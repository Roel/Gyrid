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

import logging
import logging.handlers
import os
import threading
import time

import configuration
import zippingfilehandler

class Logger(object):
    """
    The Logger class handles all writing to the logfile and stores a pool
    of recently seen devices, in order to only write incoming and outgoing
    devices to the logfile.
    """
    def __init__(self, main):
        """
        Initialisation of the logfile, pool and poolchecker.
        
        @param  logfile      URL of the logfile to write to.
        @param  configfile   URL of the configfile to write to.
        """
        self.main = main
        
        self.scanlogger = logging.getLogger('BluetrackerScanLogger')
        self.scanlogger.setLevel(logging.INFO)
        handler = zippingfilehandler.TimedCompressedRotatingFileHandler(
            self.main)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.scanlogger.addHandler(handler)
        
        self.config = configuration.Configuration(self.main)
        self.started = False
        
        self.pool = {}
        self.temp_pool = {}
        self.poolchecker = PoolChecker(self.main, self)
        self.lock = threading.Lock()
        
    def write(self, timestamp, mac_address, device_class, moving):
        """
        Append the parameters to the logfile on a new line and flush the file.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  moving         Whether the device is moving 'in' or 'out'.
        """
        self.scanlogger.info(",".join([str(timestamp),
                                     str(mac_address),
                                     str(device_class),
                                     str(moving)]))
                                     
    def write_info(self, info):
        """
        Append a timestamp and the information to the logfile on a new line
        and flush the file.

        @param  info   The information to write.
        """
        self.scanlogger.info(",".join([str(int(time.time())), info]))

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
                    self.main.debug("%i devices in temporary pool, merging" % len(self.temp_pool))
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
            self.poolchecker = PoolChecker(self.main, self)
        self.main.debug("Started pool checker")
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
        """
        if self.config.get_value('alix_led_support') and \
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
    def __init__(self, main, logger):
        """
        Initialisation of the thread.
        
        @param   logger   Reference to Logger instance.
        """
        threading.Thread.__init__(self)
        self.main = main
        self.logger = logger
        self.buffer = self.logger.config.get_value('buffer_size')
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
                
                self.main.debug("Device pool checked: %(current)i devices " % d + \
                "(%(new)i new, %(gone)i disappeared)" % d)
                
            finally:
                self.logger.lock.release()
                
            time.sleep(self.buffer)
            
    def stop(self):
        """
        Stop the thread.
        """
        self._running = False
        self.main.debug("Stopped pool checker")
