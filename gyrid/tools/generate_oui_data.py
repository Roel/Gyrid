#!/usr/bin/python
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
Script to write a tabseparated 'oui_data.txt' file based on IEEE data.
"""

if __name__ == '__main__':
    import urllib

    input = urllib.urlopen("http://standards.ieee.org/regauth/oui/oui.txt", 'r')
    output = open('oui_data.txt', 'w')

    output.write("#Original data downloaded from http://standards.ieee.org/regauth/oui/oui.txt")
    output.write("\n#\n#MAC-address\tVendor\n")
    for line in input:
        if '(hex)' in line:
            mac = line[2:10].replace('-', ':')
            vendor = line.split('\t\t')[-1].strip(' \r\n')
            output.write('\t'.join([mac, vendor]) + '\n')

    input.close()
    output.close()
