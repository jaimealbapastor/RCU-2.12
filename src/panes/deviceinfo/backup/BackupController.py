'''
BackupController.py
This is the UIController for backups.

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

import tarfile
import tempfile
import pathlib
from pathlib import Path
import log
from .Backup import Backup
import json
from datetime import datetime
import platform

from PySide2.QtWidgets import QTreeWidgetItem, QHeaderView, \
    QMenu, QTreeWidget, QFrame, QAbstractItemView, QMessageBox, \
    QSizePolicy
from PySide2.QtCore import Qt, QRect

def prettydate(then, abs=False):
    now = datetime.now().timestamp()
    offset = datetime.fromtimestamp(now) \
        - datetime.utcfromtimestamp(now)
    tzdate = then + offset
    now = datetime.now()
    fmt = '%b %d, %Y at %I:%M %p'
    if now.date() == tzdate.date():
        fmt = 'Today at %I:%M %p'
    elif (now.date() - tzdate.date()).days == 1:
        fmt = 'Yesterday at %I:%M %p'
    elif now.year - tzdate.year == 0:
        fmt = '%b %d at %I:%M %p'
    if abs:
        fmt = '%B %d, %Y at %I:%M %p'
    return tzdate.strftime(fmt).replace(' 0', ' ')

class BackupQTreeWidget(QTreeWidget):
    def __init__(self, controller, *args, **kwargs):
        super(type(self), self).__init__(controller.window.backup_tree_placeholder, *args, **kwargs)
        self.controller = controller
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            self.open_menu)
        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setTextAlignment(
            2, Qt.AlignLeading|Qt.AlignVCenter);
        __qtreewidgetitem.setText(3, 'TS')
        __qtreewidgetitem.setText(2, 'Size on Disk')
        __qtreewidgetitem.setText(1, 'OS Version')
        __qtreewidgetitem.setText(0, 'Timestamp')
        self.setHeaderItem(__qtreewidgetitem)
        self.setObjectName(u"backup_treeWidget")
        sizePolicy2 = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(sizePolicy2)

        
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setEditTriggers(
            QAbstractItemView.NoEditTriggers)
        self.setProperty("showDropIndicator", False)
        self.setSelectionBehavior(
            QAbstractItemView.SelectRows)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(False)
        self.setAllColumnsShowFocus(True)
        self.header().setVisible(True)
        self.header().setStretchLastSection(True)
        self.header().setSectionHidden(3, True)

        # # Platform-specific stuff
        # plat = platform.system()
        # if 'Windows' == plat:
        #     self.setAlternatingRowColors(False)
        # else:
        #     self.setAlternatingRowColors(True)
        self.setAlternatingRowColors(True)
        # Windows shows the default differently, so be explicit
        #self.setStyleSheet('alternate-background-color: #f9f9f9;')

        controller.window.backup_treelayout.addWidget(self, 1, 0, 1, 1)
            
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Escape and
            event.modifiers() == Qt.NoModifier):
            self.selectionModel().clear()
        else:
            super(type(self), self).keyPressEvent(event)
            
    def mousePressEvent(self, event):
        if not self.indexAt(event.pos()).isValid():
            self.selectionModel().clear()
        super(type(self), self).mousePressEvent(event)
        
    def open_menu(self, position):
        item = self.currentItem()
        if not item:
            return
        menu = item.get_menu()
        menu.exec_(self.viewport().mapToGlobal(position))
        

class BackupQTreeWidgetItem(QTreeWidgetItem):
    def __init__(self, controller, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        self.controller = controller
        self._userData = None
    def setUserData(self, userData=None):
        self._userData = userData
    def userData(self):
        return self._userData
    def get_menu(self):
        backup = self.userData()
        menu = QMenu()

        # Restore options depend on the backup type
        restore = None
        restore_types = backup.get_restore_types()
        for t in restore_types:
            if restore is None:
                restore = menu.addMenu('Restore')
            name = t[0] + ' Restore'
            trig = t[1]
            act = restore.addAction(name)
            act.triggered.connect(
                lambda checked=False,
                t=trig: self.controller.pane.make_restore(t))

        menu.addSeparator()
        delete = menu.addAction('Delete')
        delete.triggered.connect(self.delete)
        
        return menu
        
    
    def delete(self):
        # Deletes itself
        backup = self.userData()

        mb = QMessageBox()
        mb.setWindowTitle('Delete Backup')
        mb.setText('Do you want to permanently delete this backup?')
        mb.setDetailedText(prettydate(backup.timestamp, abs=True))
        mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
        mb.setDefaultButton(QMessageBox.No)
        ret = mb.exec()
        if int(QMessageBox.Yes) != ret:
            return
        backup.delete_data()
        # remove treewidget item
        i = self.treeWidget().indexOfTopLevelItem(self)
        self.treeWidget().takeTopLevelItem(i)

class BackupController():
    # This is the controller for the UI widget that appears in the
    # backup box.
    baktools_path = Path(Path(__file__).parent / 'baktools')
    
    def __init__(self, pane):
        self.pane = pane
        self.model = pane.model
        self.window = pane.window
        self.backups = []
        self.backup_dir = pane.backup_dir
        self.abort = False # Flag; when set to True, abort!

        # Overlay a new TreeWidget (the GUI designer one is just a
        # placeholder).
        self.window.backup_treeWidget = BackupQTreeWidget(self)
        self.treewidget = self.window.backup_treeWidget

        # # Detect stuck backup
        # if self.detect_stuck_backup_mode():
        #     mb = QMessageBox()
        #     mb.setWindowTitle('Stuck Backup Detected')
        #     mb.setText('RCU has detected a stuck backup and will now fix it. The interface may freeze for a moment.')
        #     mb.exec()

        # Finish
        self.find_and_load_backups()

    def detect_stuck_backup_mode(self):
        # If RCU is just starting up, and the tablet is detected in
        # backup mode, then get it out of that mode and bring it back!
        log.info('detect stuck backup mode')
        cmd = 'test -e /var/run/bakwait.pid && echo $?'
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('problem in detect_stuck_backup_mode')
            log.error(err)
            return False
        status = out.strip('\n')
        log.info(out)
        if '0' != status:
            # not backup mode
            return False
        # is backup mode
        return True
        
    def get_abort(self):
        if self.abort:
            log.info('Abort is true!')
        return self.abort
    def set_abort(self):
        self.abort = True
    def reset_abort(self):
        self.abort = False
    def find_and_load_backups(self):
        # Find all the backup files in this directory. Look for
        # backup.json files at depth=1. Load them into self.backups.
        psearch = self.backup_dir.glob('*/backup.json')
        for path in psearch:
            with open(path, 'r') as f:
                d = json.load(f)
                self.load_backup(d)
    def load_backup(self, obj):
        # Pass in a decoded json object, get a Backup
        if type(obj) is Backup:
            backup = obj
        else:
            backup = Backup(self, obj)

        # Make sure this backup isn't already loaded
        for i in range(0, self.treewidget.topLevelItemCount()):
            ti = self.treewidget.topLevelItem(i)
            bid = ti.userData().bid
            if backup.bid == bid:
                return
        
        # Don't load incomplete backups
        if not backup.complete:
            return

        # Don't load backups which are incompatible with the current
        # device model number. (This is not implemented correctly--
        # it really ought to check the backup's model number, and
        # compare against the current model number. As of this writing,
        # there are only two reMarkable models.) Todo...
        if 'RM100' != self.model.device_info['model'] \
           and 'RM102' != self.model.device_info['model']:
            #log.info('skipping backup because model does not match', self.model.device_info['model'])
            #log.info(self.model.device_info)
            return
        
        # Add to tree
        item = BackupQTreeWidgetItem(self)
        item.setUserData(backup)

        pdate = prettydate(backup.timestamp)
        item.setData(0, 0, pdate)
        item.setData(1, 0, backup.device_info['osver'])
        
        mib = int(round(backup.get_size() / 1024 / 1024))
        mibstring = '{} MiB'.format(mib)
        item.setData(2, 0, mibstring)
        
        # hidden columns
        # 10: epoch number (sort by timestamp)
        ts = backup.timestamp.timestamp()
        item.setData(3, 0, ts.__str__())
        # add to treewidget
        self.treewidget.addTopLevelItem(item)
        # re-sort treewidget by epoch number
        self.treewidget.sortItems(3, Qt.SortOrder.DescendingOrder)

        # Resize header elements
        header = self.treewidget.header()
        header.setSectionResizeMode(
            QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)

        # Add contextual menu
        #menu = QMenu()
        #item.addMenu(menu)
    def make_backup(self, progress_callback, bfiles):
        # Makes a new backup
        # btype can be 'full', 'os', or 'data'
        log.info('making backup')

        # Perform backup
        backup = Backup(self).as_new(bfiles)
        try:
            status = backup.do_backup(self.get_abort, progress_callback)
        except Exception as e:
            status = False
            log.error('Error during backup')
            log.error(e)
        if status:
            # Success -- load it in the list
            # Backups are loaded in the list by the pane, since this is
            # called by a thread.
            pass
        # done?
        # If we aborted, delete all the files.
        if self.get_abort():
            backup.delete_data()
        self.reset_abort()
