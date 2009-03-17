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
    
        self._run_check = False
        self._pool = {}
        
        #gobject.threads_init()
        
    def _threaded(f):
        """
        Wrapper to start a function within a new thread.

        @param  f   The function to run inside the thread.
        """
        def wrapper(*args):
            t = threading.Thread(target=f, args=args)
            t.start()
        return wrapper
        
    def _write(self, timestamp, mac_address, device_class, moving):
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
            self._write(timestamp, mac_address, deviceclass, 'in')
            
        self._pool[mac_address] = [timestamp, device_class]

    @_threaded
    def _check_pool(self):
        while self._run_check:
            tijd = int(time.time())
            print tijd, ", checked"
            for device in self._pool:
                if tijd - self._pool[device][0] <= 120:
                    self._write(self._pool[device][0],
                                device,
                                self._pool[device][1],
                                'out')
                    del(self._pool[device])
            time.sleep(300)
            
    def stop(self):
        self._run_check = False
        
    def start(self):
        self._run_check = True
        self._check_pool()
        
    def close(self):
        self.stop()
        self.logfile.close()
