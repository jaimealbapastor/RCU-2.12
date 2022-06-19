# Makefile
# This is the makefile for reMarkable Connection Utility.

# RCU is a synchronization tool for the reMarkable Tablet.
# Copyright (C) 2020  Davis Remmel
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see
# <https://www.gnu.org/licenses/>.

SHELL=bash
UNAME := $(shell uname)

# OS detection
# (Windows only supported via Make-win.bat)
OSNAME=generic
ifeq ($(UNAME), FreeBSD)
	OSNAME=FreeBSD
else ifeq ($(UNAME), Linux)
	OSNAME := $(shell source /etc/os-release && echo $$ID)
else ifeq ($(UNAME), Darwin)
	OSNAME=macOS
endif

# FreeBSD requires python3.7 because that's where the PySide2 port is.
# macOS requires python3.8 from Homebrew. Others may work, but that one
# is supported.
# Linux users may have a variety of pythons, so just test for the
# maximum version.
ifeq ($(UNAME), FreeBSD)
	PYTHON=python3.8
else ifeq ($(UNAME), Darwin)
	PYTHON:=$(shell which python3.8 || which python3 || echo "/usr/local/bin/python3.8")
else
#	GNU/Linux, Generic
	PYTHON := $(shell bash -c "which python3.9 || which python3.8 || which python3.7 || which python3.6")
endif

# Grab the RCU version from the src/version.txt file
RCUFULLVER := $(shell cut -f2 src/version.txt)
RCUVER := $(shell cut -f2 src/version.txt | tr -d '(' | tr -d ')')
RCUVERFLAG := $(shell cut -f2 src/version.txt | head -c 1)

all: dist/RCU

FORCE:

build:
	mkdir -p "$@"

dist:
	mkdir -p "$@"


# Documentation
.PHONY: doc
doc: manual/manual.pdf
manual/manual.pdf:
	(cat manual/manual.template.tex \
		| sed 's/%%RCUFULLVER%%/${RCUFULLVER}/g' \
		&& cat manual/license.template.tex \
		&& echo '\end{document}') \
		> manual/manual.tex
	(cd manual && pdflatex -shell-escape manual.tex && pdflatex -shell-escape manual.tex)


# Python venv
venv:
ifeq (${OSNAME}, FreeBSD)
	${PYTHON} -m venv --system-site-packages venv
	. venv/bin/activate; \
	pip install --upgrade pip; \
	pip install --ignore-installed -r src/requirements.txt
else
#	Don't use system site packages anywhere else--weird conflicts
#	may occur.
	${PYTHON} -m venv venv
	. venv/bin/activate; \
	pip install --upgrade pip; \
	pip install -r src/requirements.txt; \
	pip install -r src/optionals.txt
endif

.PHONY: clean-venv
clean-venv:
	rm -rf venv


# Icons
icons/windows-icon.ico: build
	convert \
		"icons/16x16/rcu-icon-16x16.png" \
		"icons/24x24/rcu-icon-24x24.png" \
		"icons/32x32/rcu-icon-32x32.png" \
		"icons/48x48/rcu-icon-48x48.png" \
		"icons/64x64/rcu-icon-64x64.png" \
		"icons/128x128/rcu-icon-128x128.png" \
		"icons/256x256/rcu-icon-256x256.png" \
		-colors 256 "$@"

# Run
.PHONY: run
run: venv
	. venv/bin/activate; \
	(cd src && python -B main.py)

# Main application
dist/RCU: venv FORCE
ifeq ($(UNAME), FreeBSD)
	. venv/bin/activate; \
	pyinstaller --hiddenimport PySide2.QtXml \
		--add-data "/usr/local/lib/qt5/plugins/platforms/libqxcb.so:PySide2/plugins/platforms" \
		--add-data "./src/views:views" \
		--add-data "./src/panes:panes" \
		--add-data "./src/model/pens/pencil_textures_linear:model/pens/pencil_textures_linear" \
		--add-data "./src/model/pens/pencil_textures_log:model/pens/pencil_textures_log" \
		--add-data "./src/model/pens/paintbrush_textures_log:model/pens/paintbrush_textures_log" \
		--add-data "./src/licenses:licenses" \
		--add-data "./src/version.txt:." \
		--add-data "./recovery_os_build:recovery_os_build" \
		--onefile \
		--name RCU \
		--console \
		src/main.py; \
	deactivate
