'''
Backup.py
This is the abstract Backup type. A backup is stored on disk in the
$HOME/.rcu/backups directory, and has a backup.json and files/.

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

# All these may not be necessary. Todo: cull later
import uuid
import datetime
import json
from pathlib import Path
import log
import time
import platform
import base64

from .BackupFile import BackupFile

def rmdir(path):
    for child in path.glob('*'):
        if child.is_file():
            child.unlink()
        else:
            rmdir(child)
    path.rmdir()

class Backup:
    # This is a backup unit. They have some elementary meta that is
    # ripped from the filesystem, and are determined to be a specific
    # backup type (Full, OS, or Data).
    def __init__(self, controller, backup_dict=None):
        self.controller = controller
        self.model = controller.model
        self.parent_dir = controller.backup_dir
        self.bid = None # uuid.uuid4()
        self.device_info = None
        self.timestamp = None
        self.files = [] # stores BackupFile[]
        self.complete = False

        if backup_dict:
            self.bid = backup_dict['bid']
            self.device_info = backup_dict['device_info']
            self.timestamp = datetime.datetime.fromtimestamp(
                float(backup_dict['timestamp']))
            self.complete = backup_dict['complete']
            for f in backup_dict['files']:
                bf = BackupFile(self,
                                name=f['name'],
                                btype=f['btype'],
                                mountpoint=f['mountpoint'],
                                size=f['size'],
                                checksum=f['checksum'])
                self.files.append(bf)

        # these aren't used by json; they're used to calculate
        # percentage transferred
        self.bytes_transferred = 0
        self.total_bytes = 0

    def get_restore_types(self):
        has_mmcblk1boot0 = False
        has_mmcblk1boot1 = False
        has_mmcblk1 = False
        has_mmcblk1p1 = False
        has_mmcblk1p2 = False
        has_mmcblk1p3 = False
        has_mmcblk1p4 = False
        has_mmcblk1p5 = False
        has_mmcblk1p6 = False
        has_mmcblk1p7 = False
        for f in self.files:
            if 'mmcblk1boot0' == f.name:
                has_mmcblk1boot0 = True
            if 'mmcblk1boot1' == f.name:
                has_mmcblk1boot1 = True
            if 'mmcblk1' == f.name:
                has_mmcblk1 = True
            if 'mmcblk1p1' == f.name:
                has_mmcblk1p1 = True
            if 'mmcblk1p2' == f.name:
                has_mmcblk1p2 = True
            if 'mmcblk1p3' == f.name:
                has_mmcblk1p3 = True
            if 'mmcblk1p4' == f.name:
                has_mmcblk1p4 = True
            if 'mmcblk1p5' == f.name:
                has_mmcblk1p5 = True
            if 'mmcblk1p6' == f.name:
                has_mmcblk1p6 = True
            if 'mmcblk1p7' == f.name:
                has_mmcblk1p7 = True
        # determine
        types = []
        if (has_mmcblk1boot0 and has_mmcblk1):
            types.append(('Full', self._restore_full))
        if (has_mmcblk1boot0):
            types.append(('Bootloader', self._restore_bootloader))
        if (has_mmcblk1) \
           or (has_mmcblk1p1 and has_mmcblk1p2 and has_mmcblk1p3):
            # Quick hack to disallow OS-level restores to Parabola
            if self.device_info and 'osver' in self.device_info and 'Parabola' not in self.device_info['osver']:
                if self.model.device_info and 'osver' in self.model.device_info and self.model.device_info['osver'] and 'Parabola' not in self.model.device_info['osver']:
                    types.append(('OS', self._restore_os))
        if (has_mmcblk1 or has_mmcblk1p7):
            # Quick hack to disallow Data-level restores to Parabola
            if self.device_info and 'osver' in self.device_info and 'Parabola' not in self.device_info['osver']:
                if self.model.device_info and 'osver' in self.model.device_info and self.model.device_info['osver'] and 'Parabola' not in self.model.device_info['osver']:
                    types.append(('Data', self._restore_data))

        
        return types

    def _restore_full(self, progress_callback):
        log.info('full restore')

        has_dict = {
            'mmcblk1': False,
            'mmcblk1boot0': False
        }

        for f in self.files:
            for name in has_dict:
                if f.name == name:
                    has_dict[name] = True
                    break

        if has_dict['mmcblk1'] and has_dict['mmcblk1boot0']:
            return self._restore_full_from_mmcblk1(progress_callback)
        log.error('cannot restore due to missing partitions')
        return False

    def _restore_bootloader(self, progress_callback):
        has_mmcblk1boot0 = False
        for f in self.files:
            if 'mmcblk1boot0' == f.name:
                has_mmcblk1boot0 = True
                break
        if not has_mmcblk1boot0:
            log.error('cannot restore bootloader--missing file')
            return False
        files = [self._get_offset_from_mountpoint('/dev/mmcblk1boot0')]
        return self._restore_files(files, progress_callback)
        
    def _restore_os(self, progress_callback):
        log.info('os restore')

        has_dict = {
            'mmcblk1': False,
            'mmcblk1p1': False,
            'mmcblk1p2': False,
            'mmcblk1p3': False
        }

        for f in self.files:
            for name in has_dict:
                # Note: files are assumed to be clean if they can be
                # loaded here, because the backup.json file can't be
                # written if it was a dirty backup.
                if f.name == name:
                    has_dict[name] = True
                    break

        if has_dict['mmcblk1']:
            return self._restore_os_from_mmcblk1(progress_callback)
        elif (has_dict['mmcblk1p1'] and has_dict['mmcblk1p2'] \
                   and has_dict['mmcblk1p3']):
            return self._restore_os_from_mmcblk1ps(progress_callback)
        log.error('cannot restore due to missing partitions')
        return False

    def _get_offset_from_partition_table(self, mountpoint):
        # Look at the partition table to find partition boundaries and
        # return a tuple of (mountpoint, startbyte, length) based on
        # /dev/mmcblk1.

        # TODO: redefine the way values are grepped out of the parition
        # table, or better-yet, redefine how the partition table is
        # stored in the backup. The full text is useful for humans to
        # read, but I'm worried it may change if busybox ever updates
        # the format.

        # Maybe I'll edit this later when I get around to SD card
        # detection.
        maindisk = '/dev/mmcblk1'
        ptable = base64.b64decode(
            self.model.device_info['partition_table']).decode('utf-8')
        ptbytes = 0
        ptsectors = 0
        for line in ptable.split('\n'):
            if line.startswith('Disk {}'.format(maindisk)):
                sl = line.split(' ')
                ptsectors = int(sl[-2])
                ptbytes = int(sl[-4])
                break
        # This forms the basis of offset calculations
        ptbytespersector = int(ptbytes / ptsectors)
        # Find the mountpoint
        pstartbyte = 0
        plength = 0
        for line in ptable.split('\n'):
            if line.startswith(mountpoint):
                # Replace the * which occupies boot flag column
                sl = line.replace('*', '').split()
                pstartbyte = int(sl[-6]) * ptbytespersector
                plength = int(sl[-4]) * ptbytespersector
                break
        # Find the file for the main disk to return with offsets
        for f in self.files:
            if f.mountpoint == maindisk:
                return (f, mountpoint, pstartbyte, plength)

    def _get_offset_from_mountpoint(self, mountpoint):
        for f in self.files:
            if f.mountpoint == mountpoint:
                return (f, f.mountpoint, 0, f.size)

    def _restore_full_from_mmcblk1(self, progress_callback):
        restores = [
            self._get_offset_from_mountpoint('/dev/mmcblk1'),
            self._get_offset_from_mountpoint('/dev/mmcblk1boot0')
        ]
        return self._restore_files(restores, progress_callback)
    
    def _restore_os_from_mmcblk1(self, progress_callback):
        restores = [
            self._get_offset_from_partition_table('/dev/mmcblk1p1'),
            self._get_offset_from_partition_table('/dev/mmcblk1p2'),
            self._get_offset_from_partition_table('/dev/mmcblk1p3')
        ]
        return self._restore_files(restores, progress_callback)

    def _restore_os_from_mmcblk1ps(self, progress_callback):
        restores = [
            self._get_offset_from_mountpoint('/dev/mmcblk1p1'),
            self._get_offset_from_mountpoint('/dev/mmcblk1p2'),
            self._get_offset_from_mountpoint('/dev/mmcblk1p3')
        ]
        return self._restore_files(restores, progress_callback)

    def _restore_data_from_mmcblk1(self, progress_callback):
        restores = [
            self._get_offset_from_partition_table('/dev/mmcblk1p7')
        ]
        return self._restore_files(restores, progress_callback)

    def _restore_data_from_mmcblk1ps(self, progress_callback):
        restores = [
            self._get_offset_from_mountpoint('/dev/mmcblk1p7')
        ]
        return self._restore_files(restores, progress_callback)

    def _restore_files(self, restore_files, progress_callback):
        # It is assumed these files exist if this fuction is being
        # called. The restore_files should be a list of tuples
        # output from one of the _get_offset_XXX() functions.

        log.info('@@@ restoring files')
        log.info(restore_files)

        # Verify checksums
        all_good_checksums = True
        for tup in restore_files:
            f = tup[0]
            if not f.verify_checksum_against_disk_copy():
                all_good_checksums = False
        if not all_good_checksums:
            log.error('all the checksums could not be verified')
            log.error('aborting')
            return

        log.info('all disk checksums are good')

        # Calculate size for progress
        total_bytes = 0
        for tup in restore_files:
            blength = tup[3]
            total_bytes += blength

        # Do restore
        bytes_done = 0
        for tup in restore_files:
            f = tup[0]
            mountpoint = tup[1]
            bstart = tup[2]
            blength = tup[3]
            
            ret = f.restore_to_device(
                mountpoint, bstart, blength,
                lambda x:
                progress_callback.emit(
                    (bytes_done + (blength * x)) / total_bytes * 100))
            if not ret:
                log.error('restoring {} failed. retrying...'.format(f.name))
                # This could have failed if the user bumped the
                # cable during the restore. The OS should still
                # be up. If it isn't, then try to reconnect.
                # Otherwise, there are bigger problems. Wait a
                # little, then try reconnect once.
                if not self.model.is_connected():
                    log.info('waiting 30 seconds before attempting to reconnect')
                    time.sleep(30)
                    if not self.model.reconnect_restore(load_info=False):
                        # problem
                        log.error('could not re-establish connection to recovery os. nothing else can be done. the device is in a broken state.')
                        # break out of the loop. nothing more can be
                        # done.
                        break

                ret = f.restore_to_device(
                    mountpoint, bstart, blength,
                    lambda x:
                    progress_callback.emit(
                        (bytes_done + (blength * x)) / total_bytes * 100))
            if not ret:
                log.error('failed to restore a critical file. aborting restore. device is in a broken state.')
                break
            
            bytes_done += blength
        
    
    def _restore_data(self, progress_callback):
        log.info('data restore')

        has_dict = {
            'mmcblk1': False,
            'mmcblk1p7': False
        }

        for f in self.files:
            for name in has_dict:
                # Note: files are assumed to be clean if they can be
                # loaded here, because the backup.json file can't be
                # written if it was a dirty backup.
                if f.name == name:
                    has_dict[name] = True
                    break

        if has_dict['mmcblk1']:
            return self._restore_data_from_mmcblk1(progress_callback)
        elif has_dict['mmcblk1p7']:
            return self._restore_data_from_mmcblk1ps(progress_callback)
        log.error('cannot restore due to missing partitions')
        return False

    def get_size(self):
        # Returns the total size in bytes
        tot = 0
        for f in self.files:
            tot += f.size
        return tot

    def get_dir(self):
        return Path(self.parent_dir / self.bid)
        
    def as_new(self, bfiles):
        # Returns self configured as a new backup
        self.bid = uuid.uuid4().__str__()
        self.timestamp = datetime.datetime.utcnow()

        self.device_info = {
            'osver': self.model.device_info['osver'],
            'serial': self.model.device_info['serial'],
            'model': self.model.device_info['model'],
            'kernel_bootargs': self.model.device_info[
                'kernel_bootargs'],
            'partition_table': self.model.device_info[
                'partition_table']
        }

        # Populate files from array+strings
        bdir = self.get_dir()
        self.files_dir = Path(bdir / 'files')
        self.files_dir.mkdir(parents=True)
        self.json_file = Path(bdir / 'backup.json')

        for bf in bfiles:
            self.files.append(BackupFile(
                self,
                name=bf[0],
                btype=bf[1],
                mountpoint=bf[2]))
        
        return self

    def save_json(self):
        obj = {
            'bid': self.bid,
            'timestamp': self.timestamp.timestamp(),
            'complete': self.complete,
            'device_info': self.device_info,
            'files': []
            }
        allfiles_complete = True
        for file in self.files:
            if not file.dirty:
                obj['files'].append(file.as_dict())
            else:
                allfiles_complete = False
        if allfiles_complete:
            self.complete = True
            obj['complete'] = self.complete
        jsobj = json.dumps(obj)
        with open(self.json_file, 'w') as file:
            file.write(jsobj)

    def do_backup(self, abort, progress_callback):
        # This must be a new backup (as_new) and have a model.
        # self.files must contain a list of files TO BACK UP.
        # This is the function ultimately responsible for the
        # progress_callback, which will update the progress bar.

        # How many bytes?
        for file in self.files:
            self.total_bytes += file.size
        
        def add_bytes(n):
            self.bytes_transferred += n
            pct = self.bytes_transferred / self.total_bytes * 100
            progress_callback.emit(pct)
        
        for file in self.files:
            destname = Path(
                self.parent_dir / self.bid \
                / 'files' / file.get_filename())
            status = file.dump_data_from_device(
                destname, abort, add_bytes)
            if not status:
                log.error('backup failed for {}'.format(destname))
                # Should we just mark this as a dirty backup and
                # continue?
                continue
            # The file was dumnped successfully, so save the json
            self.save_json()
        # save_json will set self.complete
        if self.complete:
            return True
        
    def load_from_file(self, backupjson):
        # Will load the specified directory as a backup
        True

    def delete_data(self):
        # Delete the backup
        rmdir(self.get_dir())
