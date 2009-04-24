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

import threading
import time

import configuration

class Logger(object):
    """
    The Logger class handles all writing to the logfile and stores a pool
    of recently seen devices, in order to only write incoming and outgoing
    devices to the logfile.
    """
    def __init__(self, logfile, configfile):
        """
        Initialisation of the logfile, pool and poolchecker.
        
        @param  logfile      URL of the logfile to write to.
        @param  configfile   URL of the configfile to write to.
        """
        self.logfile = open(logfile, 'a')
        self.config = configuration.Configuration(configfile)
        self.started = False
        
        self.pool = {}
        self.poolchecker = PoolChecker(self)
        
    def write(self, timestamp, mac_address, device_class, moving):
        """
        Append the parameters to the logfile on a new line and flush the file.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  moving         Whether the device is moving 'in' or 'out'.
        """
        self.logfile.write(",".join([str(timestamp),
                                     str(mac_address),
                                     str(device_class),
                                     str(moving)]))
        self.logfile.write("\n")
        self.logfile.flush()

    def write_info(self, info):
        """
        Append a timestamp and the information to the logfile on a new line
        and flush the file.

        @param  info   The information to write.
        """
        self.logfile.write(",".join([str(int(time.time())), info]))
        self.logfile.write("\n")
        self.logfile.flush()

    def update_device(self, timestamp, mac_address, device_class):
        """
        Update the device with specified mac_address in the pool.
        
        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        """
        if mac_address not in self.pool:
            self.write(timestamp, mac_address, device_class, 'in')
            
        self.pool[mac_address] = [timestamp, device_class]
                    
    def start(self):
        """
        Start the poolchecker, which checks at regular intervals the pool for
        deviced that have disappeared.
        """
        if not 'poolchecker' in self.__dict__:
            self.poolchecker = PoolChecker(self)
        self.poolchecker.start()
        
    def stop(self):
        """
        Stop the poolchecker.
        """
        self.poolchecker.stop()
        del(self.poolchecker)
        
    def close(self):
        """
        Stop the poolchecker and close the logfile.
        """
        self.stop()
        self.logfile.close()
        
class PoolChecker(threading.Thread):
    """
    The PoolChecker checks the device_pool at regular intervals to delete
    devices that have not been seen for x amount of time from the pool.
    It is a subclass of threading.Thread to start in a new thread automatically.
    """
    def __init__(self, logger):
        """
        Initialisation of the thread.
        
        @param   logger   Reference to Logger instance.
        """
        threading.Thread.__init__(self)
        self.logger = logger
        self.buffer = self.logger.config.get_value('buffer_size')
        self._running = True
        
    def run(self):
        """
        Start the thread. Loop over the device pool at a regular interval and
        delete devices that have not been seen since x amount of time. Write
        them to the logfile as being moved 'out'.
        """
        while self._running:
            tijd = int(time.time())
            #print tijd, ", checked"
            to_delete = []
            for device in self.logger.pool:
                if tijd - self.logger.pool[device][0] > self.buffer:
                    self.logger.write(self.logger.pool[device][0],
                                      device,
                                      self.logger.pool[device][1],
                                      'out')
                    to_delete.append(device)
            for device in to_delete:
                del(self.logger.pool[device])
            time.sleep(self.buffer)
            
    def stop(self):
        """
        Stop the thread.
        """
        self._running = False
