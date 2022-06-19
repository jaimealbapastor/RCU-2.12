:: Make-win.bat
:: This is the Windows makefile for reMarkable Connection Utility.
::
:: RCU is a synchronization tool for the reMarkable Tablet.
:: Copyright (C) 2020  Davis Remmel
:: 
:: This program is free software: you can redistribute it and/or modify
:: it under the terms of the GNU Affero General Public License as
:: published by the Free Software Foundation, either version 3 of the
:: License, or (at your option) any later version.
:: 
:: This program is distributed in the hope that it will be useful,
:: but WITHOUT ANY WARRANTY; without even the implied warranty of
:: MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
:: GNU Affero General Public License for more details.
:: 
:: You should have received a copy of the GNU Affero General Public License
:: along with this program.  If not, see <https://www.gnu.org/licenses/>.

pyinstaller --hiddenimport PySide2.QtXml ^
	--add-data ".\src\views;views" ^
	--add-data ".\src\panes;panes" ^
	--add-data ".\src\model\pens\pencil_textures_linear;model\pens\pencil_textures_linear" ^
	--add-data ".\src\model\pens\pencil_textures_log;model\pens\pencil_textures_log" ^
	--add-data ".\src\model\pens\paintbrush_textures_log;model\pens\paintbrush_textures_log" ^
	--add-data ".\src\licenses;licenses" ^
	--add-data ".\src\version.txt;." ^
	--add-data ".\recovery_os_build;recovery_os_build" ^
	--icon ".\icons\windows-icon.ico" ^
	--onefile ^
	--name RCU ^
	--console ^
	src\main.py
