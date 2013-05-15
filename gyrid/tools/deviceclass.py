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
Module to get useful information from the device class of a Bluetooth
device.

Information from Bluetooth Assigned Numbers, Bluetooth Baseband:
    http://simon.dehartog.nl/datasheets/protocols/Bluetooth_assigned_numbers_baseband.pdf
"""

SERVICE_MASK = 0xffe000
MAJOR_MASK = 0x001f00
MINOR_MASK = 0x0000fc

SERVICE_CLASSES = {16: 'Positioning', 17: 'Networking', 18: 'Rendering',
                   19: 'Capturing', 20: 'Object transfer', 21: 'Audio',
                   22: 'Telephony', 23: 'Information'}

MAJOR_CLASSES = {256: 'Computer', 512: 'Phone',
                 768: 'Network access point', 1024: 'Audio/video',
                 1280: 'Peripheral', 1536: 'Imaging'}

MINOR_COMPUTER = {4: 'Desktop', 8: 'Server', 12: 'Laptop',
                  16: 'Handheld', 20: 'Palm sized', 24: 'Watch sized'}

MINOR_PHONE = {4: 'Cellular', 8: 'Cordless', 12: 'Smartphone',
               16: 'Modem', 20: 'ISDN'}

MINOR_AUDIOVIDEO = {4: 'Headset', 8: 'Handsfree', 16: 'Microphone',
                    20: 'Loudspeaker', 24: 'Headphones',
                    28: 'Portable audio', 32: 'Car audio',
                    36: 'Set-top box', 40: 'HiFi', 44: 'VCR',
                    48: 'Video camera', 52: 'Camcorder',
                    56: 'Video monitor', 60: 'Video display and loudspeaker',
                    64: 'Video conferencing', 72: 'Gaming'}

def _decimal_to_binary(number):
    """
    Convert a decimal number to a binary string.

    @param  number The number to convert.
    """
    hex_bin = {"0":"0000", "1":"0001", "2":"0010", "3":"0011", "4":"0100",
               "5":"0101", "6":"0110", "7":"0111", "8":"1000", "9":"1001",
               "A":"1010", "B":"1011", "C":"1100", "D":"1101", "E":"1110",
               "F":"1111"}
    return "".join([hex_bin[i] for i in '%X' % number]).lstrip('0')

def get_service_class(device_class):
    """
    Retrieve the service classes of the device with specified device
    class.

    @param  device_class  The device class of the device.
    @return A list of service classes (capabilities) of the device.
    """
    classes = []
    bin = _decimal_to_binary(device_class & SERVICE_MASK)
    invbin = bin[::-1]
    for i in range(len(invbin)):
        if invbin[i] == '1':
            classes.append(SERVICE_CLASSES[i])
    return classes

def get_major_class(device_class):
    """
    Retrieve the major class of the device with specified device class.

    @param  device_class  The device class of the device.
    @return The major device class (type of device), None when unknown.
    """
    try:
        return MAJOR_CLASSES[device_class & MAJOR_MASK]
    except KeyError:
        return None

def get_minor_class(device_class):
    """
    Retrieve the minor class of the device with specified device class.

    @param  device_class  The device class of the device.
    @return The minor device class (subtype of device), None when unknown.
    """
    dic = {'Computer': MINOR_COMPUTER,
           'Phone': MINOR_PHONE,
           'Audio/video': MINOR_AUDIOVIDEO}

    try:
        return dic[get_major_class(device_class)][device_class & MINOR_MASK]
    except KeyError:
        return None
