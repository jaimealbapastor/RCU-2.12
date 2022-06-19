'''
ConnectionErrorController.py
This is a modal that shows when a connection error happens. There isn't
anything the application can do to correct it.

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

from . import UIController
from pathlib import Path

class ConnectionErrorController(UIController):
    adir = Path(__file__).parent.parent
    ui_filename = Path(adir / 'views' / 'ConnectionError.ui')
    
    def __init__(self, parent_controller):
        super(type(self), self).__init__(parent_controller.model,
                                         parent_controller.threadpool)
        self.window.show()
