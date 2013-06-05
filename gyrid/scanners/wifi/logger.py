#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2009-2011  Roel Huybrechts
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

import logging
import logging.handlers
import os
import threading
import time

from gyrid.logger import InfoLogger
from scanners.bluetooth.logger import ScanLogger
from gyrid.zippingfilehandler import CompressingRotatingFileHandler


class WiFiRawLogger(InfoLogger):
    def __init__(self, mgr, mac):
        """
        Initialisation of the logfile.

        @param  mgr   Reference to Scanmanager instance.
        @param  mac   The MAC-address of the adapter used for scanning.
        """
        self.mgr = mgr
        self.mac = mac
        InfoLogger.__init__(self, mgr, self._get_log_location())

        self.enable = True

    def _get_log_id(self):
        return '%s-wifiraw' % self.mac

    def _get_log_location(self):
        return self.mgr.get_wifiraw_log_location(self.mac)

    def _get_logger(self):
        logger = logging.getLogger(self._get_log_id())
        handler = CompressingRotatingFileHandler(self.mgr,
            self._get_log_location())
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger

    def write(self, timestamp, frequency, type, subtype, hwid1, hwid2, rssi, retry, info):
        """
        Append the parameters to the logfile on a new line and flush the file.
        Try sending the data over the network.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  rssi           The RSSI value of the received Bluetooth signal.
        """
        if self.enable and not (self.mgr.debug_mode and self.mgr.debug_silent):
            a = [time.strftime(self.time_format, time.localtime(timestamp))]
            a.extend([str(i) for i in [frequency, type, subtype, hwid1, hwid2, rssi, retry, info]])

            self.logger.info(",".join(a))


class WiFiPoolChecker(threading.Thread):
    """
    The PoolChecker checks the device_pool at regular intervals to delete
    devices that have not been seen for x amount of time from the pool.
    It is a subclass of threading.Thread to start in a new thread automatically.
    """
    def __init__(self, mgr, logger):
        """
        Initialisation of the thread.

        @param   logger   Reference to Logger instance.
        """
        threading.Thread.__init__(self)
        self.mgr = mgr
        self.logger = logger
        self.buffer = 30
        self._running = True

    def run(self):
        """
        Start the thread. Loop over the device pool at a regular interval and
        delete devices that have not been seen since x amount of time. Write
        them to the logfile as being moved 'out'.
        """
        previous = 0
        while self._running:
            self.logger.lock.acquire()
            try:
                tijd = int(time.time())

                to_delete = []
                for device in self.logger.pool:
                    if tijd - self.logger.pool[device] > self.buffer:
                        self.logger.write(self.logger.pool[device],
                                          device,
                                          'out')
                        to_delete.append(device)

                new = len(self.logger.pool) - previous
                # Delete
                for device in to_delete:
                    del(self.logger.pool[device])

                current = len(self.logger.pool)

                d = {'current': current,
                     'new': new if new > 0 else 0,
                     'gone': len(to_delete)}
                previous = current

                self.mgr.debug("%s: " % self.logger.mac +
                    "Device pool checked: %(current)i device" % d + \
                    ("s " if current != 1 else " ") + \
                    "(%(new)i new, %(gone)i disappeared)" % d)

            finally:
                self.logger.lock.release()

            time.sleep(self.buffer)

    def stop(self):
        """
        Stop the thread.
        """
        self._running = False
        self.mgr.debug("%s: Stopped pool checker" % self.logger.mac)

class WiFiLogger(ScanLogger):
    def __init__(self, mgr, mac, type):
        self.type = type
        ScanLogger.__init__(self, mgr, mac)

        self.poolchecker = WiFiPoolChecker(self.mgr, self)

    def _get_log_id(self):
        return '%s-wifi-%s' % (self.mac, self.type)

    def _get_log_location(self):
        return self.mgr.get_wifi_log_location(self.mac, self.type)

    def start(self):
        """
        Start the poolchecker, which checks at regular intervals the pool for
        devices that have disappeared.
        """
        if not 'poolchecker' in self.__dict__:
            self.poolchecker = WiFiPoolChecker(self.mgr, self)
        self.mgr.debug("%s: Started pool checker" % self.mac)
        self.pool.clear()
        self.temp_pool.clear()
        self.poolchecker.start()

    def write(self, timestamp, hwid, moving):
        """
        Append the parameters to the logfile on a new line and flush the file.
        Try sending the data over the network.

        @param  timestamp      UNIX timestamp.
        @param  hwid           Hardware id of the WiFi device.
        @param  moving         Whether the device is moving 'in' or 'out'.
        """
        if not (self.mgr.debug_mode and self.mgr.debug_silent):
            self.logger.info(",".join([time.strftime(
                self.time_format,
                time.localtime(timestamp)),
                str(hwid),
                str(moving)]))
            self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_IO', self.mac, timestamp,
                hwid, self.type, moving]))

    def seen_device(self, timestamp, hwid):
        if hwid in self.pool:
            self.update_device(timestamp, hwid)
            return True
        return False

    def update_device(self, timestamp, hwid):
        """
        Update the device with specified mac_address in the pool.

        @param  timestamp      UNIX timestamp.
        @param  hwid           Hardware id of the WiFi device.
        """
        if not self.lock.acquire(False):
            #Failed to lock
            self.temp_pool[hwid] = timestamp
        else:
            try:
                if len(self.temp_pool) > 0:
                    for id in self.temp_pool:
                        if id not in self.pool:
                            self.write(timestamp, id, 'in')
                    self.pool.update(self.temp_pool)
                    self.mgr.debug("%s: " % self.mac + \
                        "%i devices in temporary pool, merging" % \
                        len(self.temp_pool))
                    self.temp_pool.clear()
                self.switch_led(3)

                if hwid not in self.pool:
                    self.write(timestamp, hwid, 'in')

                self.pool[hwid] = timestamp
            finally:
                self.lock.release()
