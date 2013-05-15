#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2009  Roel Huybrechts
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""
Module to get the vendor company from a mac address of a Bluetooth
device.

Source of information (oui.txt):
    http://standards.ieee.org/regauth/oui/oui.txt
"""

import gzip
import os

VENDOR_MAC = {}

def _parse_oui(url):
    """
    Parse the file populating the VENDOR_MAC dictionary.

    @param  url   URL of the file to parse.
    """
    if url.endswith('.gz'):
        file = gzip.GzipFile(url, 'r')
    else:
        file = open(url, 'r')
    for line in file:
        if not line.startswith('#'):
            ls = line.split('\t')
            VENDOR_MAC [ls[0]] = ls[1].strip('\n')
    file.close()

def get_vendor(mac_address):
    """
    Retrieve the vendor company of the device with specified mac address.

    @param  mac_address  The mac address of the device.
    """
    try:
        return VENDOR_MAC[mac_address[:8].upper()]
    except KeyError:
        return None

#Parse the oui file on importing
try:
    __dir__ = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(__dir__, 'oui_data.txt')
    _parse_oui(filepath)
except IOError:
    _parse_oui('/usr/share/gyrid/oui_data.txt.gz')