endif
ifeq ($(UNAME), Linux)
	. venv/bin/activate; \
	pyinstaller --hiddenimport PySide2.QtXml \
		--add-data "./src/views:views" \
		--add-data "./src/panes:panes" \
		--add-data "./src/model/pens/pencil_textures_linear:model/pens/pencil_textures_linear" \
		--add-data "./src/model/pens/pencil_textures_log:model/pens/pencil_textures_log" \
		--add-data "./src/model/pens/paintbrush_textures_log:model/pens/paintbrush_textures_log" \
		--add-data "./src/licenses:licenses" \
		--add-data "./src/version.txt:." \
		--add-data "./recovery_os_build:recovery_os_build" \
		--onefile \
		--name RCU \
		--console \
		src/main.py; \
	deactivate
endif
ifeq ($(UNAME), Darwin)
	. venv/bin/activate; \
	pyinstaller --hiddenimport PySide2.QtXml \
		--add-data "./src/views:views" \
		--add-data "./src/panes:panes" \
		--add-data "./src/model/pens/pencil_textures_linear:model/pens/pencil_textures_linear" \
		--add-data "./src/model/pens/pencil_textures_log:model/pens/pencil_textures_log" \
		--add-data "./src/model/pens/paintbrush_textures_log:model/pens/paintbrush_textures_log" \
		--add-data "./src/licenses:licenses" \
		--add-data "./src/version.txt:." \
		--add-data "./recovery_os_build:recovery_os_build" \
		--osx-bundle-identifier "me.davisr.rcu" \
		--onefile \
		--name RCU \
		--windowed \
		--icon "./icons/mac-icon.icns" \
		src/main.py; \
	deactivate
endif


# Packaging
.PHONY: package
package: dist/rcu-${RCUVER}-${OSNAME}.tar.gz

# PKG_EXCLUDE="--exclude=.git --exclude=build --exclude=dist --exclude=venv --exclude=recovery_os"

