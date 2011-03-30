#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
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

import zippingfilehandler

class InfoLogger(object):
    """
    The InfoLogger class handles writing informational messages to a logfile.
    """
    def __init__(self, mgr, log_location):
        """
        Initialisation of the logfile.

        @param  mgr   Reference to a ScanManager instance.
        @param  log_location  The location of the logfile.
        """
        self.mgr = mgr
        self.log_location = log_location

        self.logger = self._get_logger()
        self.logger.setLevel(logging.INFO)

        self.time_format = self.mgr.config.get_value('time_format')

    def _get_log_id(self):
        return self.log_location

    def _get_logger(self):
        logger = logging.getLogger(self._get_log_id())
        handler = logging.FileHandler(self.log_location)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger

    def write_info(self, info):
        """
        Append a timestamp and the information to the logfile on a new line
        and flush the file. Try sending the info over the network.

        @param  info   The information to write.
        """
        if not (self.mgr.debug_mode and self.mgr.debug_silent):
            self.logger.info(",".join([time.strftime(
                self.time_format,
                time.localtime()), info]))
        self.mgr.net_send_line(",".join(['INFO',
                time.strftime('%s',
                time.localtime()),
                info]))

class RSSILogger(InfoLogger):
    """
    The RSSI logger takes care of the logging of RSSI-enabled queries.
    """
    def __init__(self, mgr, mac):
        """
        Initialisation of the logfile, pool and poolchecker.

        @param  mgr   Reference to Scanmanager instance.
        @param  mac   The MAC-address of the adapter used for scanning.
        """
        self.mgr = mgr
        self.mac = mac
        InfoLogger.__init__(self, mgr, self._get_log_location())

        self.enable = self.mgr.config.get_value('enable_rssi_log')

    def _get_log_id(self):
        return '%s-rssi' % self.mac

    def _get_log_location(self):
        return self.mgr.get_rssi_log_location(self.mac)

    def _get_log_processing(self):
        return False

    def _get_logger(self):
        logger = logging.getLogger(self._get_log_id())
        handler = zippingfilehandler.CompressingRotatingFileHandler(self.mgr,
            self._get_log_location(), self._get_log_processing())
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger

    def write(self, timestamp, mac_address, device_class, rssi):
        """
        Append the parameters to the logfile on a new line and flush the file.
        Try sending the data over the network.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  rssi           The RSSI value of the received Bluetooth signal.
        """
        if self.enable and not (self.mgr.debug_mode and self.mgr.debug_silent):
            self.logger.info(",".join([time.strftime(
                self.time_format,
                time.localtime(timestamp)),
                str(mac_address),
                str(rssi)]))
        self.mgr.net_send_line(",".join(['SIGHT_RSSI',
            str(self.mac.replace(':','')),
            str(timestamp),
            str(mac_address.replace(':','')),
            str(rssi)]))

class ScanLogger(RSSILogger):
    """
    The Logger class handles all writing to the logfile and stores a pool
    of recently seen devices, in order to only write incoming and outgoing
    devices to the logfile.
    """
    def __init__(self, mgr, mac):
        """
        Initialisation of the logfile, pool and poolchecker.

        @param  mgr   Reference to Scanmanager instance.
        @param  mac   The MAC-address of the adapter used for scanning.
        """
        self.mgr = mgr
        self.mac = mac
        RSSILogger.__init__(self, mgr, mac)

        self.started = False
        self.alix_led_support = (self.mgr.config.get_value(
            'alix_led_support') and (False not in [os.path.exists(
            '/sys/class/leds/alix:%i' % i) for i in [2, 3]]))

        self.pool = {}
        self.temp_pool = {}
        self.poolchecker = PoolChecker(self.mgr, self)
        self.lock = threading.Lock()

    def _get_log_id(self):
        return '%s-scan' % self.mac

    def _get_log_location(self):
        return self.mgr.get_scan_log_location(self.mac)

    def _get_log_processing(self):
        return True

    def write(self, timestamp, mac_address, device_class, moving):
        """
        Append the parameters to the logfile on a new line and flush the file.
        Try sending the data over the network.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  moving         Whether the device is moving 'in' or 'out'.
        """
        if not (self.mgr.debug_mode and self.mgr.debug_silent):
            self.logger.info(",".join([time.strftime(
                self.time_format,
                time.localtime(timestamp)),
                str(mac_address),
                str(device_class),
                str(moving)]))
        self.mgr.net_send_line(",".join(['SIGHT_CELL',
                str(self.mac.replace(':','')),
                str(timestamp),
                str(mac_address.replace(':','')),
                str(device_class),
                str(moving)]))

    def update_device(self, timestamp, mac_address, device_class):
        """
        Update the device with specified mac_address in the pool.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        """
        if not self.lock.acquire(False):
            #Failed to lock
            self.temp_pool[mac_address] = [timestamp, device_class]
        else:
            try:
                if len(self.temp_pool) > 0:
                    for mac in self.temp_pool:
                        if mac not in self.pool:
                            self.write(timestamp, mac, device_class, 'in')
                    self.pool.update(self.temp_pool)
                    self.mgr.debug("%s: " % self.mac + \
                        "%i devices in temporary pool, merging" % \
                        len(self.temp_pool))
                    self.temp_pool.clear()
                self.switch_led(3)

                if mac_address not in self.pool:
                    self.write(timestamp, mac_address, device_class, 'in')

                self.pool[mac_address] = [timestamp, device_class]
            finally:
                self.lock.release()

    def start(self):
        """
        Start the poolchecker, which checks at regular intervals the pool for
        devices that have disappeared.
        """
        if not 'poolchecker' in self.__dict__:
            self.poolchecker = PoolChecker(self.mgr, self)
        self.mgr.debug("%s: Started pool checker" % self.mac)
        self.pool.clear()
        self.temp_pool.clear()
        self.poolchecker.start()

    def stop(self):
        """
        Stop the poolchecker.
        """
        self.poolchecker.stop()
        del(self.poolchecker)

    def switch_led(self, id):
        """
        Switch the state of the LED (on/off) with the specified id.
        Checks if such a LED exists on the system before trying to set it.
        """
        if 2 <= id <= 3 and self.alix_led_support \
            and not os.path.exists('/tmp/gyrid-led-disabled'):
            swap = {0: 1, 1: 0}

            file = open('/sys/class/leds/alix:%i/brightness' % id, 'r')
            current_state = int(file.read()[0])
            file.close()

            file = open('/sys/class/leds/alix:%i/brightness' % id, 'w')
            file.write(str(swap[current_state]))
            file.close()

class PoolChecker(threading.Thread):
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
        self.buffer = self.logger.mgr.config.get_value('buffer_size')
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
                self.logger.switch_led(2)

                tijd = int(time.time())

                to_delete = []
                for device in self.logger.pool:
                    if tijd - self.logger.pool[device][0] > self.buffer:
                        self.logger.write(self.logger.pool[device][0],
                                          device,
                                          self.logger.pool[device][1],
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
