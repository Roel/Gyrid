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

import time
import datetime

import gyrid.discoverer

class Discoverer(gyrid.discoverer.Discoverer):
    """
    Discoverer that 'plays back' detections by reading them from a previously
    recorded rssi logfile. Timestamps generated will not reflect those in the
    original rssi logfile but will use current time instead!

    The logfile should be an existing file, residing in /var/tmp/rssi.log

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
        self.log = open('/var/tmp/rssi.log', 'r')
        return 0

    def find(self):
        """
        Start 'scanning'. Continuously calls device_discovered based on the
        detections in the logfile.
        """
        linecount = 1

        for line in self.log:
            splits = line.split(',')

            t = datetime.datetime.strptime(splits[0], "%Y%m%d-%H%M%S-%Z")
            tline = int(t.strftime("%s"))
            macline = splits[1]
            rssiline = int(splits[2])

            if linecount == 1:
                macprevious = macline
                rssiprevious = rssiline
            else:
                self.device_discovered(macprevious, 0, rssiprevious)
                time.sleep((tline - tprevious) * 1.0)

            linecount += 1
            tprevious = tline
            macprevious = macline
            rssiprevious = rssiline

        self.log.close()
        return ""
