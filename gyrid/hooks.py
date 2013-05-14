#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
# Copyright (C) 2009-2013  Roel Huybrechts
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

import arduino

class Hooks(object):
    """
    This class provides hooks that are executed at various points in the
    device discovery cycle.
    """
    def __init__(self, mgr, discoverer):
        """
        Initialisation. Executed on discoverer initialisation.

        @param  mgr          Reference to the Scanmanager instance.
        @param  discoverer   Reference to the connected Discoverer instance.
        """
        self.mgr = mgr
        self.discoverer = discoverer

        self.arduino = arduino.Arduino(self.mgr, self.discoverer.mac)

    def pre_inquiry(self):
        """
        Executed before the start of each inquiry.
        """
        self.arduino.turn()

    def post_inquiry(self):
        """
        Executed after the end of each inquiry.
        """
        pass

    def device_discovered(self, address, device_class, rssi):
        """
        Executed when a Bluetooth device has been discovered.
        """
        self.arduino.write_log(address, device_class, rssi)

    def stop(self):
        """
        Executed when discovery process end.
        """
        self.arduino.stop()
