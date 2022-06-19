#!/usr/bin/env bash

# pkg.sh
# This is a sample using the RMPKG format. It is intended to be used as
# a sample package so other developers understand the format.

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

if [[ "" == "$PREFIX" ]]
then
    PREFIX="$HOME/.local"
fi

# Identify the payload
pload_match="$(grep -n '^##### PAYLOAD #####$' "$0" \
                    | cut -d':' -f1)"
pload_start=$((pload_match + 1))

# --info will print information about this package.
if [[ "--info" == "$1" ]]
then
    awk '/^##### INFO #####$/{f=1;next} /^#####/{f=0} f' "$0"
    exit 0
fi

# --manifest will show all files which are modified by the install AND
# uninstall procedures. It is supposed to be run against all .rmpkg
# files to understand which ones conflict.
if [[ "--manifest" == "$1" ]]
then
    awk '/^##### MANIFEST #####$/{f=1;next} /^#####/{f=0} f' "$0" \
	| awk '$0="'$PREFIX'/"$0'
    exit 0
fi

# --install will perform all necessary operations to install this
# package.
if [[ "--install" == "$1" ]]
then
    set -x
    tail -n "+$pload_start" "$0" | tar xvf - -C "$PREFIX"
    set +x
    exit 0
fi

# --uninstall will perform all necessary operations to uninstall this
# package.
if [[ "--uninstall" == "$1" ]]
then
    set -x
    rmfiles=$(tail -n "+$pload_start" "$0" \
	| tar tf - \
	| sort -r \
	| awk '$0="'$PREFIX'/"$0')
    echo "$rmfiles" | xargs rm -rf
    set +x
    exit 0
fi

>&2 echo "Unsupported flag: specify --info, --manifest, --install, \
or --uninstall."
exit 0

# Below this line, the Makefile will append various payloads. Required
# sections include "INFO" and "MANIFEST". This sample application will
# apply a binary "PAYLOAD" section as well.
