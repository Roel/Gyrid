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

import os
import threading
import bluetooth

import logger
import discoverer

class ScanDevice(object):
    """
    Class representing a Bluetooth device attached to the computer that can be
    used as a scanner.
    """
    def __init__(self, device, bluetracker):
        """
        Initialisation.
        """
        self.main = bluetracker
        
        self.mac_address = ":".join([("%012x" % int(device.GetProperty(
            'bluetooth_hci.address')))[a:a+2] for a in range(0, 12, 2)])
        print self.mac_address
        
        self.logger = logger.Logger(os.path.join(self.main.logdir,
            '%s.log' % self.mac_address))
            
    def _threaded(f):
        """
        Wrapper to start a function within a new thread.

        @param  f   The function to run inside the thread.
        """
        def wrapper(*args):
            t = threading.Thread(target=f, args=args)
            t.start()
        return wrapper
            
    def run(self, restart=False):
        """
        Called after the daemon gets the (re)start command.
        Connect the DeviceAdded signal (DBus/HAL) to its handler and start
        the Bluetooth discoverer.
        """
        if not restart:
            self.logger.write_info("I: Started")
        else:
            self.logger.write_info("I: Restarted")

        self._start_discover()
        
    def resume(self):
        """
        Called after the device has been plugged in again.
        """
        if not discoverer in self.__dict__:
            self.logger.write_info("I: Bluetooth receiver found")
            self._start_discover()
        
    @_threaded
    def _start_discover(self):
        """
        Start the Discoverer and start scanning. Start the logger in order to
        get the pool_checker running. This function is decorated to start in
        a new thread automatically. The scan ends if there is no Bluetooth
        device (anymore).
        """
        try:
            self.discoverer = discoverer.Discoverer(self.logger)
        except bluetooth.BluetoothError:
            #No Bluetooth receiver found, return to end the function.
            #We will automatically start again after a Bluetooth device
            #has been plugged in thanks to HAL signal receiver.
            return

        self.logger.start()
        while not self.discoverer.done:
            try:
                self.discoverer.process_event()
            except bluetooth._bluetooth.error, e:
                if e[0] == 32:
                    #The Bluetooth receiver has been plugged out, end the loop.
                    #We will automatically start again after a Bluetooth device
                    #has been plugged in thanks to HAL signal receiver.
                    self.logger.write_info("E: Bluetooth receiver lost")
                    self.logger.stop()
                    self.discoverer.done = True
        del(self.discoverer)
        
    def stop(self, restart=False):
        """
        Called when the daemon gets the stop command. Stop the logger, cleanly
        close the logfile if restart=False and then stop the daemon.
        
        @param  restart   If this call to stop() is part of a restart operation.
        """
        if not restart:
            self.logger.write_info("I: Stopped")
            self.logger.close()
        else:
            self.logger.stop()
