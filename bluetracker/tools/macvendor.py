#-*- coding: utf-8 -*-
#
# This file belongs to Bluetracker.
#
# Bluetracker is a Bluetooth device scanner daemon.
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

VENDOR_MAC = {}

def _parse_oui(url):
    """
    Parse the file populating the VENDOR_MAC dictionary.
    
    @param  url   URL of the file to parse.
    """
    for line in open(url, 'r'):
        if '(hex)' in line:
            VENDOR_MAC [line[:8].replace('-', ':')] = line.split(
                '\t\t')[-1].strip(' \r\n')
                
def get_vendor(mac_address):
    """
    Retrieve the vendor company of the device with specified mac address.
    
    @param  mac_address  The mac address of the device.
    """
    try:
        return VENDOR_MAC[mac_address[:8]]
    except KeyError:
        return None
        
#Parse the oui file on importing
_parse_oui('oui.txt')
