'''
ConnectionUtilityController.py
This is the main window of the application.

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

from PySide2.QtCore import Qt, QObject, QEvent, QCoreApplication, \
    QSettings, QTimer
from PySide2.QtWidgets import QListWidgetItem, QShortcut, QApplication
from PySide2.QtGui import QKeySequence, QPalette, QPixmap
from controllers import UIController
from panes import paneslist, IncompatiblePane
from pathlib import Path
import log

PANEROLE = 420

class GeometryEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize \
           or event.type() == QEvent.Move:
            if not hasattr(obj, '_appsettings'):
                return False
            size = obj.size()
            pos = obj.pos()
            obj._appsettings.setValue('cx_utility_controller/geosize', size)
            obj._appsettings.setValue('cx_utility_controller/geopos', pos)
            return True
        else:
            # standard event processing
            try:
                return QObject.eventFilter(self, obj, event)
            except:
                return False

class DroppedConnectionController(UIController):
    adir = Path(__file__).parent.parent
    ui_filename = Path(adir / 'views' / 'DroppedConnection.ui')

    def __init__(self, parent_controller):
        super(type(self), self).__init__(parent_controller.model,
                                         parent_controller.threadpool)
        iconfile = str(Path(type(self).adir / 'views' / 'dialog-warning.png'))
        icon = QPixmap()
        icon.load(iconfile)
        self.window.icon_label.setPixmap(icon)

class ConnectionUtilityController(UIController):
    adir = Path(__file__).parent.parent
    ui_filename = Path(adir / 'views' / 'ConnectionUtility.ui')

    def evaluate_cli_args(self, args):
        # Ask each pane to process its CLI arguments, then exit.
        count = self.window.listWidget.count()
        for n in range(0, count):
            pane = self.window.listWidget.item(n).data(PANEROLE)
            ret = pane.evaluate_cli(args)
            if (ret or 0) >= 1:
                QCoreApplication.exit(ret)
    
    def __init__(self, parent_controller):
        super(type(self), self).__init__(parent_controller.model,
                                         parent_controller.threadpool)
        self.parent_controller = parent_controller
        self.current_pane = None

        self.load_panes()

        # CLI vs. GUI
        if QCoreApplication.args.cli:
            log.info('is using cli')
            return self.evaluate_cli_args(QCoreApplication.args)
        log.info('is using gui')

        # Fix highlight color to whatever was set with theme
        ss = self.window.listWidget.styleSheet()
        newbgcolor = QCoreApplication.instance().palette().color(
            QPalette.Highlight)
        newbgalpha = 50
        if QCoreApplication.is_dark_mode:
            newbgalpha = 100
        newbgstr = 'rgba({}, {}, {}, {})'.format(newbgcolor.red(),
                                                 newbgcolor.green(),
                                                 newbgcolor.blue(),
                                                 newbgalpha)
        newcolor = QCoreApplication.instance().palette().color(
            QPalette.Text)
        newcolorstr = 'rgb({}, {}, {})'.format(newcolor.red(),
                                               newcolor.green(),
                                               newcolor.blue())
        ss += '''
