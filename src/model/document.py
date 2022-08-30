'''
document.py
This is the model for a document.

RCU is a synchronization tool for the reMarkable Tablet.
Copyright (C) 2020-21  Davis Remmel
Copyright (C) 2021  Robert Schroll

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

from model.pens import *
import log
import tempfile
from datetime import datetime
import tarfile
from pathlib import Path
from model.template import Template
import uuid
import json
from model import lines
import gc
import shutil
import time
import os
import ctypes
import re

#from PySide2.QtWidgets import QGraphicsScene
from PySide2.QtGui import QPainter, QImage, QPen, QPixmap, \
    QPageSize, QColor, QBrush, QPainterPath, QTransform
from PySide2.QtCore import Qt, QByteArray, QIODevice, QBuffer, QSizeF, \
    QSettings, QRectF, QPointF
from PySide2.QtPrintSupport import QPrinter

from pdfrw.pdfrw import PdfReader, PdfWriter, PageMerge, PdfDict, \
    PdfArray, PdfName, IndirectPdfDict, uncompress, compress

import svgtools


def rmdir(path):
    if path.is_file() and path.exists():
        path.unlink()
    try:
        for child in path.glob('*'):
            if child.is_file():
                child.unlink()
            else:
                rmdir(child)
        path.rmdir()
    except:
        pass


class Document:
    pathpfx = '$HOME/.local/share/remarkable/xochitl'

    def __str__(self):
        return '{}\t{}\t{}'.format(self.uuid,
                                   self.visible_name,
                                   self.last_modified)

    # Pass the model just so documents can handle their own PDF
    # conversion.
    def __init__(self, model):
        self.model = model

        self.use_local_archive = None

        self.uuid = str(uuid.uuid4())
        self.filetype = 'notebook'

        self.deleted = None
        self.last_modified = None
        self.metadatamodified = None
        self.modified = None
        self.parent = None
        self.pinned = None
        self.synced = None
        self.version = 1
        self.visible_name = None

        # Imported from on-device notebook
        self.contentdict = {}

    def from_dict(self, adict):
        if 'id' in adict:
            self.uuid = adict['id']
        if 'filetype' in adict:
            self.filetype = adict['filetype']

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
            'type': 'DocumentType',
            'version': self.version,
            'visibleName': self.visible_name
        }

    def get_pin(self):
        return self.pinned

    def get_last_modified_date(self):
        # There is a bug in Windows that a user hit. Windows cannot cast
        # datetimes which are negative. I'm not sure how the user got
        # their notebooks with negative lastModified timestamps.
        try:
            date = datetime.fromtimestamp(int(self.last_modified) / 1000)
            return date
        except Exception as e:
            # Negative timestamps are set from the reMarkable Send From
            # Chrome browser plugin. Silently fail.
            pass
        return None

    def get_pretty_name(self):
        return self.visible_name

    def get_sanitized_filepath(self, ext='.rmn'):
        name = self.get_pretty_name()
        # If adjacent to another document with the same pretty name,
        # this wil use the ID as part of the sanitized name (no
        # preference).
        for d in self.model.documents:
            if d.parent == self.parent \
               and d.uuid != self.uuid \
               and d.get_pretty_name() == self.get_pretty_name():
                name += '-' + self.uuid[:8]
                break
        sanitized = re.sub('[\/\\\!\@\#\$\%\^\&\*\~\|\:\;\?\`\’\“\'\"]',
                           '_',
                           name)
        return Path(sanitized + ext)

    def get_tsfm(self):
        tsfm = {
            'm11': 1, 'm12': 0, 'm13': 0,
            'm21': 0, 'm22': 1, 'm23': 0,
            'm31': 0, 'm32': 0, 'm33': 1
        }
        if 'transform' in self.contentdict:
            tsfm = self.contentdict['transform']
        return tsfm

    def write_metadata_out(self):
        # Always increment the version number by 1 before writing, to
        # force a cloud sync of new data (if the user has that).
        self.version += 1

        js = json.dumps(self.as_dict(), sort_keys=True, indent=4)
        cmd = 'cat > "{}/{}.metadata"'.format(type(self).pathpfx,
                                              self.uuid)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        stdin.write(js)
        stdin.close()

    def delete(self):
        # Deletes self
        # In order to accomodate cloud users, we only can set the
        # deleted flag and let reMarkable's software take it the rest of
        # the way.
        if self.model.device_info['cloud_user']:
            self.deleted = True
            self.write_metadata_out()
            self.model.documents.discard(self)
        else:
            # Purge files immediately
            cmd = 'rm -rf {}/{}*'.format(type(self).pathpfx, self.uuid)
            out, err = self.model.run_cmd(cmd)
            if len(err):
                log.error('problem deleting notebook')
                log.error('problem command: {}'.format(cmd))
                log.error(err)
                return
            self.model.documents.discard(self)

    def pin(self):
        self.pinned = True
        self.write_metadata_out()

    def unpin(self):
        self.pinned = False
        self.write_metadata_out()

    def rename(self, newname=None):
        # Renames self
        if not newname or '' == newname:
            return False
        self.visible_name = newname
        self.write_metadata_out()
        return True

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
        self.write_metadata_out()
        return True

    def get_manifest_strings(self):
        # Document Files
        pathpfx = '$HOME/.local/share/remarkable/xochitl'
        taritems = [
            self.uuid,
            self.uuid + '.content',
            self.uuid + '.metadata',
            self.uuid + '.pagedata',
            self.uuid + '.highlights',
            self.uuid + '.bookmarks'
        ]
        if 'pdf' == self.filetype:
            taritems.append(self.uuid + '.' + self.filetype)
        elif 'epub' == self.filetype:
            taritems.append(self.uuid + '.' + self.filetype)
            # also rm-converted pdf
            taritems.append(self.uuid + '.pdf')
        taritemstring = ' '.join(taritems)
        return (pathpfx, taritemstring)

        # Template Files
        #pathpfx = '/usr/share/remarkable/templates'

    def estimate_size(self, abort_func=lambda: ()):
        r = self.get_manifest_strings()
        pathpfx = r[0]
        taritemstring = r[1]
        # get estimated file size
        cmd = '(cd {} && du -ck {} 2>/dev/null | grep total | cut -f1)'.format(
            pathpfx, taritemstring)
        if abort_func():
            return
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('error getting estimated file archive size')
            log.error(err)
            return False
        # Adds 4k for good measure
        estsizeb = (int(out) + 4) * 1024
        return estsizeb

    def upload_file(self, filepath, parent, bytes_cb=lambda x: (),
                    abort_func=lambda x=None: ()):
        # Uploads a PDF or Epub file to the tablet.

        # This is going to be a new document that is written back out to
        # the tablet.
        txbytes = 0

        # This ought to be a dummy document, so we can use itself
        self.filetype = filepath.suffix.replace('.', '').lower()
        self.last_modified = str(round(time.time() * 1000))
        self.visible_name = filepath.stem

        if parent:
            self.parent = parent.uuid

        # Using new UUID, upload PDF to tablet
        cmd = 'cat > {}/{}.{}'.format(
            type(self).pathpfx, self.uuid, self.filetype)
        out, err, stdin = self.model.run_cmd(
            cmd, raw_noread=True, with_stdin=True)
        with open(filepath, 'rb') as pdf:
            for chunk in iter(lambda: pdf.read(4096), b''):
                stdin.write(chunk)
                txbytes += len(chunk)
                bytes_cb(txbytes)
            pdf.close()
            stdin.close()

        self.write_metadata_out()

        # Is that it, or do we need content too? Will that be created?
        # This should probably be stored in this object, with an
        # associated write_content_out() method. TODO
        dumcdict = {
            'dummyDocument': False,
            'extraMetadata': {},
            'fileType': self.filetype,
            'fontName': '',
            'lastOpenedPage': 0,
            'legacyEpub': False,
            'lineHeight': -1,
            'margins': 100,
            'orientation': 'portrait',
            'pageCount': 0,
            'textScale': 1,
            'transform': {
                'm11': 1,
                'm12': 0,
                'm13': 0,
                'm21': 0,
                'm22': 1,
                'm23': 0,
                'm31': 0,
                'm32': 0,
                'm33': 1
            }
        }

        jsons = json.dumps(dumcdict, sort_keys=True, indent=4)
        cmd = 'cat > {}/{}.content'.format(
            type(self).pathpfx, self.uuid)
        out, err, stdin = self.model.run_cmd(
            cmd, raw_noread=True, with_stdin=True)
        stdin.write(jsons)
        stdin.close()

        return txbytes

    def upload_archive(self, filepath, parent,
                       bytes_cb=lambda x: (),
                       abort_func=lambda x=None: ()):
        # Uploads an .rmn archive to the tablet.

        tf = tarfile.open(filepath)
        names = tf.getnames()
        tf.close()
        template_names = []
        for name in names:
            if '.metadata' in name:
                self.uuid = name.replace('.metadata', '')
            if '.rmt' in name:
                template_names.append(name)

        # Always increment the version number by 1 to force cloud
        # sync.
        existing_version = None
        pre_metadata = self.get_metadata_from_device()
        if pre_metadata:
            self.from_dict(pre_metadata)
            existing_version = pre_metadata['version']

        # send file to device
        exclude_tmps = '\\n'.join(template_names)
        f = open(filepath, 'rb')
        cmd = 'echo -e "{}" > /tmp/exclude.txt && tar xpf - -X /tmp/exclude.txt -C {}; rm -f /tmp/exclude.txt'.format(
            exclude_tmps, type(self).pathpfx)
        out, err, ins = self.model.run_cmd(cmd,
                                           raw_noread=True,
                                           with_stdin=True)
        txbytes = 0
        while True:
            if abort_func():
                # Force reconnect to terminate tar
                # self.model.reconnect()
                self.model.run_cmd('killall tar')
                break
            chunk = f.read(4096)
            if chunk:
                ins.write(chunk)
                txbytes += len(chunk)
                bytes_cb(txbytes)
            else:
                break
        f.close()
        ins.close()

        # If the templates don't already exist on the device,
        # extract them.
        tmpd = Path(tempfile.mkdtemp())
        tf = tarfile.open(filepath)
        for name in template_names:
            tm = tf.getmember(name)
            th, tmp = tempfile.mkstemp()
            os.close(th)
            tmpt = Path(tmp)
            tf.extract(tm, tmpd)
            # This can probably be corrected with
            # model.add_new_template_from_archive
            # but that function needs some work to install if doesn't
            # exist
            fname = name.split('.')[0]
            if not self.model.template_is_loaded(fname):
                template = self.model.add_new_template_from_archive(
                    Path(tmpd / name))
                log.info('installing {}', name)
                template.install_to_device()
            tmpt.unlink()
        tf.close()
        rmdir(tmpd)

        # Update the version number
        if existing_version:
            metadata = self.get_metadata_from_device()
            self.from_dict(metadata)
            self.version = existing_version
            self.write_metadata_out()

        # Change the parent
        if parent:
            metadata = self.get_metadata_from_device()
            self.from_dict(metadata)
            self.parent = parent.uuid
            self.write_metadata_out()

        return txbytes

    def get_metadata_from_device(self):
        # Does not load the metadata, only returns it as a dict.
        cmd = 'cat "{}/{}.metadata"'.format(
            type(self).pathpfx, self.uuid)
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('could not load metadata from device')
            log.error(err)
        else:
            metadata = json.loads(out)
            return metadata
        return

    def save_archive(self, filepath, est_bytes=0,
                     bytes_cb=lambda x=None: (),
                     abort_func=lambda x=None: ()):
        if abort_func():
            return 0
        # Actually saves a document/collection from the device to disk.
        # Returns the total bytes of the tar transferred to disk.

        # Identify parent items. Use this function recursively for all
        # parents.
        # todo... (for Collection type)

        # Download tar from device
        r = self.get_manifest_strings()
        pathpfx = r[0]
        taritemstring = r[1]
        btransferred = 0

        cmd = 'tar cf - -C {} {}'.format(
            pathpfx, taritemstring)
        out, err = self.model.run_cmd(cmd, raw_noread=True)
        with open(filepath, 'wb+') as destfile:
            while True:
                if abort_func():
                    # Force reconnect to terminate tar
                    # self.model.reconnect()
                    self.model.run_cmd('killall tar')
                    break
                chunk = out.read(4096)
                if chunk:
                    destfile.write(chunk)
                    btransferred += len(chunk)
                    bytes_cb(btransferred)
                else:
                    break
            destfile.close()
            # Delete partially-transmitted file
        if abort_func():
            filepath.unlink()

        # Add templates to the tar archive
        cmd = 'cat "{}/{}.pagedata" | sort | uniq'.format(
            type(self).pathpfx, self.uuid)
        out, err = self.model.run_cmd(cmd)
        tids = set(out.splitlines())
        outtar = tarfile.open(filepath, 'a')
        for tid in tids:
            found = False
            for t in self.model.templates:
                if t.filename == tid:
                    # found it
                    found = True
                    th, tmp = tempfile.mkstemp()
                    os.close(th)
                    tmpfile = Path(tmp)
                    t.load_svg_from_device()
                    t.save_archive(tmpfile)
                    outtar.add(tmpfile,
                               arcname=Path(t.get_id_archive_name()))
                    tmpfile.unlink()
                    break
            if not found:
                # TODO tid is empty
                log.error('Unable to add template to archive: {}'.format(tid))
        outtar.close()

        # If a transfer fails, maybe we should return the estimated
        # size as to not mess up the progress meter?
        return btransferred

    def save_original_pdf(self, filepath, prog_cb=lambda x: (),
                          abort_func=lambda: False):
        # Just downloads the original PDF to disk, directly from the
        # rM--no need to download the whole .rmn.
        log.info('save_original_pdf')

        if abort_func():
            return

        pdfpath = '{}/{}.pdf'.format(type(self).pathpfx, self.uuid)

        cmd = 'wc -c "{}" | cut -d" " -f1'.format(pdfpath)
        out, err = self.model.run_cmd(cmd)
        if (err):
            log.error('could not get length for original pdf')
            log.error(err)
            return
        blength = int(out)

        if abort_func():
            return

        bdone = 0
        with open(filepath, 'wb') as outfile:
            cmd = 'cat "{}"'.format(pdfpath)
            out, err = self.model.run_cmd(cmd, raw_noread=True)
            for chunk in iter(lambda: out.read(4096), b''):
                if abort_func():
                    break
                outfile.write(chunk)
                bdone += len(chunk)
                prog_cb(bdone / blength * 100)
            outfile.close()

        if abort_func():
            filepath.unlink()
            return

        return True

    def save_pdf(self, filepath, vector=True, prog_cb=lambda x: (),
                 abort_func=lambda: False):
        # Exports the self as a PDF document to disk

        # prog_cb should emit between 0-100 (percent complete).
        # Percentages are split between three processes. Downloading the
        # archive takes the first 50%. If there is not a base PDF, the
        # RM page rasterization takes the next 50%. If there is a base
        # PDF, then the page rasterization takes 25% and the PDF
        # merging takes another 25%.

        # This holds stuff to clean up
        cleanup_stuff = set()

        def cleanup():
            for thing in cleanup_stuff:
                rmdir(thing)

        if abort_func():
            return

        # Load pencil textures (shared for brushes, takes a lot of time
        # because there are many)
        from model.pens.textures import PencilTextures
        pencil_textures = PencilTextures()

        # This res_mod is the resolution modifier--users can set a
        # super-resolution (usually 4x).
        res_mod = 2 if bool(int(QSettings().value(
            'pane/notebooks/export_pdf_hires'))) else 1

        # Note: this is kind of hacky because it is a pseudo-
        # document. Ideally, a document should be able to load from
        # either the device or a file on-disk, but to save a pdf
        # requires a lot of file manipulation, so I'd rather just keep
        # all the operations local (at least, for now).

        # Extract the archive to disk in some temporary directory

        if self.use_local_archive:
            tmparchive = Path(self.use_local_archive)
        else:
            th, tmp = tempfile.mkstemp()
            os.close(th)
            tmparchive = Path(tmp)
            cleanup_stuff.add(tmparchive)
            est_bytes = self.estimate_size()
            self.save_archive(tmparchive, est_bytes,
                              abort_func=abort_func,
                              bytes_cb=lambda x: prog_cb(
                                  x / est_bytes * 50))

        if abort_func():
            cleanup()
            return
        tmpdir = Path(tempfile.mkdtemp())
        cleanup_stuff.add(tmpdir)
        with tarfile.open(tmparchive, 'r') as tar:
            tar.extractall(path=tmpdir)
            tar.close()
        # cleanup()

        # If using a local archive, load all document metadata now.
        if self.use_local_archive:
            mdname = None
            tf = tarfile.open(self.use_local_archive)
            names = tf.getnames()
            tf.close()
            for name in names:
                if '.metadata' in name:
                    mdname = name
            if not mdname:
                log.error('no metadata file in archive')
                return

            tf = tarfile.open(self.use_local_archive)
            tm = tf.getmember(mdname)
            tmpmd = tf.extractfile(tm)
            mdj = json.load(tmpmd)
            mdj['id'] = mdname.replace('.metadata', '')
            self.from_dict(mdj)

            tf.close()

        # If this is using a base PDF, the percentage is calculated
        # differently.
        pdfpath = Path(tmpdir / Path(self.uuid + '.pdf'))
        uses_base_pdf = pdfpath.exists()

        # Document metadata should already be loaded (from device)
        # ...

        # Generate page information
        contentpath = Path(tmpdir / Path(self.uuid + '.content'))
        if contentpath.exists():
            with open(contentpath, 'r') as f:
                self.contentdict = json.load(f)
                f.close()
        # If a PDF file was uploaded, but never opened, there may not be
        # a .content file. So, just load a barebones one with a 'pages'
        # key of zero length, so it doesn't break the rest of the
        # process. This is here, instead of in __init__, because it is
        # more explainable/straightforward here.
        if not 'pages' in self.contentdict:
            self.contentdict['pages'] = []

        # Render each page as a pdf
        th, tmp = tempfile.mkstemp()
        os.close(th)
        tmprmpdf = Path(tmp)
        cleanup_stuff.add(tmprmpdf)
        pdf = QPrinter()
        res = type(self.model.display).dpi
        width, height = type(self.model.display).portrait_size
        # Qt docs say 1 pt is always 1/72 inch
        # Multiply ptperpx by pixels to convert to PDF coords
        ptperpx = 72 / res
        pdfheight = height * ptperpx
        pdfwidth = width * ptperpx
        pdf.setPaperSize(QSizeF(width / res, height / res), QPrinter.Inch)
        pdf.setResolution(res*res_mod)
        pdf.setOutputFormat(QPrinter.PdfFormat)
        pdf.setPageMargins(0, 0, 0, 0, QPrinter.Inch)
        pdf.setOutputFileName(str(tmprmpdf))

        # Don't load all the pages into memory, because large notebooks
        # about 500 pages could use up to 3 GB of RAM. Create them by
        # iteration so they get released by garbage collector.
        changed_pages = []
        painter = QPainter(pdf)
        annotations = []
        for i in range(0, len(self.contentdict['pages'])):
            if abort_func():
                painter.end()
                cleanup()
                return

            page = DocumentPage(self, i, tmpdir, self.model.display,
                                pencil_textures=pencil_textures,
                                res_mod=res_mod)

            if page.rmpath.exists():
                changed_pages.append(i)

            page.render_to_painter(painter, vector)
            annotations.append(page.get_grouped_annotations())
            if i < len(self.contentdict['pages'])-1:
                pdf.newPage()
            progpct = (i + 1) / len(self.contentdict['pages']) * 25 + 50
            prog_cb(progpct)
        painter.end()

        # This new PDF represents just the notebook. If there was a
        # parent PDF, merge it now.
        if uses_base_pdf and not len(changed_pages):
            if abort_func():
                cleanup()
                return
            # Since there is no stroke data, verbatim copy the PDF.
            # pdfpath.rename(filepath)
            shutil.move(pdfpath, filepath)
            prog_cb(100)
        else:
            if abort_func():
                cleanup()
                return

            # PDF exists, stroke data exists, so mix them together.
            if uses_base_pdf:
                rmpdfr = PdfReader(tmprmpdf)
                basepdfr = PdfReader(pdfpath)
            else:
                basepdfr = PdfReader(tmprmpdf)
                # Alias, which is used for annotations and layers.
                rmpdfr = basepdfr

            pdfw = PdfWriter()

            # If making a 'layered' PDF (with optional content groups,
            # OCGs), associate the annoatations with the layer.

            # This property list is put into the rmpdfr document, which
            # will not have any existing properties.
            ocgprop = IndirectPdfDict(
                OCGs=PdfArray(),
                D=PdfDict(Order=PdfArray()))

            for i in range(0, len(basepdfr.pages)):
                if abort_func():
                    cleanup()
                    return

                def release_progress():
                    # This emits the other 25% of the progress. Only
                    # run this method when this page is finished
                    # processing.
                    progpct = ((i + 1) / rmpdfr.numPages * 25) + 75
                    prog_cb(progpct)

                basepage = basepdfr.pages[i]
                rmpage = rmpdfr.pages[i]

                # Apply OCGs
                apply_ocg = bool(int(QSettings().value(
                    'pane/notebooks/export_pdf_ocg')))
                if apply_ocg:
                    ocgpage = IndirectPdfDict(
                        Type=PdfName('OCG'),
                        Name='Page ' + str(i+1))
                    ocgprop.OCGs.append(ocgpage)

                    # The Order dict is a Page, followed by Inner
                    ocgorderinner = PdfArray()

                    # Add Template OCG layer
                    # If this uses a basepdf, the template is located
                    # elsewhere.

                    # If using a basepdf, assign its stream as a
                    # 'Background' layer under this page. When the page
                    # primary OCG is disabled, the background will
                    # remain, making it easy to disable all annotations.
                    if uses_base_pdf:
                        ocgorigdoc = IndirectPdfDict(
                            Type=PdfName('OCG'),
                            Name='Background')
                        ocgprop.OCGs.append(ocgorigdoc)
                        ocgorderinner.append(ocgorigdoc)

                        # If the basepage can't be uncompressed, such as
                        # if it is password protected, or due to any
                        # other unsupported decompression filter in
                        # pdfrw, then skip the background OCG.

                        def apply_background_ocg():
                            if not hasattr(basepage.Contents, 'stream'):
                                # This is a hack that will let the PDF pass
                                # through the rest of this block, but will
                                # not actually work when de-selecting the
                                # 'Background' OCG layer in a PDF reader.
                                stream = basepage.Contents[0].stream
                            else:
                                stream = basepage.Contents.stream
                            stream = '/OC /ocgorigdoc BDC\n' \
                                + stream \
                                + 'EMC\n'
                            basepage.Contents.stream = stream
                            compress.compress([basepage.Contents])
                            if '/Properties' in basepage.Resources:
                                props = basepage.Resources.Properties
                            else:
                                props = PdfDict()
                            props.ocgorigdoc = ocgorigdoc
                            basepage.Resources.Properties = props

                        ok = uncompress.uncompress([basepage.Contents])
                        if ok:
                            apply_background_ocg()
                        else:
                            log.error(
                                'could not decompress background page; continuing anyway')

                    # If not using a basepdf, assign the rmpage's stream
                    # as a 'Template' layer under this page. It will be
                    # affected by disabling the primary Page OCG (which
                    # by itself is kind of useless for exported
                    # notebooks).

                    # Regardless of using a basepdf or not, put the
                    # rmpage layers into their own OCGs.

                    # If the template has an XObject, we want to skip
                    # the first one. This happens when the template
                    # contains a PNG. Question--what happens when the
                    # template contains more than one PNG? How do we
                    # detect all of those?

                    template_xobj_keys = []
                    vector_layers = []
                    uncompress.uncompress([rmpage.Contents])
                    if uses_base_pdf:
                        # The entire thing is the page ocg
                        stream = '/OC /ocgpage BDC\n'
                        stream += rmpage.Contents.stream
                        stream += 'EMC\n'
                        rmpage.Contents.stream = stream
                    else:
                        stream = rmpage.Contents.stream
                        # Mark the template ocg separate from page ocg
                        template_endpos = 0
                        page_inatpos = 0
                        findkey = '1 w 2 J 2 j []0  d\nq\n'
                        # Finds only the first instance, which should be
                        # for the template.
                        findloc = stream.find(findkey)
                        if findloc < 0:
                            # May be a vector, which we stick a marker
                            # in for.
                            # ?? Why is this a half-point off ??
                            findkey = '799.500000 85 l\n'
                            m = re.search(
                                findkey,
                                rmpage.Contents.stream)
                            if m:
                                findloc = m.start()
                        if findloc > 0:
                            template_endpos = findloc + len(findkey)
                            # Add vector template OCG
                            stream = '/OC /ocgtemplate BDC\n'
                            stream += rmpage.Contents.stream[:template_endpos]
                            stream += 'EMC\n'
                            page_inatpos = len(stream)
                            stream += rmpage.Contents.stream[template_endpos:]
                            # Save stream
                            rmpage.Contents.stream = stream

                        # Add template ocg
                        ocgtemplate = IndirectPdfDict(
                            Type=PdfName('OCG'),
                            Name='Template')
                        ocgprop.OCGs.append(ocgtemplate)
                        ocgorderinner.append(ocgtemplate)

                        # If a template (which is SVG) has embedded PNG
                        # images, those appear as XObjects. This will
                        # mess up the layer order, so we will ignore
                        # them later.
                        template_xobj_keys = \
                            re.findall('(\/Im[0-9]+)\s',
                                       stream[:template_endpos])

                        # Page ocg
                        stream = rmpage.Contents.stream[:page_inatpos]
                        stream += '/OC /ocgpage BDC\n'
                        stream += rmpage.Contents.stream[page_inatpos:]
                        stream += 'EMC\n'
                        # Save stream
                        rmpage.Contents.stream = stream

                    # Find all other vector layers using the magic
                    # point (DocumentPageLayer.render_to_painter()).
                    # ?? Why is this a half-point off ??
                    while True:
                        m = re.search(
                            '420.500000 69 m\n',
                            rmpage.Contents.stream)
                        if not m:
                            break
                        stream = ''
                        layerid = 'ocglayer{}'.format(
                            len(vector_layers) + 1)
                        stream = rmpage.Contents.stream[:m.start()]
                        if len(vector_layers):
                            # close previous layer
                            stream += 'EMC\n'
                        stream += '/OC /{} BDC\n'.format(layerid)
                        stream += rmpage.Contents.stream[m.end():]
                        vector_layers.append(layerid)
                        rmpage.Contents.stream = stream
                    # If we added vector layers, have to end the
                    # first one.
                    if len(vector_layers):
                        stream = rmpage.Contents.stream + 'EMC\n'
                        rmpage.Contents.stream = stream

                    # Done--recompress the stream.
                    compress.compress([rmpage.Contents])

                    # There shouldn't be any Properties there since we
                    # generated the rmpage ourselves, so don't bother
                    # checking.
                    rmpage.Resources.Properties = PdfDict(
                        ocgpage=ocgpage)
                    if not uses_base_pdf:
                        rmpage.Resources.Properties.ocgtemplate = ocgtemplate

                    # Add individual OCG layers (Bitmap)
                    was_vector = True
                    for n, key in enumerate(rmpage.Resources.XObject):
                        if str(key) in template_xobj_keys:
                            continue
                        was_vector = False
                        l = n - len(template_xobj_keys)
                        # This would indicate a bug in the handling of a
                        # notebook.
                        try:
                            layer = annotations[i][l]
                        except:
                            log.error(
                                'could not associate XObject with layer: (i, l) ({}, {})'.format(i, l))
                            log.error(str(annotations))
                            log.error('document: {} ()').format(
                                self.uuid,
                                self.visible_name)
                            continue
                        layername = layer[0]
                        ocg = IndirectPdfDict(
                            Type=PdfName('OCG'),
                            Name=layername)
                        ocgprop.OCGs.append(ocg)
                        ocgorderinner.append(ocg)
                        rmpage.Resources.XObject[key].OC = ocg

                    # Add individual OCG layers (Vector)
                    if was_vector:
                        for l, layerid in enumerate(vector_layers):
                            # This would indicate a bug in the handling of a
                            # notebook.
                            try:
                                layer = annotations[i][l]
                            except:
                                log.error('could not associate layerid with layer: (i, l, layerid) ({}, {}, {})'.format(
                                    i, l, layerid))
                                log.error('document: {} ()').format(
                                    self.uuid,
                                    self.visible_name)
                                log.error(str(annotations))
                                continue
                            layername = layer[0]
                            ocg = IndirectPdfDict(
                                Type=PdfName('OCG'),
                                Name=layername)
                            ocgprop.OCGs.append(ocg)
                            ocgorderinner.append(ocg)
                            rmpage.Resources.Properties[PdfName(layerid)] = \
                                ocg

                    # Add order of OCGs to primary document
                    ocgprop.D.Order.append(ocgpage)
                    ocgprop.D.Order.append(ocgorderinner)

                # Apply annotations to the rmpage. This must come after
                # applying OCGs, because the annotation may belong to
                # one of those groups.
                page_annot = annotations[i]

                for k, layer_a in enumerate(page_annot):
                    layerannots = layer_a[1]
                    for a in layerannots:
                        # PDF origin is in bottom-left, so invert all
                        # y-coordinates.
                        author = self.model.device_info['rcuname']
                        pdf_a = PdfDict(Type=PdfName('Annot'),
                                        Rect=PdfArray([
                                            (a[1].left()/res_mod * ptperpx),
                                            (a[1].bottom()/res_mod * ptperpx),
                                            (a[1].right()/res_mod * ptperpx),
                                            (a[1].top()/res_mod * ptperpx)]),
                                        T=author,
                                        ANN='pdfmark',
                                        Subtype=PdfName(a[0]),
                                        # Subtype=PdfName('Square'),
                                        P=rmpage,
                                        Contents=a[2] if len(a) > 2 else None)
                        # Set to indirect because it makes a cleaner PDF
                        # output.
                        pdf_a.indirect = True
                        if apply_ocg:
                            pdf_a.OC = ocgorderinner[k]
                        if not '/Annots' in rmpage:
                            rmpage.Annots = PdfArray()
                        rmpage.Annots.append(pdf_a)

                # If this is a normal notebook with highlighting,
                # just add the annotations and forget about the rest,
                # which are page geometry transformations.
                if not uses_base_pdf:
                    release_progress()
                    continue

                # The general appraoch is to keep the base PDF. So, all
                # operations must be made upon the basepage. PyPDF2 will
                # keep all those pages' metadata and annotations,
                # including the paper size. However, a few things must
                # also occur.

                # The basepage must be reisized to the ratio of the rM
                # page so that no brush strokes get cut.

                # The new (rM) page must be resized to the dimensions of
                # the basepage. The PDF standard allows different page
                # sizes in one document, so each page must be measured.

                # ...

                # There is a bug here that can be seen with the NH file
                # It is possible (why?) for a page not to have a
                # MediaBox, so one must be taken from the parent. The
                # rM adds a bit to the width AND the height on this
                # file.
                bpage_opts = ['basepage.CropBox',
                              'basepage.Parent.CropBox',
                              'basepage.MediaBox',
                              'basepage.Parent.MediaBox',
                              'basepdfr.Root.Pages.CropBox',
                              'basepdfr.Root.Pages.MediaBox']

                # Test exist
                got_opt = None
                for k, v in enumerate(bpage_opts):
                    try:
                        n = eval(v)
                        if n:
                            # log.info('got boudning box', k, v, n)
                            got_opt = v
                            break
                    except:
                        pass
                if not got_opt:
                    log.error(
                        'Could not find a CropBox or MediaBox in basepdf! Aborting.')
                    return
                bpage_box = n

                if not bpage_box:
                    log.error('no basepage box!!!')
                bpage_w = float(bpage_box[2]) - float(bpage_box[0])
                bpage_h = float(bpage_box[3]) - float(bpage_box[1])
                # Round because floating point makes it prissy
                bpage_ratio = round(bpage_w / bpage_h * 10000) / 10000
                landscape_bpage = False
                if bpage_w > bpage_h:
                    landscape_bpage = True
                # Detect existing rotation
                # if basepage.Rotate in ('270'):
                    # landscape_bpage = not landscape_bpage

                # If the base PDF page was really wide, the rM rotates
                # it -90deg (CCW) on the screen, but doesn't actually
                # rotate it in the PDF. Also, if a notebook is in
                # landscape format, it remains in portrait mode during
                # the Web UI export. So, we must actually rotate the rM
                # page 90deg (CW) to fit on these wide pages.

                rpage_box = rmpage.MediaBox
                rpage_w = float(rpage_box[2]) - float(rpage_box[0])
                rpage_h = float(rpage_box[3]) - float(rpage_box[1])
                rpage_ratio = rpage_w / rpage_h

                # print('rpage started at', rpage_w, rpage_h)

                # WARNING: The following geometrical procedure is not
                # formal. This method only allows for rotations of 0
                # or 90 degrees on the basepage PDF. In order to make
                # this 'nice', it will require a restructuring of how
                # annotation geometries are carried into this section,
                # so that those annnotations plus the rmpage can be
                # used with a QTransform simultaneously. The best
                # implementation would only need minimal transformations
                # and would use the translate90/rotate() functions of
                # QTransform to move elements around, determine their
                # final positions and scales, then apply those positions
                # and scales with pdfrw. Debugging that process is
                # very time-consuming, and so this procedure stays for
                # now. An aide to that debugging can be found earlier
                # in document.py (this file) by searching 'Square', to
                # visually show where annotation geometries appear.

                if landscape_bpage:
                    rmpage.Rotate = (int(rmpage.Rotate or 0) + 90) % 360
                    rpage_ratio = rpage_h / rpage_w

                    # Annotations must be rotated because this rotation
                    # statement won't hit until the page merge, and
                    # pdfrw is unaware of annotations.
                    if '/Annots' in rmpage:
                        for a, annot in enumerate(rmpage.Annots):
                            rect = annot.Rect
                            rmpage.Annots[a].Rect = PdfArray([
                                rect[1],
                                pdfwidth - rect[0],
                                rect[3],
                                pdfwidth - rect[2]])

                # Resize the base page to the notebook page ratio by
                # adjusting the trimBox. If the basepage was landscape,
                # the trimbox must expand laterally, because the rM
                # rotates the page on-screen into portrait. If the
                # basepage was already portrait, it must expand
                # laterally.

                adjust = 0
                if bpage_ratio <= rpage_ratio:
                    # Basepage is taller, so need to expand the width.
                    # The basepage should be pushed to the right, which
                    # is also the top of the rM in portrait mode. A
                    # push to the right is really just decreasing the
                    # left side.
                    new_width = rpage_ratio * bpage_h
                    if landscape_bpage:
                        adjust = float(bpage_box[2]) - new_width
                        bpage_box[0] = adjust
                    else:
                        # Portrait documents get pushed to the left, so
                        # expand the right side.
                        adjust = float(bpage_box[0])
                        bpage_box[2] = new_width + float(bpage_box[0])
                elif bpage_ratio > rpage_ratio:
                    # Basepage is fatter, so need to expand the height.
                    # The basepage should be pushed to the top, which is
                    # also the top of the rM in portrait mode. A push to
                    # the top is really decreasing the bottom side.
                    new_height = (1 / rpage_ratio) * bpage_w
                    adjust = float(bpage_box[3]) - new_height
                    bpage_box[1] = adjust

                # Cast all to float for convenience
                for k, v in enumerate(bpage_box):
                    bpage_box[k] = float(v)

                tsfm = self.get_tsfm()
                real_transform = QTransform(tsfm['m11'], tsfm['m12'], tsfm['m13'],
                                            tsfm['m21'], tsfm['m22'], tsfm['m23'],
                                            tsfm['m31']*1404, tsfm['m32']*1872, tsfm['m33'])
                # inverse transform for basepage
                i_transform = real_transform.inverted()[0]

                bpage_box = [bpage_box[0],
                             bpage_box[1],
                             bpage_box[2],
                             bpage_box[3]]
                #            ^^^^^^^^^^^^^
                # At this point, the bpage_box is the canonical shape
                # and position of the tablet's screen. If the rotation
                # was lanscape, the notes overlay will be centered
                # over this bpage_box's center, so any rotation should
                # apply equally well.
                # print('bpage box', bpage_box)

                bpage_w = bpage_box[2] - bpage_box[0]
                bpage_h = bpage_box[3] - bpage_box[1]
                bpage_center = (bpage_box[2]-bpage_w/2, bpage_box[3]-bpage_h/2)

                # This is the 'origin' box -- the default geometry for
                # the tablet's screen, in PDF units (points).
                obox = QRectF(bpage_box[0], bpage_box[1], bpage_w, bpage_h)
                # print('origin box', obox)

                # If this wasn't a changed page, don't bother with the
                # following.
                if i in changed_pages:
                    # Scale and (if necesssary) rotate the notebook page
                    # and overlay it to the basepage. Might have to push
                    # it a bit, depending on the direction.

                    np = PageMerge(basepage).add(rmpage)

                    # The page comes in pre-transformed, so to de-
                    # transform it, do it in reverse.
                    # Use basepage coords as origin.

                    # Shift
                    if landscape_bpage:

                        # Pretend that we are sideways
                        real_transform = QTransform(tsfm['m11'], tsfm['m12'], tsfm['m13'],
                                                    tsfm['m21'], tsfm['m22'], tsfm['m23'],
                                                    tsfm['m31']*bpage_h, tsfm['m32']*bpage_w, tsfm['m33'])

                        # Since we are in portrait, the basepage is already at 0, 0.
                        bpbr = QRectF(0, 0, bpage_w, bpage_h)

                        # do inverse tranform on the bpbr
                        invt = real_transform.inverted()[0]

                        should_be = real_transform.inverted()[0].mapRect(bpbr)

                        # print('should_be', should_be)
                        should_be_scale = should_be.height() / np[1].h
                        np[1].scale(should_be_scale)

                        np[1].x = bpage_box[0] + \
                            bpbr.right() - should_be.y() - np[1].w
                        np[1].y = bpage_box[1] + bpage_h - \
                            np[1].h - should_be.x()

                        # print('landscape bpage', i)
                    else:
                        # Rightways -- no mods here
                        real_transform = QTransform(tsfm['m11'], tsfm['m12'], tsfm['m13'],
                                                    tsfm['m21'], tsfm['m22'], tsfm['m23'],
                                                    tsfm['m31']*bpage_w, tsfm['m32']*bpage_h, tsfm['m33'])

                        bpbr = QRectF(
                            bpage_box[0], bpage_box[1], bpage_w, bpage_h)
                        # print(bpbr)
                        # move to 0 0
                        opoint = (bpbr.x(), bpbr.y())
                        bpbr.moveLeft(0)
                        bpbr.moveTop(0)

                        # do inverse tranform on the bpbr
                        invt = real_transform.inverted()[0]
                        # print('invt', invt)

                        should_be = real_transform.inverted()[0].mapRect(bpbr)
                        should_be.moveLeft(opoint[0])
                        should_be.moveTop(opoint[1])
                        # print('should_be', should_be)

                        should_be_scale = should_be.width() / np[1].w
                        np[1].scale(should_be_scale)

                        hdiff = bpage_h - np[1].h
                        # print('hdiff', hdiff)
                        # This works for letter-size paper (gap of -24 on bottom)
                        np[1].x = opoint[0] + invt.m31()
                        np[1].y = opoint[1] - invt.m32() + hdiff

                    # # Save bound box
                    rm_page_box = [np[1].x, np[1].y,
                                   np[1].x+np[1].w, np[1].y+np[1].h]
                    # rm_page_box = [-200, -200, 1000, 1000]

                    if '/Annots' in rmpage:
                        for a, annot in enumerate(rmpage.Annots):
                            rect = annot.Rect

                            r = QRectF()
                            if not landscape_bpage:
                                r.setLeft(
                                    rect[0] * should_be_scale + invt.m31())
                                r.setBottom(
                                    rect[1] * should_be_scale + invt.m32())
                                r.setRight(
                                    rect[2] * should_be_scale + invt.m31())
                                r.setTop(
                                    rect[3] * should_be_scale + invt.m32())
                                r = real_transform.mapRect(r)
                                # flip
                                r = QRectF(bpage_box[0] + r.left(),
                                           bpage_box[3] - r.bottom(),
                                           r.width(),
                                           r.height())
                            else:
                                # print('invt', invt)
                                # print('should_be_scale', should_be_scale)
                                # print('should_be', should_be)
                                r.setLeft(
                                    rect[0] * should_be_scale + invt.m31())
                                r.setBottom(
                                    rect[1] * should_be_scale + invt.m32())
                                r.setRight(
                                    rect[2] * should_be_scale + invt.m31())
                                r.setTop(
                                    rect[3] * should_be_scale + invt.m32())
                                r = real_transform.mapRect(r)
                                # flip
                                r = QRectF(np[1].y + bpage_box[2] - r.right(),
                                           -np[1].x + bpage_box[0] + r.top(),
                                           r.width(),
                                           r.height())
                                # r.moveLeft(r.left() - obox.x())
                                r.moveTop(r.top() + obox.y())

                            newrect = [r.left(), r.bottom(),
                                       r.right(), r.top()]
                            rmpage.Annots[a].Rect = newrect

                    # Gives the basepage the rmpage as a new object
                    np.render()

                    # Annots aren't carried over--pdfrw isn't aware.
                    if '/Annots' in rmpage:
                        if not '/Annots' in basepage:
                            basepage.Annots = PdfArray()
                        basepage.Annots += rmpage.Annots

                    # Whatever was used as the basepage box, set that to
                    # the new page dimensions.
                    bpage_box = rm_page_box
                    exec(got_opt + ' = ' + str(bpage_box))

                release_progress()

            # Apply the OCG order. The basepdf may have already had OCGs
            # and so we must not overwrite them. NOTE: there are other
            # properties that ought to be carried over, but this is the
            # minimum required.
            if apply_ocg:
                if '/OCProperties' in basepdfr.Root:
                    basepdfr.Root.OCProperties.OCGs += ocgprop.OCGs
                    basepdfr.Root.OCProperties.D.Order += ocgprop.D.Order
                else:
                    basepdfr.Root.OCProperties = ocgprop

            pdfw.write(filepath, basepdfr)
            tmprmpdf.unlink()

        # Cleanup
        cleanup()

        # log.info('exported pdf')
        return True


class DocumentPage:
    # A single page in a document
    # From local disk!! When making agnostic later, only keep the
    # document and pagenum args.
    def __init__(self, document, pagenum, archivepath, display,
                 pencil_textures=None, res_mod=1):
        # Page 0 is the first page!
        self.document = document
        self.num = pagenum
        self.display = display  # Carried from model
        self.res_mod = res_mod
        self.pencil_textures = pencil_textures

        # get page id
        self.uuid = self.document.contentdict['pages'][pagenum]

        self.rmpath = Path(
            archivepath /
            Path(self.document.uuid) / Path(self.uuid + '.rm'))

        # Try to load page metadata
        self.metadict = None
        self.metafilepath = Path(
            archivepath / Path(self.document.uuid) /
            Path(self.uuid + '-metadata.json'))
        if self.metafilepath.exists():
            with open(self.metafilepath, 'r') as f:
                self.metadict = json.load(f)
                f.close()

        # Try to load highlights
        self.highlights = []
        self.highlightspath = Path(
            archivepath / Path(self.document.uuid + '.highlights')
            / Path(self.uuid + '.json'))
        if False and self.highlightspath.exists():      # remove 'False and'
            with open(self.highlightspath, 'r') as f:
                jdict = json.load(f)                    # TODO issue decoding utf-16
                if 'highlights' in jdict:
                    self.highlights = jdict['highlights']
                f.close()
    

        # Try to load template
        self.template = None
        tmpnamearray = []
        pagedatapath = Path(
            archivepath / Path(self.document.uuid + '.pagedata'))
        if pagedatapath.exists():
            f = open(pagedatapath, 'r')
            lines = f.read()
            for line in lines.splitlines():
                tmpnamearray.append(line)
            f.close()

        if len(tmpnamearray):
            # I have encountered an issue with some PDF files, where the
            # rM won't save the page template for later pages. In this
            # case, just take the last-available page template, which
            # is usually 'Blank'.
            tmpname = tmpnamearray[-1]
            if self.num < len(tmpnamearray):
                tmpname = tmpnamearray[self.num]
            tmparchivepath = Path(
                archivepath / Path(tmpname + '.rmt'))
            if tmparchivepath.exists():
                self.template = Template(
                    self.document.model).from_archive(tmparchivepath)

        # Load layers
        self.layers = []
        self.load_layers()

    def get_grouped_annotations(self):
        # Return the annotations grouped by proximity. If they are
        # within a distance of each other, count them as a single
        # annotation.

        # Annotations should be delivered in an array, where each
        # index is a tuple (LayerName,
        annotations = []
        for layer in self.layers:
            annotations.append(layer.get_grouped_annotations())
        return annotations

    def load_layers(self):
        # Loads layers from the .rm files

        if not self.rmpath.exists():
            # no layers, obv
            return

        # Load reMy version of page layers
        pagever = None
        pagelayers = None
        with open(self.rmpath, 'rb') as f:
            pagever, pagelayers = lines.readLines(f, self.res_mod)
            f.close()

        # Load layer data
        for i in range(0, len(pagelayers)):
            layerstrokes = pagelayers[i]

            try:
                name = self.metadict['layers'][i]['name']
            except:
                name = 'Layer ' + str(i + 1)

            layer = DocumentPageLayer(self,
                                      i,
                                      name=name,
                                      pencil_textures=self.pencil_textures)
            layer.strokes = layerstrokes
            self.layers.append(layer)

    def render_to_painter(self, painter, vector):
        # Render template layer
        if self.template and self.template.name != 'Blank':
            svgtools.template_to_painter(painter, self.template)
            # Bitmaps are rendered into the PDF as XObjects, which are
            # easy to pick out for layers. Vectors will render
            # everything inline, and so we need to add a 'magic point'
            # to mark the end of the template layer.
            if vector:
                pen = GenericPen(vector=vector)
                pen.setColor(Qt.transparent)
                painter.setPen(pen)
                painter.drawPoint(800, 85)

        # Render user layers
        for i, layer in enumerate(self.layers):
            # Bitmaps are rendered into the PDF as XObjects, which are
            # easy to pick out for layers. Vectors will render
            # everything inline, and so we need to add a 'magic point'
            # to mark the beginning of layers.
            if vector:
                pen = GenericPen(vector=vector)
                pen.setColor(Qt.transparent)
                painter.setPen(pen)
                painter.drawPoint(420, 69)
            layer.render_to_painter(painter, vector)


class DocumentPageLayer:
    pen_widths = []

    def __init__(self, page, index, name=None, pencil_textures=None):
        self.page = page
        self.name = name
        self.index = index
        self.pencil_textures = pencil_textures
    
        self.colors = [
            QSettings().value('pane/notebooks/export_pdf_blackink'),
            QSettings().value('pane/notebooks/export_pdf_grayink'),
            QSettings().value('pane/notebooks/export_pdf_whiteink'),
            
            QSettings().value('pane/notebooks/export_pdf_highlight_yellowink'),
            QSettings().value('pane/notebooks/export_pdf_highlight_greenink'),
            QSettings().value('pane/notebooks/export_pdf_highlight_pinkink'),
            
            QSettings().value('pane/notebooks/export_pdf_blueink'),
            QSettings().value('pane/notebooks/export_pdf_redink')
        ]

        # Set this from the calling func
        self.strokes = None

        # Store PDF annotations with the layer, in case actual
        # PDF layers are ever implemented.
        self.annot_paths = []

        # Find highlights (introduced with 2.7) that snap. These need
        # to be drawn seperately later, in Layer.paint_strokes().
        self.highlights = []
        try:
            self.highlights = self.page.highlights[self.index]
        except:
            pass

    def get_grouped_annotations(self):
        # return: (LayerName, [(AnnotType, minX, minY, maxX, maxY)])

        # Compare all the annot_paths to each other. If any overlap,
        # they will be grouped together. This is done recursively.
        def grouping_func(pathset):
            newset = []

            for p in pathset:
                annotype = p[0]
                path = p[1]
                text = p[2]

                # skip annotations with text (to preserve)
                if p[2]:
                    newset.append(p)
                    continue

                did_fit = False
                for i, g in enumerate(newset):
                    gannotype = g[0]
                    group = g[1]
                    # Only compare annotations of the same type
                    if gannotype != annotype:
                        continue
                    if path.intersects(group):
                        did_fit = True
                        newset[i] = (annotype, group.united(path), None)
                        break
                if did_fit:
                    continue
                # Didn't fit, so place into a new group
                newset.append(p)

            if len(newset) != len(pathset):
                # Might have stuff left to group
                return grouping_func(newset)
            else:
                # Nothing was grouped, so done
                return newset

        grouped = grouping_func(self.annot_paths)

        # Get the bounding rect of each group, which sets the PDF
        # annotation geometry.
        annot_rects = []
        for p in grouped:
            annotype = p[0]
            path = p[1]
            text = p[2]
            rect = path.boundingRect()
            annot = (annotype,
                     rect,
                     text)
            annot_rects.append(annot)
        return (self.name, annot_rects)

    def paint_strokes(self, painter, vector):
        # These pen codes probably refer to different versions through
        # various system software updates. We'll just render them all
        # the same (across all versions).
        pen_lookup = [
            PaintbrushPen,       # Brush
            PencilPen,           # Pencil
            BallpointPen,        # Ballpoint
            MarkerPen,           # Marker
            FinelinerPen,        # Fineliner
            HighlighterPen,      # Highlighter
            EraserPen,           # Eraser
            MechanicalPencilPen1,  # Mechanical Pencil
            EraseAreaPen,        # Erase Area
            None,                # unknown
            None,                # unknown
            None,                # unknown
            PaintbrushPen,       # Brush
            MechanicalPencilPen,  # Mechanical Pencil
            PencilPen,           # Pencil
            BallpointPen,        # Ballpoint
            MarkerPen,           # Marker
            FinelinerPen,        # Fineliner
            HighlighterPen,      # Highlighter
            EraserPen,           # Eraser
            None,                # unknown
            CalligraphyPen       # Calligraphy
        ]

        # Draw the .highlights first (in 2.7 firmware, some higlights
        # are stored in metadata and snap to text).
        for hl in self.highlights:
            opath = QPainterPath()
            qpen = HighlighterPen(pencil_textures=self.pencil_textures,
                                  vector=vector,
                                  layer=self)
            for r in hl['rects']:
                rect = QRectF(r['x'] * self.page.res_mod,
                              r['y'] * self.page.res_mod,
                              r['width'] * self.page.res_mod,
                              r['height'] * self.page.res_mod)
                opath.addRect(rect)

            old_comp = painter.compositionMode()
            painter.setCompositionMode(QPainter.CompositionMode_Overlay)
            old_brush = painter.brush()
            old_pen = painter.pen()
            painter.setBrush(qpen.color())
            painter.setPen(qpen)
            painter.drawPath(opath)
            painter.setBrush(old_brush)
            painter.setPen(old_pen)
            painter.setCompositionMode(old_comp)

            if bool(int(QSettings().value(
                    'pane/notebooks/export_pdf_annotate'))):
                # print(hl['text'])
                self.annot_paths.append(('Highlight', opath, hl['text']))

        # Draw the rest of the .rm strokes.
        for stroke in self.strokes:
            pen, color, unk1, width, unk2, segments = stroke

            qpen = None

            try:
                penclass = pen_lookup[pen]
                assert penclass != None
            except:
                log.error("Unknown pen code %d" % pen)
                penclass = GenericPen

            
            qpen = penclass(pencil_textures=self.pencil_textures,
                            vector=vector,
                            layer=self)
            qpen.setColor(self.colors[color])

            # Do the needful
            qpen.paint_stroke(painter, stroke)
            


    def render_to_painter(self, painter, vector):
        # Transform according to the document metadata
        s_size = self.page.document.model.display.portrait_size
        tsfm = self.page.document.get_tsfm()
        transform = QTransform(tsfm['m11'], tsfm['m12'], tsfm['m13'],
                               tsfm['m21'], tsfm['m22'], tsfm['m23'],
                               s_size[0]*tsfm['m31']*self.page.res_mod,
                               s_size[1]*tsfm['m32']*self.page.res_mod,
                               tsfm['m33'])

        if vector:
            ot = painter.transform()
            painter.setTransform(transform)
            self.paint_strokes(painter, vector=vector)
            painter.setTransform(ot)
            return

        # I was having problems with QImage corruption (garbage data)
        # and memory leaking on large notebooks. I fixed this by giving
        # the QImage a reference array to pre-allocate RAM, then reset
        # the reference count after I'm done with it, so that it gets
        # cleaned up by the python garbage collector.

        res_mod = self.page.res_mod
        image_ref = QByteArray()
        width, height = type(self.page.display).portrait_size
        devpx = width*res_mod * height*res_mod
        bytepp = 4  # ARGB32
        image_ref.fill('\0', devpx * bytepp)
        qimage = QImage(image_ref,
                        width*res_mod,
                        height*res_mod,
                        QImage.Format_ARGB32)

        # This is a fix for a bug that still exists in PySide2
        # https://github.com/matplotlib/matplotlib/issues/4283#issuecomment-95950441
        ctypes.c_long.from_address(id(image_ref)).value = 1

        imgpainter = QPainter(qimage)
        imgpainter.setRenderHint(QPainter.Antialiasing)
        # imgpainter.setRenderHint(QPainter.LosslessImageRendering)

        ot = imgpainter.transform()
        # print('resmod is', res_mod)
        imgpainter.setTransform(transform)

        self.paint_strokes(imgpainter, vector=vector)

        imgpainter.setTransform(ot)
        imgpainter.end()

        painter.drawImage(0, 0, qimage)

        del imgpainter
        del qimage
        del image_ref
        gc.collect()
