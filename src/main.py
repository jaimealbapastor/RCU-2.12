'''
main.py
This is the master run file for reMarkable Connection Utility.

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

# Provide tracebacks in case of crash
import faulthandler
faulthandler.enable(all_threads=True)

import platform
import os
if 'Darwin' == platform.system():
    # Fixes a problem where the main window wouldn't show past the
    # Connection Dialog in macOS 11 (the application appears to stall).
    os.environ['QT_MAC_WANTS_LAYER'] = '1'
    # Fixes a problem reading some PDF files, which are tried to be
    # decoded with 'ascii' instead of 'utf-8' when running as a binary
    # (this could have instead be fixed in the open() calls in
    # document.py, but since RCU is English-only this way may not be
    # problematic).
    os.environ['LANG'] = 'en_US.UTF-8'

# Give these to all our children
global worker
import worker
global log
import log
global svgtools
import svgtools as svgtools

import model
from controllers import ConnectionDialogController
from panes import paneslist


from pathlib import Path
import sys
from PySide2.QtWidgets import QApplication, QStyleFactory
from PySide2.QtCore import QCoreApplication, Qt, QThreadPool, QSettings
from PySide2.QtGui import QFont, QPalette, QColor

# Handle Ctrl-C
import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)

# Standard command line arguments
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-v', '--version',
                    help='print version number and exit',
                    action='store_true')
parser.add_argument('--autoconnect',
                    help='immediately connect to the last-used preset',
                    action='store_true')
parser.add_argument('--dark',
                    help='force dark theme',
                    action='store_true')
parser.add_argument('--no-compat-check',
                    help='skip pane compatibility checks (load anyway)',
                    action='store_true')
parser.add_argument('--cli',
                    help='run headless (best used with --autoconnect)',
                    action='store_true')

# Load CLI arguments for each of the available panes.
group = parser.add_mutually_exclusive_group()
for pane in paneslist:
    for arg in pane.cli_args:
        if arg[1] is True:
            group.add_argument(arg[0],
                                help=arg[3],
                                action='store_true')
        else:
            group.add_argument(arg[0],
                                nargs=arg[1],
                                metavar=arg[2],
                                help=arg[3])
# Rendering RMN to PDF will not load the rest of the program and may be
# used alone.
group.add_argument('--render-rmn-pdf-b',
                   nargs=2,
                   metavar=('in.rmn', 'out.pdf'),
                   help='render local RMN archive to PDF (bitmap)')
group.add_argument('--render-rmn-pdf-v',
                   nargs=2,
                   metavar=('in.rmn', 'out.pdf'),
                   help='render local RMN archive to PDF (vector)')

args = parser.parse_args()

if args.cli:
    log.activated = False


# Start main application
if __name__ == '__main__':
    QCoreApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    QCoreApplication.setOrganizationName('davisr')
    QCoreApplication.setOrganizationDomain('davisr.me')
    QCoreApplication.setApplicationName('rcu')

    # Make CLI arguments accessible throughout the program
    QCoreApplication.args = args

    # Version is now stored in version.txt
    ui_basepath = '.'
    if hasattr(sys, '_MEIPASS'):
        ui_basepath = sys._MEIPASS
    versiontxt = Path(Path(ui_basepath) / 'version.txt')
    with open(versiontxt, 'r') as f:
        vstring = f.read().splitlines()[0].strip().split('\t')
        sortcode = vstring[0]
        prettyver = vstring[1]
        QCoreApplication.version_sortcode = sortcode
        QCoreApplication.setApplicationVersion(prettyver)
        if args.version:
            log.info(prettyver)
            sys.exit(0)
        else:
            log.info('running version {}'.format(prettyver))

    # Find the share dir
    share_dir = Path(Path.home() / \
                      Path('.local') / \
                      Path('share') / \
                      Path(QCoreApplication.organizationName()) / \
                      Path(QCoreApplication.applicationName()))
    if 'Windows' == platform.system():
        share_dir = Path(Path.home() / \
                          Path('AppData') / \
                          Path('Roaming') / \
                          Path(QCoreApplication.organizationName()) / \
                          Path(QCoreApplication.applicationName()))
    elif 'Darwin' == platform.system():
        share_dir = Path(Path.home() / \
                          Path('Library') / \
                          Path('Application Support') / \
                          Path(QCoreApplication.applicationName()))
    test_sharedir = QSettings().value('main/share_path')
    if test_sharedir:
        QCoreApplication.sharePath = Path(test_sharedir)
    else:
        QCoreApplication.sharePath = share_dir
        QSettings().setValue('main/share_path', str(share_dir))
    QCoreApplication.sharePath.mkdir(parents=True, exist_ok=True)
    
    app = QApplication(sys.argv)

    # Keep consistent style across platforms (hard to write code when
    # spacing/geometry is slightly different on every platform).
    app.setStyle(QStyleFactory.create('Fusion'))
    # Tweak the fonts on different platforms
    plat = platform.system()
    if 'Windows' == plat:
        # Todo: only set this to 9pt when the user has not already
        # changed their desktop font size.
        # ...
        app.setFont(QFont('Segoe UI', 9))
    # if 'Linux' == plat:
    #     app.setFont(QFont('sans-serif', 9))
    if 'Darwin' == plat:
        # macOS font is to get past Qt 5.13.2 issue where there is no
        # spacing after a comma (QTBUG-86496).
        app.setFont(QFont('Lucida Grande'))

    # Dark mode
    QCoreApplication.is_dark_mode = False
    palette = QPalette()
    if args.dark:
        QCoreApplication.is_dark_mode = True
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(187, 138, 255))
        palette.setColor(QPalette.Highlight, QColor(97, 42, 218))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        darkGray = QColor(53, 53, 53);
        gray = QColor(128, 128, 128);
        black = QColor(25, 25, 25);
        blue = QColor(42, 130, 218);
        palette.setColor(QPalette.Active, QPalette.Button, gray.darker());
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, gray);
        palette.setColor(QPalette.Disabled, QPalette.WindowText, gray);
        palette.setColor(QPalette.Disabled, QPalette.Text, gray);
        palette.setColor(QPalette.Disabled, QPalette.Light, darkGray);
        app.setPalette(palette)
        app.setStyleSheet('QToolTip { color: #ffffff; background-color: #2a82da; border: 1px solid white; }')
    app.setPalette(palette)

    # The model and threadpool are distributed to all panes.
    model = model.RCU(QCoreApplication)
    threadpool = QThreadPool()

    # Skip main application for rendering RMN to PDF. Use dummy docs.
    if args.render_rmn_pdf_b or args.render_rmn_pdf_v:
        from model.document import Document
        from model.display import DisplayRM
        model.display = DisplayRM(model)
        arg = args.render_rmn_pdf_b or args.render_rmn_pdf_v
        doc = Document(model)
        doc.use_local_archive = arg[0]
        # no connection
        if doc.save_pdf(arg[1], vector=args.render_rmn_pdf_v):
            sys.exit(0)
        else:
            sys.exit(1)

    # Start the main application with the Connection Dialog.
    connection_dialog = ConnectionDialogController(model,
                                                   threadpool)
    sys.exit(app.exec_())
