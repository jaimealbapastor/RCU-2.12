# Makefile
# This is a sample makefile to build the .rmpkg file.

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

all: build/MyPackage.rmpkg

.PHONY: clean build
clean:
	rm -rf build

build:
	mkdir -p build

build/MyPackage.rmpkg: build pkg.sh info.txt MyPackage
	cp pkg.sh $@
	echo "##### INFO #####" >> $@
	cat info.txt >> $@
	echo "##### MANIFEST #####" >> $@
	find MyPackage >> $@
	echo "##### PAYLOAD #####" >> $@
	tar cf - MyPackage >> $@
	chmod +x $@
