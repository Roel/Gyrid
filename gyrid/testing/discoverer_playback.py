#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
# Copyright (C) 2011  Mathias Versichele
# Copyright (C) 2011  Roel Huybrechts
#
# Gyrid is a Bluetooth device scanner daemon.
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

import random
import time
import datetime

import gyrid.discoverer

class Discoverer(gyrid.discoverer.Discoverer):
    """
    Discoverer that 'plays back' detections by reading them from a previously recorded rssi logfile.
    Timestamps generated will not reflect those in the original rssi logfile but current time instead !
    Used for stresstesting.
    """
    def __init__(self, mgr, logger, logger_rssi, device_id, mac):
        """
        Initialisation of the Discoverer. Store the reference to the loggers and
        query the necessary configuration options.

        @param  mgr          Reference to a Scanmanger instance.
        @param  logger       Reference to a Logger instance.
        @param  logger_rssi  Reference to a logger instance which records
                               the RSSI values.
        @param  device_id    The ID of the Bluetooth device used for scanning.
        @param  mac          The MAC address of the Bluetooth scanning device.
        """
        gyrid.discoverer.Discoverer.__init__(self, mgr, logger, logger_rssi,
            device_id, mac)

    def init(self):
        """
        Initialise.

        @return  0 on success, 1 on failure.
        """
        return 0

    def find(self):
        """
        Start 'scanning'. Continuously calls device_discovered with a fake MAC
        address, deviceclass and RSSI value.
        """
        shouldrun = True
        while shouldrun:
            linecount = 1

            tprevious = 0
            macprevious = ""
            rssiprevious = 0

            for line in open('/var/tmp/rssi.log', 'r'):
                #print 'line', linecount, ': ', line
                splits = line.split(',')

                t = datetime.datetime.strptime(splits[0], "%Y%m%d-%H%M%S-%Z")
                tline = int(t.strftime("%s"))
                macline = splits[1]
                rssiline = int(splits[2])

                if linecount > 1:
                    time.sleep((tline - tprevious) * 1.0)

                self.device_discovered(macprevious, 0, rssiprevious)
                linecount += 1
                tprevious = tline
                macprevious = macline
                rssiprevious = rssiline
            shouldrun = False
        return ""
