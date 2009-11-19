#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
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
    def __init__(self, mgr):
        """
        Initialisation of the logfile.

        @param  mgr   Reference to a ScanManager instance.
        """
        self.mgr = mgr

        self.logger = self._get_logger()
        self.logger.setLevel(logging.INFO)

        self.time_format = self.mgr.config.get_value('time_format')

    def _get_log_location(self):
        return self.mgr.get_info_log_location()

    def _get_logger(self):
        logger = logging.getLogger('info')
        handler = logging.FileHandler(self._get_log_location())
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger

    def write_info(self, info):
        """
        Append a timestamp and the information to the logfile on a new line
        and flush the file.

        @param  info   The information to write.
        """
        self.logger.info(",".join([time.strftime(
            self.time_format,
            time.localtime()), info]))

class Logger(InfoLogger):
    """
    The Logger class handles all writing to the logfile and stores a pool
    of recently seen devices, in order to only write incoming and outgoing
    devices to the logfile.
    """
    def __init__(self, mgr, mac):
        """
        Initialisation of the logfile, pool and poolchecker.
        
        @param  logfile      URL of the logfile to write to.
        @param  configfile   URL of the configfile to write to.
        """
        self.mac = mac
        InfoLogger.__init__(self, mgr)
        
        self.started = False
        self.alix_led_support = self.mgr.config.get_value('alix_led_support')
        
        self.pool = {}
        self.temp_pool = {}
        self.poolchecker = PoolChecker(self.mgr, self)
        self.lock = threading.Lock()

    def _get_log_location(self):
        return self.mgr.get_scan_log_location(self.mac)

    def _get_logger(self):
        logger = logging.getLogger(self.mac)
        handler = zippingfilehandler.CompressingRotatingFileHandler(self.mgr,
            self._get_log_location())
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger
        
    def write(self, timestamp, mac_address, device_class, moving):
        """
        Append the parameters to the logfile on a new line and flush the file.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  moving         Whether the device is moving 'in' or 'out'.
        """
        self.logger.info(",".join([time.strftime(
            self.time_format, 
            time.localtime(timestamp)),
            str(mac_address),
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
            if mac_address not in self.pool:
                self.write(timestamp, mac_address, device_class, 'in')
            self.temp_pool[mac_address] = [timestamp, device_class]
        else:
            try:
                if len(self.temp_pool) > 0:
                    self.pool.update(self.temp_pool)
                    self.mgr.debug(
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
        self.mgr.debug("Started pool checker")
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
        if self.alix_led_support and \
                (False not in [os.path.exists('/sys/class/leds/alix:%i' % i) \
                for i in [1, 2, 3]]):
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
                
                self.mgr.debug(
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
        self.mgr.debug("Stopped pool checker")