QListWidget::item::selected  {
	/*background-color: rgb(191, 218, 229);*/
	/*background-color: rgba(150, 200, 210, 128);*/
	border: 1px solid rgba(90, 90, 90, 80);
	border-right: 1px solid rgba(128, 128, 128, 64);
	margin-right: -10px;
        background-color: ''' + newbgstr + ''';
        color: ''' + newcolorstr + ''';
}'''
        self.window.listWidget.setStyleSheet(ss)

        # Restore geometry
        oldsize = QSettings().value('cx_utility_controller/geosize')
        oldpos = QSettings().value('cx_utility_controller/geopos')
        if oldsize:
            self.window.resize(oldsize)
        if oldpos:
            self.window.move(oldpos)
        # Save geometry on resize
        self.window._appsettings = QSettings()
        efilt = GeometryEventFilter(self.window)
        self.window.installEventFilter(efilt)

        # Start active connection polling
        self.cx_timer = QTimer()
        self.cx_timer.setInterval(1000)
        self.cx_timer.timeout.connect(self.connection_check)
        self.cx_counter = 5
        # self.cx_timer.start()
        self.cx_check_pane = DroppedConnectionController(self)
        self.window.pane_layout.addWidget(self.cx_check_pane.window)
        self.cx_check_pane.window.hide()

        # do on click
        self.window.listWidget.currentItemChanged.connect(
            self.pane_change)

        # Quit shortcut
        quitshortcut = QShortcut(QKeySequence.Quit, self.window)
        quitshortcut.activated.connect(QApplication.instance().quit)
        closeshortcut = QShortcut(QKeySequence.Close, self.window)
        closeshortcut.activated.connect(QApplication.instance().quit)
        
        self.window.show()
        self.cx_timer.start()

    def connection_check(self):
        if self.cx_counter > 0:
            self.cx_counter -= 1
        else:
            self.cx_counter = 5
            if not self.model.is_connected() and not self.model.reconnect():
                log.error('no active connection; device is probably sleeping')
                self.show_checkscreen()
            else:
                self.hide_checkscreen()

    def show_checkscreen(self):
        if not self.cx_check_pane.window.isVisible():
            self.disable_all_panes()
            self.current_pane.data(PANEROLE).window.hide()
            self.cx_check_pane.window.show()

    def hide_checkscreen(self):
        if self.cx_check_pane.window.isVisible():
            self.reload_pane_compatibility()
            self.update_all_pane_data()
            self.enable_all_panes()
            self.cx_check_pane.window.hide()
            self.current_pane.data(PANEROLE).window.show()

    def pane_change(self, new=None):
        new_pane = new.data(PANEROLE)
        layout = self.window.pane_layout

        if self.current_pane:
            previous_pane = self.current_pane.data(PANEROLE)
            layout.removeWidget(previous_pane.window)
            previous_pane.window.hide()
        
        # load new pane into frame
        layout.addWidget(new_pane.window)
        new_pane.window.show()
        self.current_pane = new

        # Set the sidebar
        row = self.window.listWidget.row(new)
        self.window.listWidget.setCurrentRow(row)

        # save to config to reload on new start
        pname = type(new_pane).name
        QSettings().setValue(
            'cx_utility_controller/current_pane', pname)

    def load_panes(self):
        # Registers each pane in the sidebar
        restore_pane_name = QSettings().value(
            'cx_utility_controller/current_pane')
        firstpane = True
        restore_pane = False
        for pane in paneslist:
            newitem = QListWidgetItem(
                pane.get_icon(),
                pane.name)
            
            # Check compatibility
            no_compat_check = QCoreApplication.args.no_compat_check
            if no_compat_check:
                log.info('skipping pane compatibility check for {}'.
                         format(pane.name))
            if not no_compat_check \
               and not pane.is_compatible(self.model):
                # load the other pane
                log.info('{} pane not compatible'.format(pane.name))
                newitem.setData(PANEROLE, IncompatiblePane(self, pane))
            else:
                # The actual pane instance is stored with the
                # listwidgetitem
                newitem.setData(PANEROLE, pane(self))

            # Add pane to list
            self.window.listWidget.addItem(newitem)

            # Open the default pane upon load
            if firstpane:
                self.pane_change(newitem)
                firstpane = False
            elif pane.name == restore_pane_name \
                 and not self.model.is_in_recovery:
                restore_pane = newitem
        if restore_pane:
            self.pane_change(restore_pane)
        if self.model.is_in_recovery:
            self.disable_nonessential_panes()

    def reload_pane_compatibility(self):
        # After a restore, the version of Xochitl might have changed. Go
        # through each pane, and determine whether it should be replaced
        # with an incompatibility barrier, or the existing barrier
        # released.

        for i in range(0, self.window.listWidget.count()):
            lwitem = self.window.listWidget.item(i)
            pane = lwitem.data(PANEROLE)

            # If it is _already_ an IncompatiblePane, should it be?
            if type(pane) is IncompatiblePane:
                if pane.truepane.is_compatible(self.model):
                    # It really is compatible, so reload this pane with
                    # full compatibility.
                    lwitem.setData(PANEROLE, pane.truepane(self))

            # If it is _not_ an IncompatiblePane, should it be?
            if type(pane) is not IncompatiblePane:
                if not type(pane).is_compatible(self.model):
                    # It really isn't compatible, so hide it behind a
                    # veil.
                    lwitem.setData(PANEROLE,
                                   pane.IncompatiblePane(self, pane))

    def update_all_pane_data(self):
        # Asks all the panes to update their data
        log.info('update_all_pane_data')
        for i in range(0, self.window.listWidget.count()):
            pane = self.window.listWidget.item(i).data(PANEROLE)
            pane.update_view()

    def disable_nonessential_panes(self):
        # Disables panes during backups
        log.info('disable_nonessential_panes')
        for i in range(0, self.window.listWidget.count()):
            item = self.window.listWidget.item(i)
            pane = item.data(PANEROLE)
            if not type(pane).is_essential:
                log.info('--disabling {} essential={}'.format(pane.name, type(pane).is_essential))
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)

    def enable_all_panes(self):
        # The antithesis to disable_nonessential_panes()
        for i in range(0, self.window.listWidget.count()):
            item = self.window.listWidget.item(i)
            pane = item.data(PANEROLE)
            item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)

    def disable_all_panes(self):
        for i in range(0, self.window.listWidget.count()):
            item = self.window.listWidget.item(i)
            pane = item.data(PANEROLE)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
