'''
BackupFile.py
A BackupFile is a data unit contained inside a Backup. Typically, files
are mirrors of block devices/partitions that can be restored over the
originals.

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

import hashlib
from pathlib import Path
import log

class BackupFile:
    # This is a single file contined inside of a backup.
    def __init__(self, backup, name='', btype='', mountpoint='',
                 size=False, checksum=False):
        self.backup = backup
        self.model = self.backup.model
        self.name = name
        # Acceptable btypes: 'bin', (NOT 'tar'--not implemented yet)
        self.btype = btype
        self.mountpoint = mountpoint
        self.size = size
        self.checksum = checksum
        self.dirty = True

        # Upon init, get the size so the progress bar will now how
        # far to advance.
        if 'bin' == self.btype:
            if not self.size:
                cmd = "/sbin/fdisk -l " + self.mountpoint + " \
                | head -n 1 \
                | awk -F'bytes' '{print $1}' \
                | awk '{print $NF}'"
                out, err = self.model.run_cmd(cmd)
                if 0 != len(err):
                    log.error('error getting length of backup!')
                    log.error(err)
                    return False
                self.size = int(out)
            if not self.checksum:
                log.info('getting checksum of {}'.format(self.mountpoint))
                cmd = 'md5sum {} | cut -d" " -f1'.format(
                    self.mountpoint)
                out, err = self.model.run_cmd(cmd, timeout=300)
                self.checksum = out.strip('\n')

    def as_dict(self):
        # Returns a dictionary of self; useful for json
        return {
            'name': self.name,
            'btype': self.btype,
            'mountpoint': self.mountpoint,
            'size': self.size,
            'checksum': self.checksum
            }

    def get_filename(self):
        return '{}.{}'.format(self.name, self.btype)

    def get_disk_filepath(self):
        return Path(self.backup.get_dir() / 'files' / self.get_filename())

    def verify_checksum_against_disk_copy(self):
        md5 = hashlib.md5()
        with open(self.get_disk_filepath(), 'rb') as f:
            # checksum
            for chunk in iter(lambda: f.read(4096), b''):
                md5.update(chunk)
            f.close()
        oldchecksum = md5.hexdigest()

        if oldchecksum != self.checksum:
            log.error('Checksums do not match! Aborting!')
            return False

        return True

    def restore_to_device(self, mountpoint, bstart, blength, prog_cb):
        # This requires the tablet to already be in the restore mode.
        # This assumes the checksums have already been verified through
        # verify_checksum_against_disk_copy().

        # prog_cb should be called with the percentage complete, on a
        # scale of 0-1.

        log.info('restoring {} -> {}, start={}, length={}'.format(
            self.name, mountpoint, bstart, blength))
        
        # Upload to the device
        filepath = self.get_disk_filepath()

        # If this is a bootloader, we have to unlock it first.
        if '/dev/mmcblk1boot0' == mountpoint:
            cmd = 'echo 0 > /sys/block/mmcblk1boot0/force_ro'
            out, err = self.model.run_cmd(cmd)
            if (err):
                log.error('problem unlocking bootloader to rw')
                log.error(err)
                return False

        cmd = 'cat > "{}"'.format(mountpoint)
        out, err, stdin = self.model.run_cmd(cmd, raw_noread=True,
                                             with_stdin=True)
        bytes_left = blength
        chunksize = 4096
        ondisk_md5 = hashlib.md5()
        with open(filepath, 'rb') as f:
            f.seek(bstart)
            if bytes_left < chunksize:
                chunksize = bytes_left
            while bytes_left > 0:
                chunk = f.read(chunksize)
                stdin.write(chunk)
                ondisk_md5.update(chunk)
                bytes_left -= chunksize
                prog_cb((blength - bytes_left) / blength)
            f.close()
            stdin.close()
        ondisk_checksum = ondisk_md5.hexdigest()

        err = err.read().decode('utf-8')
        if (err):
            log.error('error during restore')
            log.error(err)
            return False

        # If this is a bootloader, we have to lock it back up.
        if '/dev/mmcblk1boot0' == mountpoint:
            cmd = 'echo 1 > /sys/block/mmcblk1boot0/force_ro'
            out, err = self.model.run_cmd(cmd)
            if (err):
                log.error('problem locking bootloader to ro')
                log.error(err)
                # don't return--might not be a problem after reboot

        # Verify the new data against the old checksum. Since we may
        # have done a partial restore from mmcblk1, we need to compute
        # the checksum now. The entire file should have passed a check
        # against its stored checksum in the beginning, so we could
        # trust it.
        cmd = 'md5sum {} | cut -d" " -f1'.format(mountpoint)
        out, err = self.model.run_cmd(cmd, timeout=300)
        newchecksum = out.strip('\n')

        if newchecksum != ondisk_checksum:
            log.error('checksums do not match!')
            return False

        return True
                              
    def dump_data_from_device(self, destname, abort, bytes_cb):
        # Will dump the data from the device depending on self.btype,
        # to the backup's directory path.
        if Path(destname).is_file():
            log.error('refusing to overwrite backup data from device')
            return
        if 'bin' == self.btype:
            return self.backup_bin(
                self.mountpoint, destname, abort, bytes_cb)
        if 'tar' == self.btype:
            log.error('tar types are not yet implemented')
            
    # This was the original, but is outperformed by the dumper
    def backup_bin(self, device, destname, abort, bytes_cb):
        if abort(): return False
        size = self.size
        log.info('size is {}, starting backup'.format(size))
        with open(destname, 'ab+') as outfile:
            cmd = 'dd if={} bs=4M'.format(device)
            chunksize = 4096
            out, err = self.model.run_cmd(cmd, raw_noread=True)
            for chunk in iter(lambda: out.read(chunksize), b''):
                if abort(): return False
                outfile.write(chunk)
                bytes_cb(len(chunk))
        outfile.close()
        # Verify the outfile
        md5 = hashlib.md5()
        with open(destname, 'rb') as outfile:
            for chunk in iter(lambda: outfile.read(4096), b''):
                md5.update(chunk)
        outfile.close()
        checksum = md5.hexdigest()
        if self.checksum != checksum:
            log.error('backup file does not match!')
            log.error('wanted {}'.format(checksum))
            log.error('got {}'.format(out))
            # Should we do anything about this?
            return False
        log.info('backup file matches--finished')
        self.dirty = False
        return True
