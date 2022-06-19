'''
collection.py
This is the model for notebook Collections.

RCU is a synchronization tool for the reMarkable Tablet.
Copyright (C) 2020  Davis Remmel

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''

import log
from datetime import datetime
import uuid
import json
import re
from pathlib import Path

class Collection:
    pathpfx = '$HOME/.local/share/remarkable/xochitl'

    def __str__(self):
        return '{}\t{}\t{}'.format(self.uuid,
                                   self.visible_name,
                                   self.last_modified)
    
    def __init__(self, model):
        self.model = model

        self.content_dict = {}
        
        self.uuid = str(uuid.uuid4())
        self.deleted = False
        self.last_modified = None
        self.metadatamodified = True
        self.modified = True
        self.parent = None
        self.pinned = False
        self.synced = False
        self.version = 0
        self.visible_name = 'Untitled Collection'
        
    def from_dict(self, adict):
        self.uuid = adict['id']
        self.deleted = adict['deleted']
        self.last_modified = adict['lastModified']
        self.metadatamodified = adict['metadatamodified']
        self.modified = adict['modified']
        self.parent = adict['parent']
        self.pinned = adict['pinned']
        self.synced = adict['synced']
        self.version = adict['version']
        self.visible_name = adict['visibleName']
        return self
        
    def as_dict(self):
        return {
            'deleted': self.deleted,
            'lastModified': self.last_modified,
            'metadatamodified': self.metadatamodified,
            'modified': self.modified,
            'parent': self.parent,
            'pinned': self.pinned,
            'synced': self.synced,
            'type': 'CollectionType',
            'version': self.version,
            'visibleName': self.visible_name
        }

    def get_pin(self):
        return self.pinned

    def get_last_modified_date(self):
        date = datetime.fromtimestamp(int(self.last_modified) / 1000)
        return date

    def get_pretty_name(self):
        return self.visible_name

    def get_sanitized_filepath(self, ext=None):
        name = self.get_pretty_name()
        # If adjacent to another collection with same pretty name, then
        # this will use the ID as part of the sanitized name (no
        # preference).
        for c in self.model.collections:
            if c.parent == self.parent \
               and c.uuid != self.uuid \
               and c.get_pretty_name() == self.get_pretty_name():
                name += '-' + self.uuid[:8]
                break
        sanitized = re.sub('[\/\\\!\@\#\$\%\^\&\*\~\|\:\;\?\`]', '_',
                               name)
        return Path(sanitized)

    def estimate_size(self, abort_func=lambda: ()):
        # Assume that folders don't take up any space, so recursively
        # add up the documents contained within. Have to search inside
        # the model to find children, both collections and documents.
        totalsize = 0
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                totalsize += c.estimate_size(abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                totalsize += d.estimate_size(abort_func)
        return totalsize
        
    def write_metadata_out(self):
        js = json.dumps(self.as_dict(), sort_keys=True, indent=4)
        cmd = 'cat > "{}/{}.metadata"'.format(type(self).pathpfx,
                                              self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(js)
        stdin.close()

        content_js = json.dumps(self.content_dict,
                                sort_keys=True, indent=4)
        cmd = 'cat > "{}/{}.content"'.format(type(self).pathpfx,
                                             self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(content_js)
        stdin.close()

    def delete(self):
        # Deletes self
        # In order to accomodate cloud users, we only can set the
        # deleted flag and let reMarkable's software take it the rest of
        # the way.
        if self.model.device_info['cloud_user']:
            self.deleted = True
            self.version += 1
            self.write_metadata_out()
            self.model.collections.discard(self)
        else:
            # Purge files immediately
            cmd = 'rm -rf {}/{}*'.format(type(self).pathpfx, self.uuid)
            out, err = self.model.run_cmd(cmd)
            if len(err):
                log.error('problem deleting collection')
                log.error('problem command: {}'.format(cmd))
                log.error(err)
                return
            self.model.documents.discard(self)

    def move_to_parent(self, parent_collection=None):
        # Moves this item into a parent collection
        # Todo...some type checking
        if not parent_collection:
            parent_id = ''
        else:
            parent_id = parent_collection.uuid

        # If the parent doesn't change, abort
        if self.parent == parent_id:
            return False

        self.parent = parent_id
        self.version += 1
        self.write_metadata_out()
        return True

    def rename(self, newname=None):
        # Renames self
        if not newname or '' == newname:
            return False
        self.visible_name = newname
        self.version += 1
        self.write_metadata_out()
        return True

    def pin(self):
        self.pinned = True
        self.write_metadata_out()

    def unpin(self):
        self.pinned = False
        self.write_metadata_out()

    def get_num_child_documents(self):
        # Recursively adds the total of the number of Documents which
        # are a descendant of this node.
        total = 0
        for c in self.model.collections:
            if c.parent == self.uuid:
                total += c.get_num_child_documents()
        for d in self.model.documents:
            if d.parent == self.uuid:
                total += 1
        return total

    def save_archive(self, filepath, est_bytes,
                     bytes_cb=lambda x=None: (),
                     abort_func=lambda x=None: ()):
        # Create the directory on-disk (if it doesn't already exist).
        # Then, fill it with the actual document archives.
        
        # Todo: visible_name needs sanitation!
        filepath.mkdir(parents=True, exist_ok=True)

        btransferred = 0

        def emitthrough(bytecount):
            bytes_cb(btransferred + bytecount)
        
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                btransferred += c.save_archive(
                    filepath / c.get_sanitized_filepath(),
                    est_bytes, emitthrough, abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                btransferred += d.save_archive(
                    filepath / d.get_sanitized_filepath(),
                    est_bytes, emitthrough, abort_func)

        return btransferred

    def save_pdf(self, filepath, vector=True, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        filepath.mkdir(parents=True, exist_ok=True)

        num_docs = self.get_num_child_documents()
        docs_done = 0

        def progshim(pct):
            mod = (docs_done / num_docs * 100) + (pct / num_docs)
            prog_cb(mod)
        
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                docs_done += c.save_pdf(
                    filepath / c.get_sanitized_filepath(),
                    vector=vector, prog_cb=progshim,
                    abort_func=abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                d.save_pdf(
                    filepath / d.get_sanitized_filepath('.pdf'),
                    vector=vector, prog_cb=progshim,
                    abort_func=abort_func)
                docs_done += 1

        return docs_done

    def save_original_pdf(self, filepath, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        filepath.mkdir(parents=True, exist_ok=True)

        num_docs = self.get_num_child_documents()
        docs_done = 0

        def progshim(pct):
            mod = (docs_done / num_docs * 100) + (pct / num_docs)
            prog_cb(mod)
        
        for c in self.model.collections:
            if not abort_func() and self.uuid == c.parent:
                docs_done += c.save_original_pdf(
                    filepath / c.get_sanitized_filepath(),
                    prog_cb=progshim,
                    abort_func=abort_func)
        for d in self.model.documents:
            if not abort_func() and self.uuid == d.parent:
                d.save_original_pdf(
                    filepath / d.get_sanitized_filepath('.pdf'),
                    prog_cb=progshim,
                    abort_func=abort_func)
                docs_done += 1

        return docs_done
        
