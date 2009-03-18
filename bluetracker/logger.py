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

import gobject
import threading
import time

class Logger(object):
    def __init__(self, logfile):
        self.logfile = open(logfile, 'a')
        self.started = False
        
        #self._run_check = False
        self.pool = {}
        self.poolchecker = PoolChecker(self)
        
    def _threaded(f):
        """
        Wrapper to start a function within a new thread.

        @param  f   The function to run inside the thread.
        """
        def wrapper(*args):
            t = threading.Thread(target=f, args=args)
            t.start()
        return wrapper
        
    def write(self, timestamp, mac_address, device_class, moving):
        """
        Append the parameters to the logfile on a new line and flush the file.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
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
        if mac_address not in self.pool:
            self.write(timestamp, mac_address, device_class, 'in')
            
        self.pool[mac_address] = [timestamp, device_class]

    #@_threaded
    #def _check_pool(self):
    #    while self._run_check:
    #        tijd = int(time.time())
    #        print tijd, ", checked"
    #        to_delete = []
    #        for device in self._pool:
    #            if tijd - self._pool[device][0] > 120:
    #                self.write(self._pool[device][0],
    #                           device,
    #                           self._pool[device][1],
    #                           'out')
    #                to_delete.append(device)
    #        for device in to_delete:
    #            del(self._pool[device])
    #        time.sleep(300)
                    
    def start(self):
        #self._run_check = True
        #self._check_pool()
        if not 'poolchecker' in self.__dict__:
            self.poolchecker = PoolChecker(self)
        self.poolchecker.start()
        
    def stop(self):
        #self._run_check = False
        self.poolchecker.stop()
        del(self.poolchecker)
        
    def close(self):
        self.stop()
        self.logfile.close()
        
class PoolChecker(threading.Thread):
    def __init__(self, logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.buffer = 120
        self._running = True
        
    def run(self):
        while self._running:
            tijd = int(time.time())
            print tijd, ", checked"
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
        self._running = False