# Package for FreeBSD (local only)
dist/rcu-${RCUVER}-FreeBSD.tar.gz: dist doc dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-$(UNAME)"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-FreeBSD/User Manual.pdf"
	cp "dist/RCU" "dist/rcu-${RCUVER}-FreeBSD/rcu"
	cp package_support/generic/* dist/rcu-${RCUVER}-FreeBSD/
	cp icons/32x32/rcu-icon-32x32.png dist/rcu-${RCUVER}-FreeBSD/davisr-rcu.png
	cp -r 'icons/mac-icon.iconset' 'dist/rcu-${RCUVER}-FreeBSD/Extra Icons'
	chmod +x dist/rcu-${RCUVER}-FreeBSD/*.sh
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-FreeBSD"

# Package for Ubuntu
dist/rcu-${RCUVER}-ubuntu.tar.gz: dist doc dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-ubuntu"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-ubuntu/User Manual.pdf"
	cp "dist/RCU" "dist/rcu-${RCUVER}-ubuntu/rcu"
	cp package_support/gnulinux/* dist/rcu-${RCUVER}-ubuntu/
	cp package_support/generic/* dist/rcu-${RCUVER}-ubuntu/
	cp icons/32x32/rcu-icon-32x32.png dist/rcu-${RCUVER}-ubuntu/davisr-rcu.png
	cp -r 'icons/mac-icon.iconset' 'dist/rcu-${RCUVER}-ubuntu/Extra Icons'
	chmod +x dist/rcu-${RCUVER}-ubuntu/*.sh
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-ubuntu"
.PHONY: remote-ubuntu-package
remote-ubuntu-package: doc dist
	ssh rcu-build-ubuntu 'rm -rf $$HOME/Downloads/rcu' && \
	ssh rcu-build-ubuntu 'mkdir -p $$HOME/Downloads/rcu' && \
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-cf - * \
		| ssh rcu-build-ubuntu 'tar -xf - -C Downloads/rcu' && \
	ssh rcu-build-ubuntu 'cd $$HOME/Downloads/rcu && make package' && \
	scp rcu-build-ubuntu:'$$HOME/Downloads/rcu/dist/rcu-${RCUVER}-ubuntu.tar.gz' dist/
.PHONY: remote-ubuntu18-package
remote-ubuntu18-package: doc dist
	ssh rcu-build-ubuntu18 'rm -rf $$HOME/Downloads/rcu' && \
	ssh rcu-build-ubuntu18 'mkdir -p $$HOME/Downloads/rcu' && \
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-cf - * \
		| ssh rcu-build-ubuntu18 'tar -xf - -C Downloads/rcu' && \
	ssh rcu-build-ubuntu18 'cd $$HOME/Downloads/rcu && make package' && \
	scp rcu-build-ubuntu18:'$$HOME/Downloads/rcu/dist/rcu-${RCUVER}-ubuntu.tar.gz' "dist/rcu-${RCUVER}-ubuntu18.tar.gz"


# Package for openSuse Leap 15.2
dist/rcu-${RCUVER}-opensuse-leap.tar.gz: dist doc dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-opensuse-leap"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-opensuse-leap/User Manual.pdf"
	cp "dist/RCU" "dist/rcu-${RCUVER}-opensuse-leap/rcu"
	cp package_support/gnulinux/* dist/rcu-${RCUVER}-opensuse-leap/
	cp package_support/generic/* dist/rcu-${RCUVER}-opensuse-leap/
	cp icons/32x32/rcu-icon-32x32.png dist/rcu-${RCUVER}-opensuse-leap/davisr-rcu.png
	cp -r 'icons/mac-icon.iconset' 'dist/rcu-${RCUVER}-opensuse-leap/Extra Icons'
	chmod +x dist/rcu-${RCUVER}-opensuse-leap/*.sh
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-opensuse-leap"
.PHONY: remote-opensuse-package
remote-opensuse-package: doc dist
	ssh rcu-build-opensuse 'rm -rf $$HOME/Downloads/rcu' && \
	ssh rcu-build-opensuse 'mkdir -p $$HOME/Downloads/rcu' && \
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-cf - * \
		| ssh rcu-build-opensuse 'tar -xf - -C Downloads/rcu' && \
	ssh rcu-build-opensuse 'cd $$HOME/Downloads/rcu && make package' && \
	scp rcu-build-opensuse:'$$HOME/Downloads/rcu/dist/rcu-${RCUVER}-opensuse-leap.tar.gz' dist/

# Package for CentOS 7
dist/rcu-${RCUVER}-centos.tar.gz: dist doc dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-centos"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-centos/User Manual.pdf"
	cp "dist/RCU" "dist/rcu-${RCUVER}-centos/rcu"
	cp package_support/gnulinux/* dist/rcu-${RCUVER}-centos/
	cp package_support/generic/* dist/rcu-${RCUVER}-centos/
	cp icons/32x32/rcu-icon-32x32.png dist/rcu-${RCUVER}-centos/davisr-rcu.png
	cp -r 'icons/mac-icon.iconset' 'dist/rcu-${RCUVER}-centos/Extra Icons'
	chmod +x dist/rcu-${RCUVER}-centos/*.sh
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-centos"
.PHONY: remote-centos-package
remote-centos-package: doc dist
	ssh rcu-build-centos 'rm -rf $$HOME/Downloads/rcu' && \
	ssh rcu-build-centos 'mkdir -p $$HOME/Downloads/rcu' && \
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-cf - * \
		| ssh rcu-build-centos 'tar -xf - -C Downloads/rcu' && \
	ssh rcu-build-centos 'cd $$HOME/Downloads/rcu && make package' && \
	scp rcu-build-centos:'$$HOME/Downloads/rcu/dist/rcu-${RCUVER}-centos.tar.gz' dist/

# Package for Fedora 33
dist/rcu-${RCUVER}-fedora.tar.gz: dist doc dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-fedora"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-fedora/User Manual.pdf"
	cp "dist/RCU" "dist/rcu-${RCUVER}-fedora/rcu"
	cp package_support/gnulinux/* dist/rcu-${RCUVER}-fedora/
	cp package_support/generic/* dist/rcu-${RCUVER}-fedora/
	cp icons/32x32/rcu-icon-32x32.png dist/rcu-${RCUVER}-fedora/davisr-rcu.png
	cp -r 'icons/mac-icon.iconset' 'dist/rcu-${RCUVER}-fedora/Extra Icons'
	chmod +x dist/rcu-${RCUVER}-fedora/*.sh
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-fedora"
.PHONY: remote-fedora-package
remote-fedora-package: doc dist
	ssh rcu-build-fedora 'rm -rf $$HOME/Downloads/rcu' && \
	ssh rcu-build-fedora 'mkdir -p $$HOME/Downloads/rcu' && \
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-cf - * \
		| ssh rcu-build-fedora 'tar -xf - -C Downloads/rcu' && \
	ssh rcu-build-fedora 'cd $$HOME/Downloads/rcu && make package' && \
	scp rcu-build-fedora:'$$HOME/Downloads/rcu/dist/rcu-${RCUVER}-fedora.tar.gz' dist/

# Package for macOS
dist/rcu-${RCUVER}-macOS.tar.gz: doc dist dist/RCU
	mkdir -p "dist/rcu-${RCUVER}-macOS"
	cp "manual/manual.pdf" "dist/rcu-${RCUVER}-macOS/User Manual.pdf"
	cp -r "dist/RCU.app" "dist/rcu-${RCUVER}-macOS/RCU.app"
	tar -zcf "$@" -C "dist" "rcu-${RCUVER}-macOS"
.PHONY: remote-mac-package
remote-mac-package: doc dist
	ssh rcu-build-mac 'rm -rf $$HOME/Downloads/rcu' && \
	ssh rcu-build-mac 'mkdir -p $$HOME/Downloads/rcu' && \
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-cf - * \
		| ssh rcu-build-mac 'tar -xf - -C Downloads/rcu' && \
	ssh rcu-build-mac 'cd $$HOME/Downloads/rcu && make package' && \
	scp rcu-build-mac:'$$HOME/Downloads/rcu/dist/rcu-${RCUVER}-macOS.tar.gz' dist/

# Package for Windows (no local packaging available)
.PHONY: remote-windows-package
remote-windows-package: doc dist build
	- ssh rcu-build-win 'rmdir /S /Q Downloads\rcu'
	ssh rcu-build-win 'mkdir Downloads\rcu'
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-cf build/win-bundle.tar *
	scp build/win-bundle.tar rcu-build-win:'Downloads'
	ssh rcu-build-win 'tar -xf Downloads\win-bundle.tar -C Downloads\rcu'
	ssh rcu-build-win 'cd Downloads\rcu && ..\venv-rcu\Scripts\activate && Make-win.bat'
	mkdir -p "dist/rcu-${RCUVER}-Windows"
	scp rcu-build-win:'Downloads/rcu/dist/RCU.exe' dist/rcu-${RCUVER}-Windows/
	cp 'manual/manual.pdf' 'dist/rcu-${RCUVER}-Windows/User Manual.pdf'
	cp package_support/windows/* dist/rcu-${RCUVER}-Windows/
	cp -r 'icons/mac-icon.iconset' 'dist/rcu-${RCUVER}-Windows/Extra Icons'
	(cd dist && zip -r rcu-${RCUVER}-Windows.zip rcu-${RCUVER}-Windows)

# Package for RCU source
.PHONY: package-source
package-source: dist/rcu-${RCUVER}-source.tar.gz
dist/rcu-${RCUVER}-source.tar.gz: dist build-clean clean-doc python-clean
	tar --exclude=.git --exclude=build --exclude=dist \
		--exclude=venv --exclude=recovery_os \
		-zcf "$@" -C ../ rcu


# Package for Recovery OS source
# The recovery OS contains Linux and U-Boot, and os it is very large
# (hundreds of megabytes). It is shipped seperately from the regular
# RCU source package.
.PHONY: package-source-ros
package-source-ros: dist/rcu-${RCUVER}-ros-source.tar.gz
dist/rcu-${RCUVER}-ros-source.tar.gz: dist
	tar --exclude=.git -zcf "$@" -C ../ rcu/recovery_os


# Release bundle (all packages)
# The author uses this to generate all release files. Assumed to be
# running under FreeBSD with remote build VMs.
.PHONY: release
release: doc package remote-ubuntu-package remote-ubuntu18-package remote-fedora-package remote-centos-package remote-opensuse-package remote-mac-package remote-windows-package package-source package-source-ros
#	mkdir dist/upload
#	mv dist/*.tar.gz dist/upload
#	mv dist/*.zip dist/upload
#	(cd dist/upload && for f in *; do gpg --detach-sign --armor "$$f"; done)

# Cleanup
.PHONY: clean
clean: build-clean dist-clean python-clean clean-doc

.PHONY: build-clean
build-clean:
	rm -rf "build"

.PHONY: dist-clean
dist-clean:
	rm -rf "dist"

.PHONY: clean-doc
clean-doc:
	- find manual -name "*.aux" -o -name "*.log" -o -name "*.out" -o -name "*.toc" -o -name "manual.tex" -o -name "manual.pdf" -o -name "_minted-manual" | xargs rm -rf

# doc-stage is like clean-doc, but leaves the manual.pdf
.PHONY: doc-stage
doc-stage:
	- find manual -name "*.aux" -o -name "*.log" -o -name "*.out" -o -name "*.toc" -o -name "manual.tex" -o -name "_minted-manual" | xargs rm -rf

.PHONY: python-clean
python-clean:
	- find . -type f -name "*.core" -exec rm -f {} \;
	- find . -type d -name venv -prune -o -name "__pycache__" -exec rm -rf {} \;
	rm -rf *.spec
