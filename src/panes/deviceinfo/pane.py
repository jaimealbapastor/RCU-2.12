'''
pane.py
This is the Device Info pane.

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

from pathlib import Path
import math
import controllers
import log
from worker import Worker
from . import backup
from PySide2.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from PySide2.QtGui import QIcon, QPixmap
from PySide2.QtCore import QSize, QSettings, QCoreApplication
import time
import platform
from .BatteryInfoController import BatteryInfoController

def prettynum(num):
    return ('%.1f'%(num)).__str__().replace('.0', '')

def hide_all_in_layout(layout):
    for i in range(0, layout.count()):
        item = layout.itemAt(i)
        item.hide()
def show_all_in_layout(layout):
    for i in range(0, layout.count()):
        item = layout.itemAt(i)
        item.show()

class DeviceInfoPane(controllers.UIController):
    identity = 'me.davisr.rcu.deviceinfo'
    name = 'Device Info'
    
    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'deviceinfo.ui')

    is_essential = True

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'utilities-system-monitor.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon

    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)
        self.pane_controller = pane_controller

        self.device_name = None

        self.recoveryos_controller = controllers.RecoveryOSController(
            self.model)

        self.backup_dir = QCoreApplication.sharePath / Path('backups')
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        log.info('backups are stored in {}'.format(self.backup_dir))
        self.backup_controller = backup.BackupController(self)

        self.battinfo_controller = BatteryInfoController(self)

        if not QCoreApplication.args.cli:
            self.update_view(loadinfo=False)
            # Load product image
            imagepath = type(self).adir / type(self).bdir
            pxm = QPixmap()
            if 'RM100' == self.model.device_info['model'] \
               or 'RM102' == self.model.device_info['model']:
                filename = imagepath / 'rm1.png'
            else:
                # Don't explicitly mention the RM2 (or <insert future model
                # here> because if the model is not recognized, it is very
                # likely _not_ to have been released in the past.
                filename = imagepath / 'rm2.png'
            pxm.load(str(filename))
            self.window.prodimage_label.setPixmap(pxm)
            # Button registration
            self.window.backup_pushButton.clicked.connect(
                self.make_backup)
            self.window.abort_pushButton.clicked.connect(
                self.abort_backup)
            self.window.rename_pushButton.clicked.connect(
                self.rename_device)
            self.window.battinfo_pushButton.clicked.connect(
                self.battinfo_controller.start_window)

            # Load backup types
            for btype in backup.backup_types:
                # Quick hack for Parabola to only allow Full-level backup
                if 'Full' in btype:
                    self.window.backuptype_comboBox.addItem(
                        btype,
                        userData=backup.backup_types[btype])
                elif self.model.device_info and 'osver' in self.model.device_info and self.model.device_info['osver'] and 'Parabola' in self.model.device_info['osver']:
                    pass
                else:
                    self.window.backuptype_comboBox.addItem(
                        btype,
                        userData=backup.backup_types[btype])

            # visual stuff
            self.set_buttons_relaxed()
            
            # Register to get a callback (like if storage space changes)
            self.model.register_device_info_pane(self)
            
    def update_view(self, loadinfo=True):
        if loadinfo:
            self.model.load_device_info()
        self.load_device_name()
        self.load_strings()
        
    def set_buttons_relaxed(self):
        self.window.backup_progressBar.hide()
        self.window.backup_progressBar.setValue(0)
        self.window.abort_pushButton.setEnabled(False)
        self.window.abort_pushButton.hide()
        self.window.abort_pushButton.setText('Abort')
        self.window.backup_pushButton.setEnabled(True)
        self.window.backup_pushButton.show()
        self.window.backup_treeWidget.setEnabled(True)
        self.window.rename_pushButton.setEnabled(True)
        self.window.battinfo_pushButton.setEnabled(True)
        self.window.backuptype_comboBox.show()
        self.window.rm2_backup_notice_label.hide()

        if self.model.is_in_recovery:
            self.window.rename_pushButton.setEnabled(False)
            # self.window.battinfo_pushButton.setEnabled(False)

        # Disable all backup/restore options for unsupported
        # reMarkable models (RM2).
        if 'RM100' != self.model.device_info['model'] \
           and 'RM102' != self.model.device_info['model']:
            log.info('disabling backup interface for unsupported model')
            self.window.backup_pushButton.setEnabled(False)
            self.window.backup_treeWidget.setEnabled(False)
            self.window.backuptype_comboBox.setEnabled(False)
            self.window.rm2_backup_notice_label.show()
        
        

        
        
    def set_buttons_backup(self):
        self.window.backup_progressBar.setEnabled(True)
        self.window.backup_progressBar.show()
        self.window.backup_pushButton.setEnabled(False)
        self.window.backup_pushButton.hide()
        self.window.abort_pushButton.setEnabled(True)
        self.window.abort_pushButton.show()
        self.window.backup_treeWidget.setEnabled(False)
        self.window.rename_pushButton.setEnabled(False)
        self.window.battinfo_pushButton.setEnabled(False)
        self.window.backuptype_comboBox.hide()

    def check_if_usb_cx(self):
        # Warn the user if they are not on a USB connection and trying
        # to take or restore a backup.
        host = self.model.config.host.split(':')[0]
        if '10.11.99.1' == host:
            return True
        mb = QMessageBox()
        mb.setWindowTitle('Warning')
        mb.setText('It appears this tablet is not connected over USB. Taking and restoring backups must happen over a USB connection. Continue anyway?')
        mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
        mb.setDefaultButton(QMessageBox.No)
        ret = mb.exec()
        if int(QMessageBox.Yes) != ret:
            return False
        return True
        
    def make_backup(self):
        # Depending on the option selected, this will make a backup.
        log.info('make_backup')
        if not self.check_if_usb_cx():
            return
        self.pane_controller.disable_nonessential_panes()
        self.set_buttons_backup()
        self.pane_controller.cx_timer.stop()
        self.do_backup()

    def show_failed_operation_device_in_recovery(self):
        mb = QMessageBox()
        mb.setWindowTitle('Failed Backup/Recovery Operation')
        mb.setText('The tablet may be stuck in recovery mode. If this is the case, please hold the Power button for 10 seconds, release it, then turn it on again normally.')
        mb.setStandardButtons(QMessageBox.Ok)
        mb.exec()

    def make_backup_finished(self):
        def left(is_out):
            if not is_out:
                log.error('could not leave recovery mode after backup')
                self.show_failed_operation_device_in_recovery()
            else:
                self.backup_controller.find_and_load_backups()
            self.set_buttons_relaxed()
            self.pane_controller.enable_all_panes()
            self.pane_controller.cx_timer.start()
        self.recoveryos_controller.leave_recovery_mode(left)
        
    def do_backup(self):
        bfiles = self.window.backuptype_comboBox\
                            .currentData()
        def entered(is_in_recovery):
            if is_in_recovery:
                worker = Worker(
                    fn=lambda progress_callback, bfiles=bfiles:
                    self.backup_controller.make_backup(
                        progress_callback, bfiles))
                self.threadpool.start(worker)
                worker.signals.progress.connect(
                    lambda x: self.window.backup_progressBar.setValue(
                        int(round(x))))
                worker.signals.finished.connect(
                    self.make_backup_finished)
            else:
                log.error('cannot do_backup because recoveryos is not loaded')
                self.make_backup_finished()
        self.recoveryos_controller.enter_recovery_mode(entered, load_info=False)

    def make_restore(self, trig):
        log.info('make_restore')
        if not self.check_if_usb_cx():
            return
        # Called by a button to restore a backup to the device
        self.set_buttons_backup()
        self.window.abort_pushButton.setEnabled(False)
        self.pane_controller.disable_nonessential_panes()
        self.pane_controller.cx_timer.stop()
        self.do_restore(trig)

    def do_restore(self, trig):
        def entered(is_in_recovery):
            if is_in_recovery:
                log.info('starting restore worker')
                worker = Worker(
                    fn=lambda progress_callback:
                    trig(progress_callback))
                self.threadpool.start(worker)
                worker.signals.progress.connect(
                    lambda x: self.window.backup_progressBar.setValue(
                        int(round(x))))
                # On finish, reload all the windows
                worker.signals.finished.connect(self.finish_restore)
            else:
                log.error('cannot do_restore because recoveryos is not loaded')
                self.finish_restore()
        self.recoveryos_controller.enter_recovery_mode(entered, load_info=False)
            

    def finish_restore(self):
        def left(has_left):
            if not has_left:
                log.error('could not leave recovery mode after restore')
                self.show_failed_operation_device_in_recovery()
            else:
                self.pane_controller.reload_pane_compatibility()
                self.pane_controller.update_all_pane_data()
                self.pane_controller.enable_all_panes()
                self.pane_controller.cx_timer.start()
            self.set_buttons_relaxed()
            self.window.abort_pushButton.setEnabled(False)
        self.recoveryos_controller.leave_recovery_mode(left)
                    
        

    def abort_backup(self):
        # Abort a currently-running backup
        log.info('aborting backup!')
        self.backup_controller.set_abort()
        self.window.abort_pushButton.setText('Aborting')
        self.window.abort_pushButton.setEnabled(False)
        self.window.backup_progressBar.setEnabled(False)

    def load_strings(self):
        # Loads the device info strings into labels
        nastring = '—'

        model = self.model.device_info['model'] or nastring
        self.window.model_label.setText(model)

        serial = self.model.device_info['serial'] or nastring
        self.window.serial_label.setText(serial)

        osver = self.model.device_info['osver'] or nastring
        self.window.osver_label.setText(osver)

        cpu = self.model.device_info['cpu'] or nastring
        self.window.cpu_label.setText(cpu)

        ram = (prettynum(self.model.device_info['ram']) \
               + ' MB') if self.model.device_info['ram'] else nastring
        self.window.ram_label.setText(ram)

        storavail = (prettynum(self.model.device_info['storage_max'] \
                               - self.model.device_info['storage_used']) + ' GB available') if self.model.device_info['storage_max'] else nastring
        self.window.storage_label.setText(storavail)

    def load_device_name(self):
        # Gets the name from the device
        name = self.model.device_info['rcuname']
        self.device_name = name
        if name != '' and name != type(self.model).default_name:
            # posession
            if name[-1] == 's':
                name += "'"
            else:
                name += "'s"

        # load in window
        if not self.device_name or name == type(self.model).default_name:
            name = 'Connected'
        w = self.window.deviceinfo_groupBox
        w.setTitle(name + ' reMarkable')
        
    def rename_device(self):
        # Adds a file to the device containing the owner's name
        # grab the name
        # ...
        # Cut to
        loadname = '' if self.device_name == type(self.model).default_name else self.device_name
        text, ok = QInputDialog().getText(
            self.window, 'Rename Device', 'New Name:', QLineEdit.Normal,
            loadname)
        if ok:
            self.model.set_device_name(text)
            self.load_device_name()
