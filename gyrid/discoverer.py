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

import bluetooth
import time

class Discoverer(bluetooth.DeviceDiscoverer):
    """
    Bluetooth discover, this is the device scanner. A few modification have
    been made from the original DeviceDiscoverer.
    """
    def __init__(self, mgr, device_id):
        """
        Initialisation of the DeviceDiscoverer. Store the reference to logger
        and start scanning.

        @param  logger  Reference to a Logger instance.
        """
        # We need a patched version of Pybluez where one can specify a 
        # device_id when initialising a DeviceDiscoverer. Patch is available
        # at Pybluez's code.google.com as issue 18.
        bluetooth.DeviceDiscoverer.__init__(self, device_id)
        
        self.mgr = mgr
        self.logger = self.mgr.logger
        self.find()

    def find(self):
        """
        Start scanning.
        """
        self.find_devices(flush_cache=True, lookup_names=False, duration=8)

    def pre_inquiry(self):
        """
        Set the 'done' flag to False when starting the scan.
        """
        self.done = False

    def device_discovered(self, address, device_class, name):
        """
        Called when discovered a device. Get a UNIX timestamp and call the
        update method of Logger to update the timestamp, the address and
        the device_class of the device in the pool.

        @param  address        Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  name           The name of the Bluetooth device. Since we don't
                                query names, this value will be None.
        """
        timestamp = time.time()
        
        if self.mgr.debug_mode:
            import tools.deviceclass
            import tools.macvendor

            device = ', '.join([str(tools.deviceclass.get_major_class(device_class)),
                     str(tools.deviceclass.get_minor_class(device_class))])
            vendor = tools.macvendor.get_vendor(address)
        
            self.mgr.debug("Found device %(mac)s [%(dc)s (%(vendor)s)]" %
                {'mac': address, 'dc': device, 'vendor': vendor ,'time': str(timestamp)})
        
        self.logger.update_device(int(timestamp), address, device_class)

    def inquiry_complete(self):
        """
        Called after the inquiry is complete; restart scanning by calling
        find(). We create an endless loop here to continuously scan for
        devices.
        """
        self.mgr.debug("New inquiry")
        self.find()
