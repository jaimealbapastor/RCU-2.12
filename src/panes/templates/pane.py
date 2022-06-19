'''
pane.py
This is the Template Manager pane.

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

from controllers import UIController
from pathlib import Path
import log
from PySide2.QtWidgets import QTreeWidgetItem, QTreeWidget, QMenu, \
    QFrame, QAbstractItemView, QMessageBox, QHeaderView, QFileDialog, \
    QSizePolicy
from PySide2.QtSvg import QSvgWidget
from PySide2.QtCore import Qt, QRect, QByteArray, QSize, QObject, \
    QEvent, QSettings, QCoreApplication
from PySide2.QtGui import QIcon
from model.template import Template
import platform
import re

import svgtools

from .importcontroller import TemplateImporter


class TemplatesPane(UIController):
    identity = 'me.davisr.rcu.templates'
    name = 'Templates'

    adir = Path(__file__).parent.parent
    bdir = Path(__file__).parent
    ui_filename = Path(adir / bdir / 'templates.ui')

    xochitl_versions = [
        '^1\.8\.1\.[0-9]+$',
        '^2\.[0-8]\.[0-9]+\.[0-9]+$',
        '^2\.9\.[0-1]\.[0-9]+$'
    ]

    @classmethod
    def get_icon(cls):
        ipathstr = str(Path(cls.bdir / 'icons' / 'emblem-documents.png'))
        icon = QIcon()
        icon.addFile(ipathstr, QSize(16, 16), QIcon.Normal, QIcon.On)
        return icon

    def __init__(self, pane_controller):
        super(type(self), self).__init__(
            pane_controller.model, pane_controller.threadpool)

        self.templates_controller = TemplatesController(self)

        self.model.register_templates_pane(self)

        if not QCoreApplication.args.cli:
            # Check for broken templates, maybe from a system update
            self.check_broken_templates()

            # Finish loading templates
            self.update_view()
        
            # Button handlers
            self.window.download_pushButton.clicked.connect(
                self.templates_controller.download_template)
            self.window.upload_pushButton.clicked.connect(
                self.templates_controller.upload_template)

    def update_view(self):
        # This gets bounced back to this class from the model.
        if self.model.is_in_recovery:
            return
        self.model.load_templates(trigger_ui=False)
        self.load_items()

    def check_broken_templates(self):
        # Was the OS upgraded and user-installed templates no longer
        # there? Tell the user that we're restoring them. If they don't
        # want them, they must delete them through the tree interface.
        brokenids = self.templates_controller.get_broken_templates()
        if brokenids:
            mb = QMessageBox()
            mb.setWindowTitle('Broken Templates Detected')
            mb.setText('Broken templates were detected. This may have occurred after a recent OS software update. Repair them?')
            # It would be nice to list the template names to the user
            # Todo...
            mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
            mb.setDefaultButton(QMessageBox.Yes)
            ret = mb.exec()
            if ret == int(QMessageBox.Yes):
                self.templates_controller.fix_broken_templates(
                    brokenids)
        
    def load_items(self):
        self.templates_controller.load_templates()
        self.enable_buttons()
        
    def enable_buttons(self):
        # After templates get finished loading
        self.window.upload_pushButton.setEnabled(True)
        self.window.category_comboBox.setEnabled(True)
        self.window.loading_widget.hide()

        
class TemplateQTreeWidgetItem(QTreeWidgetItem):
    def __init__(self, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        
    def setUserData(self, userData=None):
        self._userData = userData
        self.update_from_data()
        
    def userData(self):
        return self._userData

    def update_from_data(self):
        template = self.userData()
        self.setData(0, 0, template.name)
        self.setData(1, 0, template.orientation())
    
    def get_menu(self):
        menu = QMenu()
        delete = menu.addAction('Delete')
        delete.triggered.connect(self.delete)
        return menu
    
    def delete(self):
        # Deletes itself
        template = self.userData()

        mb = QMessageBox()
        mb.setWindowTitle('Delete Template')
        mb.setText('Do you want to permanently delete this template?')
        mb.setDetailedText('{} ({})'.format(
            template.name, template.orientation()))
        mb.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
        mb.setDefaultButton(QMessageBox.No)
        ret = mb.exec()
        if int(QMessageBox.Yes) != ret:
            return

        template.delete_from_device()
        
        i = self.treeWidget().indexOfTopLevelItem(self)
        self.treeWidget().takeTopLevelItem(i)
        
    def sort_compare(self, bTemplateItem):
        # Compare this item with another for sort order.
        at = self.userData()
        bt = bTemplateItem.userData()

        afields = at.name.lower().split(' ')
        afields.append(str(int(at.landscape)))
        
        bfields = bt.name.lower().split(' ')
        bfields.append(str(int(bt.landscape)))

        # Pad the lesser
        alen = len(afields)
        blen = len(bfields)
        diff = abs(alen - blen)
        if alen < blen:
            afields += [''] * diff
        elif alen > blen:
            bfields += [''] * diff

        # same length, now compare
        for i in range(0, len(afields)):
            af = afields[i]
            bf = bfields[i]
            if af < bf:
                return -1
            if bf < af:
                return 1
        # they were equal
        return 0

class TemplateQTreeWidget(QTreeWidget):
    def __init__(self, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            self.open_menu)
        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setText(0, 'Name')
        __qtreewidgetitem.setText(1, 'Orient.')
        self.setHeaderItem(__qtreewidgetitem)
        self.setObjectName(u"templates_treeWidget")
        # Would be wiser to get these properties from the placeholder UI
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
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(QHeaderView.Stretch)
        self.header().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)

        sizePolicy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(sizePolicy)

        # # Platform-specific stuff
        # plat = platform.system()
        # if 'Windows' == plat:
        #     self.setAlternatingRowColors(False)
        # else:
        #     self.setAlternatingRowColors(True)
        self.setAlternatingRowColors(True)
        # Windows shows the default differently, so be explicit
        #self.setStyleSheet('alternate-background-color: #f9f9f9;')
            
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


class ResizeEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            if not hasattr(obj, 'svg_pixmap'):
                return False
            pxmap = obj.svg_pixmap
            obj.setPixmap(pxmap.scaled(obj.width(),
                                       obj.height(),
                                       Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
            return True
        else:
            # standard event processing
            return QObject.eventFilter(self, obj, event)
        
class TemplatesController:
    def __init__(self, pane):
        self.pane = pane
        self.model = self.pane.model
        self.window = self.pane.window

        self.importer = TemplateImporter(self.pane)

        self.categorycombo = self.window.category_comboBox
        self.categorycombo.currentIndexChanged.connect(
            self.change_category)

        # Load svg renderer
        svgpreview = QSvgWidget()
        self.window.svg_preview = svgpreview
        
        ef = ResizeEventFilter(self.window)
        self.window.svg_label.installEventFilter(ef)
        

        tw = TemplateQTreeWidget(self.window)
        self.window.selector_layout.replaceWidget(
            self.window.tree_placeholder,
            tw)
        self.treewidget = tw
        self.treewidget.currentItemChanged.connect(
            self.load_svg_preview)
    
    def load_templates(self):
        # Loads the template descriptions from the device. Only adds
        # widget items for templates that aren't already loaded. The
        # methods referenced here already make the checks to avoid
        # duplicate entries.

        if not self.model.templates or not len(self.model.templates):
            self.model.load_templates()

        # There is a bug here -- categories can be added, but not
        # removed. I am not fixing this right now because I don't
        # think it is pressing--the templates for rM have remained
        # constant for a while, and I think it is unlikely they
        # will add new ones. TODO...

        # If there is a treewidget item that does not exist in the new
        # model template set, remove it.
        template_items_to_unload = set()
        for i in range(0, self.treewidget.topLevelItemCount()):
            ti = self.treewidget.topLevelItem(i)
            tidata = ti.userData()
            exists = False
            for t in self.model.templates:
                if t is tidata:
                    exists = True
                    break
            if not exists:
                template_items_to_unload.add(ti)
        for ti in template_items_to_unload:
            i = self.treewidget.indexOfTopLevelItem(ti)
            self.treewidget.takeTopLevelItem(i)

        # Add new categories and templates
        for template in self.model.templates:
            cats = template.categories
            for c in cats:
                self.add_category_item(c)
            self.add_template_tree_item(template)

        # Update the view according to the current category
        self.change_category()

    def add_category_item(self, cname):
        # Add a new category to the list if it doesn't already exist.
        loaded_categories = set()
        for i in range(0, self.categorycombo.count()):
            ct = self.categorycombo.itemText(i)
            loaded_categories.add(ct)
        if cname in loaded_categories:
            return
        self.categorycombo.insertItem(self.categorycombo.count(), cname)
            
    def add_template_tree_item(self, template):
        # Adds a new top level item in sorted order
        # Only add if template doesn't already exist
        for i in range(0, self.treewidget.topLevelItemCount()):
            ti = self.treewidget.topLevelItem(i)
            tidata = ti.userData()
            if tidata is template:
                # Update the data and move on
                ti.update_from_data()
                return
        titem = TemplateQTreeWidgetItem()
        titem.setUserData(template)
        if not self.treewidget.topLevelItemCount():
            self.treewidget.addTopLevelItem(titem)
        else:
            for i in range(0, self.treewidget.topLevelItemCount()):
                it = self.treewidget.topLevelItem(i)
                if titem.sort_compare(it) < 1:
                    self.treewidget.insertTopLevelItem(i, titem)
                    break
            self.treewidget.addTopLevelItem(titem)
            
    def load_svg_preview(self):
        # Load the template as svg preview
        item = self.treewidget.currentItem()
        if not item:
            # self.window.svg_preview.load(QByteArray())
            self.render_svg_preview()
            self.window.download_pushButton.setEnabled(False)
            return
        # self.window.svg_preview.load(item.userData().get_svg())
        self.render_svg_preview(item.userData().get_svg())
        self.window.download_pushButton.setEnabled(True)

    def render_svg_preview(self, svgdata=None):
        # load_svg_preview only loads it--this method will also load it
        # into the svg_label (which handles size and layout)
        label = self.window.svg_label
        if not svgdata:
            # clear the window
            label.clear()
            return
        pxmap = svgtools.svg_to_pixmap(
            svgdata,
            type(self.model.display).portrait_size)
        self.window.svg_label.svg_pixmap = pxmap
        label.setPixmap(pxmap.scaled(
            label.width(),
            label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation))
        
    def change_category(self):
        catname = self.categorycombo.currentText()
        for i in range(0, self.treewidget.topLevelItemCount()):
            item = self.treewidget.topLevelItem(i)
            icats = item.userData().categories
            if catname == 'All' or catname in icats:
                item.setHidden(False)
            else:
                item.setHidden(True)
                
    def download_template(self):
        # Saves the currently-selected template to disk

        # Get the default directory to save under
        default_savepath = QSettings().value(
            'pane/templates/last_export_path')
        if not default_savepath:
            QSettings().setValue(
                'pane/templates/last_export_path',
                Path.home())
            default_savepath = Path.home()
        
        item = self.treewidget.currentItem()
        template = item.userData()
        sanitized = re.sub('[\/\\\!\@\#\$\%\^\&\*\~\|\:\;\?\`\’\“\'\"]',
                           '_',
                           template.get_pretty_name_with_orient())
        tname = sanitized + '.rmt'
        filename = QFileDialog.getSaveFileName(
            self.window,
            'Save Template',
            Path(default_savepath / tname).__str__(),
            'Templates (*.rmt)')
        if not filename[0] or filename[0] == '':
            return
        filepath = Path(filename[0])
        template.save_archive(filepath)
        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/templates/last_export_path',
            filepath.parent)
        
        
    def upload_template(self):
        # Uploads a templatename.rmt

        # Get the default directory to save under
        default_savepath = QSettings().value(
            'pane/templates/last_import_path')
        if not default_savepath:
            QSettings().setValue(
                'pane/templates/last_import_path',
                Path.home())
            default_savepath = Path.home()

        # open dialog, get target file
        filename = QFileDialog.getOpenFileName(
            self.window,
            'Open Template',
            str(default_savepath),
            'Templates (*.rmt *.svg *.png)')
        if not filename[0] or filename[0] == '':
            return
        filepath = Path(filename[0])

        # Save the last path directory for convenience
        QSettings().setValue(
            'pane/templates/last_import_path',
            filepath.parent)

        # Throw it over to the template importer to complete
        self.importer.upload_template(filepath)

    def get_broken_templates(self):
        # Detects if there are templates in the userpathpfx that are not
        # linked in the syspathpfx, or not included in the
        # templates.json file.
        log.info('checking for broken templates')
        broken_template_ids = set()
        cmd = '(cd "{}" 2>/dev/null && (find . -maxdepth 1 -name "*.json" | while read -r file; do id=`basename "$file" .json`; test -e "./$id.png" && test -e "$id.svg" && echo "$id"; done | while read -r id; do (test -L "{}/$id.png" && test -L "{}/$id.svg") || echo "$id"; done))'.format(Template.userpathpfx, Template.syspathpfx, Template.syspathpfx)
        out, err = self.model.run_cmd(cmd)
        if len(err):
            log.error('problem detecting broken template links')
            log.error(err)
            log.error('error in command: {}'.format(cmd))
            return
        if not len(out):
            # No broken links detected
            return
        
        # Detect broken filenames in template.json
        # This is unlikely...maybe TODO...
            
        log.info('detected broken templates')
        for line in out.splitlines():
            broken_template_ids.add(line)
        return broken_template_ids

    def fix_broken_templates(self, ids):
        # Fix the broken templates, given a set() of IDs (filenames)
        for tid in ids:
            # These have been pre-verified by the shell command in
            # get_broken_templates(), so we can fix immediately.
            Template(self.model).repair_links_with_id(tid)

        # Force the model to reload templates. Since this pane is
        # registered with that function, the UI will update.
        self.model.load_templates()
        self.model.restart_xochitl()
