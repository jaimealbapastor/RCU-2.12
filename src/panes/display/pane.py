'''
pane.py
This is the Display pane.

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

from PySide2.QtCore import Qt, QSize, QObject, QEvent, QSettings, \
    QCoreApplication
from PySide2.QtGui import QImage, QPixmap, QColor, QIcon
from PySide2.QtWidgets import QFileDialog, QWidget
from pathlib import Path
from datetime import datetime
from controllers import UIController
from worker import Worker
import log
import gc
import ctypes


class ResizeEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            if not hasattr(obj, 'screen_pixmap'):
                return False
            pxmap = obj.screen_pixmap
            obj.setPixmap(pxmap.scaled(obj.width(),
                                       obj.height(),
                                       Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
            return True
        else:
            # standard event processing
            return QObject.eventFilter(self, obj, event)
    

class DisplayPane(UIController):
    identity = 'me.davisr.rcu.display'
    name = 'Display'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'display.ui')

    compat_hw = ['^RM100$', '^RM102$', '^RM110$']

    cli_args = [('--screenshot-p', 1, ('out.png'), 'take a screenshot (portrait)'),
                ('--screenshot-l', 1, ('out.png'), 'take a screenshot (landscape)')]

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'video-display.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon
    
    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.pane_controller = pane_controller
        self.landscape = False
    
        if not QCoreApplication.args.cli:
            # Load initial orientation
            self.landscape = QSettings().value(
                'pane/display/orient_landscape')
            if self.landscape is None:
                self.landscape = False
            else:
                self.landscape = bool(int(self.landscape))
                self.window.portrait_radioButton.setChecked(not self.landscape)
                self.window.landscape_radioButton.setChecked(self.landscape)
        
            self.start_load_screen()

            # Replace placeholder label with our own
            efilt = ResizeEventFilter(self.window)
            self.window.testlabel.installEventFilter(efilt)
        
            # Button handlers
            self.window.refresh_pushButton.clicked.connect(
                self.start_load_screen)
            self.window.screenshot_pushButton.clicked.connect(
                self.save_image)
            self.window.portrait_radioButton.clicked.connect(
                self.change_orientation)
            self.window.landscape_radioButton.clicked.connect(
                self.change_orientation)

    def update_view(self):
        self.start_load_screen()

    def change_orientation(self):
        ppb = self.window.portrait_radioButton
        lpb = self.window.landscape_radioButton
        if (ppb.isChecked() and self.landscape) \
           or (lpb.isChecked() and not self.landscape):
            # Orientation changed
            log.info('changing display orientation')
            self.landscape = lpb.isChecked()
            # Remember orientation
            QSettings().setValue(
                'pane/display/orient_landscape',
                int(self.landscape))
            self.start_load_screen()

    def start_load_screen(self):
        # Used to kick off thread
        self.disable_buttons()
        worker = Worker(fn=self.load_screen)
        self.threadpool.start(worker)
        worker.signals.finished.connect(self.enable_buttons)
        worker.signals.progress.connect(
            lambda x: self.window.progressBar.setValue(x))

    def disable_buttons(self):
        self.window.refresh_pushButton.setEnabled(False)
        self.window.screenshot_pushButton.setEnabled(False)
        self.window.progress_label.show()
        self.window.progressBar.show()
        self.window.progressBar.setValue(0)

    def enable_buttons(self):
        self.window.refresh_pushButton.setEnabled(True)
        self.window.screenshot_pushButton.setEnabled(True)
        self.window.progress_label.hide()
        self.window.progressBar.hide()

    def save_image(self, outfile=None, landscape=False):
        # Saves screenshot to disk

        if not hasattr(self.window.testlabel, 'screen_pixmap'):
            log.info('Cannot save screenshot when one does not exist')
            return

        # Get the default directory to save under
        if not outfile:
            default_savepath = QSettings().value(
                'pane/display/last_export_path')
            if not default_savepath:
                QSettings().setValue(
                    'pane/display/last_export_path',
                    Path.home())
                default_savepath = Path.home()
                
            pfile = datetime.now().strftime('rM Screen %Y-%m-%d %H_%M_%S.png')
            filename = QFileDialog.getSaveFileName(
                self.window,
                'Save Screenshot',
                Path(default_savepath / pfile).__str__(),
                'Images (*.png)')
            if not filename[0] or filename[0] == '':
                return False
            outfile = Path(filename[0])
        else:
            outfile = Path(outfile[0])

        # If landscape, rotate it. (only used for cli, todo: use in gui)
        if landscape:
            self.window.testlabel.screen_pixmap
        self.window.testlabel.screen_pixmap.save(str(outfile), 'PNG')        
        log.info('saved screenshot')
        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/display/last_export_path',
            outfile.parent)

    def load_screen(self, progress_callback=None):
        # Captures the screen from the device and loads it into a
        # QPixmap.
        
        if not self.landscape:
            pngdata = self.model.display.get_image_portrait()
        else:
            pngdata = self.model.display.get_image_landscape()

        if progress_callback:
            progress_callback.emit(50)
        
        label = self.window.testlabel
        pxmap = QPixmap()
        pxmap.loadFromData(pngdata, 'PNG')
        label.screen_pixmap = pxmap.copy()
        label.setPixmap(pxmap.copy().scaled(label.width(),
                                     label.height(),
                                     Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation))
        ctypes.c_long.from_address(id(pxmap)).value=1
        del pxmap
        gc.collect()

        if progress_callback:
            progress_callback.emit(100)

    def evaluate_cli(self, args):
        if args.screenshot_p:
            self.landscape = False
            self.load_screen()
            if self.save_image(outfile=args.screenshot_p):
                return 0
            return 1
        elif args.screenshot_l:
            self.landscape = True
            self.load_screen()
            if self.save_image(outfile=args.screenshot_l):
                return 0
            return 1
