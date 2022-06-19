'''
pane.py
This is the Splash Screen pane.

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

from PySide2.QtCore import QSize, Qt, QObject, QEvent, QSettings
from PySide2.QtGui import QPixmap, QImage, QIcon
from PySide2.QtWidgets import QFileDialog
from pathlib import Path
from datetime import datetime
import log
from controllers import UIController

class ResizeEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            if not hasattr(obj, 'splash_pxmap'):
                return False
            pxmap = obj.splash_pxmap
            obj.setPixmap(pxmap.scaled(obj.width(),
                                       obj.height(),
                                       Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
            return True
        else:
            # standard event processing
            return QObject.eventFilter(self, obj, event)


class SplashPane(UIController):
    identity = 'me.davisr.rcu.splash'
    name = 'Wallpaper'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'splash.ui')

    # Todo: implement xochitl version support to handle all filepaths
    default_filedir = '/usr/share/remarkable'
    default_filenames = {
        'suspend': '/suspended.png',
        'poweroff': '/poweroff.png'
        }

    xochitl_versions = [
        '^1\.8\.1\.[0-9]+$',
        '^2\.[0-8]\.[0-9]+\.[0-9]+$',
        '^2\.9\.[0-1]\.[0-9]+$'
    ]

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'preferences-desktop-wallpaper.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon
    
    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        # Button handlers
        self.window.suspend_upload_pushButton.clicked.connect(
            self.suspend_upload)
        self.window.suspend_reset_pushButton.clicked.connect(
            self.suspend_reset)
        self.window.poweroff_upload_pushButton.clicked.connect(
            self.poweroff_upload)
        self.window.poweroff_reset_pushButton.clicked.connect(
            self.poweroff_reset)

        efilt = ResizeEventFilter(self.window)
        self.window.suspend_label.installEventFilter(efilt)
        efilt = ResizeEventFilter(self.window)
        self.window.poweroff_label.installEventFilter(efilt)

        # Load the initial images
        self.update_view()

    def update_view(self):
        self.set_label_pixmap('suspend')
        self.set_label_pixmap('poweroff')

    def suspend_upload(self):
        # Uploads a new suspend image
        self.set_splash('suspend')
    def suspend_reset(self):
        # Resets to the original image
        self.reset_splash('suspend')
    def poweroff_upload(self):
        # Uploads a new poweroff image
        self.set_splash('poweroff')
    def poweroff_reset(self):
        # Resets to the original image
        self.reset_splash('poweroff')

    def set_label_pixmap(self, name):
        # This assumes the target label is named the same as 'name'
        pm = self.read_device_image(name)
        if pm:
            # getattr(self.window, name + '_label').setPixmap(pm)
            getattr(self.window, name + '_label').splash_pxmap = pm
        else:
            getattr(self.window, name + '_label').splash_pxmap = QPixmap()
            # getattr(self.window, name + '_label').setPixmap(QPixmap())
        label = getattr(self.window, name + '_label')
        label.setPixmap(pm.scaled(label.width(),
                                  label.height(),
                                  Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation))

    def set_splash(self, name):
        # Sets a new splash image. 'Name' referrs to the list in
        # default_filepaths. This will open a file dialog to grab the
        # new image.

        # Get the default directory to save under
        default_savepath = QSettings().value(
            'pane/splash/last_import_path')
        if not default_savepath:
            QSettings().setValue(
                'pane/splash/last_import_path',
                Path.home())
            default_savepath = Path.home()
        
        localfile = QFileDialog.getOpenFileName(
            self.window,
            'Upload Image',
            str(default_savepath),
            'Images (*.png)')
        if not localfile[0] or localfile[0] == '':
            return
        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/splash/last_import_path',
            Path(localfile[0]).parent)
        try:
            filepath = type(self).default_filedir \
                + type(self).default_filenames[name]
            backupfilepath = filepath + '.bak'
            # Make a backup (if necessary)
            if self.backup_remote_file(filepath):
                # todo: check to see if the png file needs to match the
                # required resolution and color profile
                self.model.put_file(localfile[0], filepath)
                self.set_label_pixmap(name)
                self.model.restart_xochitl()
                log.info('set new splash for ' + name)
        except Exception as e:
            log.error('unable to set splash; ' + e.__str__())
            return False
    def reset_splash(self, name):
        # Resets the splash image to factory-default (if it was backed
        # up with RCU).
        log.info('resetting splash for ' + name)
        filepath = type(self).default_filedir \
            + type(self).default_filenames[name]
        backupfilepath = filepath + '.bak'
        self.make_free_space()
        out, err = self.model.run_cmd(
            'cp "{}" "{}"'.format(backupfilepath, filepath))
        self.set_label_pixmap(name)
        self.model.restart_xochitl()

    def check_remote_file_exists(self, fullpath):
        # Checks if there is a file on the remote system
        out, err = self.model.run_cmd(
            'test -f "' + fullpath + '"; echo $?')
        if '0' == out[0]:
            return True
        return False

    def make_free_space(self):
        out, err = self.model.run_cmd(
            'journalctl --vacuum-size=10M')

    def backup_remote_file(self, fullpath):
        # Makes a duplicate of the remote file with a .bak extension
        bakfile = fullpath + '.bak'

        self.make_free_space()

        # Create a .bak if it doesn't exist
        create_bak_cmd = 'yes n | cp -i "{}" "{}"'.format(
            fullpath, bakfile)
        self.model.run_cmd(create_bak_cmd)
        
        # Final check
        if self.check_remote_file_exists(fullpath):
            return True
        return False

    def read_device_image(self, name):
        # Reads the image from the device and returns a QPixMap. Returns
        # nothing if the image can't be read.
        fpath = type(self).default_filedir \
            + type(self).default_filenames[name]
        out, err = self.model.run_cmd('cat "{}"'.format(fpath),
                                      raw=True)
        if len(err):
            log.error('problem reading png from device; ' + name)
            log.error(err.decode('utf-8'))
            return
        pixmap = QPixmap()
        pixmap.loadFromData(out)
        return pixmap
