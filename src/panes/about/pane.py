'''
pane.py
This is the About pane.

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
from pathlib import Path
from controllers import UIController
import sys

from worker import Worker

from PySide2.QtCore import QByteArray, QUrl, QSize, QCoreApplication
from PySide2.QtGui import QIcon
from PySide2.QtWidgets import QMessageBox
import urllib.request
import hashlib

import certifi # PyInstaller pickup (should be auto-used by urllib)

class AboutPane(UIController):
    identity = 'me.davisr.rcu.about'
    name = 'About RCU'
    
    uiname = 'about.ui'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / uiname)

    is_essential = True

    update_url = 'https://files.davisr.me/projects/rcu/latest-version.txt'
    compat_url = 'https://files.davisr.me/projects/rcu/latest-compat.txt'

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'help-about.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon
    
    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.pane_controller = pane_controller

        self.version = QCoreApplication.applicationVersion().strip()
        self.version_sc = QCoreApplication.version_sortcode
        
        self.remote_version_body = None
        self.remote_compat_body = None

        # Set button icon
        ipathstr = str(Path(type(self).bdir / 'icons' / 'rcu-icon.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(48, 48), QIcon.Normal, QIcon.On)
        self.window.icon_label.setPixmap(icon.pixmap(64, 64))

        # Replace version
        ttext = self.window.label.text()
        self.window.label.setText(ttext.replace(
            '{{version}}', self.version))

        # Replace Python license
        vi = sys.version_info
        pylicense = 'COPYING_PYTHON_{}_{}_{}'.format(vi.major,
                                                     vi.minor,
                                                     vi.micro)
        licensedir = Path(type(self).adir.parent / 'licenses')
        licensepath = licensedir / pylicense
        ltextb = self.window.python_textBrowser
        if not licensepath.exists():
            log.error('Python license file not found: {}'.format(pylicense))
            ltextb.setPlainText('Python license file not found.')
        else:
            with open(licensepath, 'r', encoding='utf8') as f:
                ltextb.setPlainText(f.read())
                f.close()

        # Button registration
        self.window.checkupdates_pushButton.clicked.connect(
            self.check_for_updates_async)
        self.window.checkcompat_pushButton.clicked.connect(
            self.check_for_compat_async)

    def check_for_updates_async(self, callback):
        # Runs the update check in a new thread, not to block the GUI.
        worker = Worker(fn=self.check_for_updates)
        self.threadpool.start(worker)
        worker.signals.finished.connect(self.finished_check_for_updates)

    def check_for_compat_async(self, callback):
        # Runs the compat check in a new thread, not to block the GUI.
        worker = Worker(fn=self.check_for_compat)
        self.threadpool.start(worker)
        worker.signals.finished.connect(self.finished_check_for_compat)

    def check_for_updates(self, progress_callback=lambda x: ()):
        log.info('checking for updates')
        self.window.checkupdates_pushButton.setEnabled(False)
        with urllib.request.urlopen(type(self).update_url) as response:
            self.remote_version_body = response.read(100)

    def check_for_compat(self, progress_callback=lambda x: ()):
        log.info('checking for compat')
        self.window.checkcompat_pushButton.setEnabled(False)
        with urllib.request.urlopen(type(self).compat_url) as response:
            self.remote_compat_body = response.read(10000)

    def finished_check_for_updates(self):
        # Picks up when async worker is done
        reply = self.remote_version_body
        self.window.checkupdates_pushButton.setEnabled(True)

        if reply is None:
            # Problem contacting update server, probably no net.
            log.error('problem contacting update server')
            mb = QMessageBox()
            mb.setWindowTitle('Version Check')
            mb.setText('Unable to contact the update server. Please try again later, and sorry for the inconvenience.')
            mb.exec()
            return
        
        replystrings = str(reply, 'utf-8').strip().split('\n')
        # Get the version with the matching flag
        foundver = None
        for s in replystrings:
            split = s.split('\t')
            sortcode = split[0]
            prettyver = split[1]
            release_flag = prettyver[0]
            if release_flag == self.version[0]:
                foundver = (sortcode, prettyver)
                break
        if not foundver:
            # Unknown what the latest version is!
            # ...
            log.error('error checking version: cannot find version flag in list')
            return
        # assume foundver
        message = 'You have the latest version of RCU.'
        if self.version_sc < foundver[0]:
            message = 'A new version of RCU is available: {}.'.format(
                foundver[1])
        mb = QMessageBox()
        mb.setWindowTitle('Version Check')
        mb.setText(message)
        mb.exec()

    def finished_check_for_compat(self):
        reply = self.remote_compat_body
        self.window.checkcompat_pushButton.setEnabled(True)

        if reply is None:
            # Problem contacting update server, probably no net.
            log.error('problem contacting update server')
            mb = QMessageBox()
            mb.setWindowTitle('Compatibility Check')
            mb.setText('Unable to contact the update server. Please try again later, and sorry for the inconvenience.')
            mb.exec()
            return
        
        # Get the local compat file checksum to compare to server's
        # response.
        local_compat = QCoreApplication.sharePath / 'compat.txt'
        local_compat_hash = None
        if local_compat.exists():
            with open(local_compat, 'rb') as f:
                local_compat_hash = hashlib.md5(f.read()).hexdigest()
                f.close()
        remote_compat_body = reply
        remote_compat_hash = \
            hashlib.md5(remote_compat_body).hexdigest()
        if local_compat_hash != remote_compat_hash:
            self.new_compat_avail = True
            with open(local_compat, 'wb') as f:
                f.write(remote_compat_body)
                f.close()
        else:
            self.new_compat_avail = False
        
        message = 'You have the latest compatibility table.'
        if self.new_compat_avail:
            message = 'The compatibility table was updated. Please restart RCU to make these changes take effect.'
        mb = QMessageBox()
        mb.setWindowTitle('Compatibility Check')
        mb.setText(message)
        mb.exec()

        
