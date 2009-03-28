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

import bluetooth
import dbus
import dbus.mainloop.glib
import gobject
import threading

import discoverer
#import logger
import daemon
import scandevice

class Main(daemon.Daemon):
    """
    Main class of the Bluetooth tracker; subclass of daemon for easy
    daemonising.
    """
    def __init__(self, lockfile, logdir):
        """
        Initialistation of the daemon, threading, logging and DBus connection.

        @param  lockfile   URL of the lockfile.
        @param  logdir     URL of the logfile directory.
        """
        daemon.Daemon.__init__(self, lockfile, stdout='/dev/stdout',
                               stderr='/dev/stderr')
         
        gobject.threads_init()
        self.logdir = logdir
        self.main_loop = gobject.MainLoop()
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.dbus_systembus = dbus.SystemBus()
        hal_obj = self.dbus_systembus.get_object(
            'org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
        self._dbus_hal = dbus.Interface(hal_obj, 'org.freedesktop.Hal.Manager')

        #Build list of Bluetooth devices
        self.bluetooth_scanners = {}
        for item in self._dbus_hal.FindDeviceByCapability('bluetooth_hci'):
            device_obj = self.dbus_systembus.get_object("org.freedesktop.Hal", item)
            device = scandevice.ScanDevice(dbus.Interface(
                device_obj, "org.freedesktop.Hal.Device"), self)
            
            self.bluetooth_scanners[device.mac_address] = device

    def run(self, restart=False):
        """
        Called after the daemon gets the (re)start command.
        Connect the DeviceAdded signal (DBus/HAL) to its handler and start
        the Bluetooth discoverer.
        """
        for scanner in self.bluetooth_scanners.values():
            scanner.run(restart)

        self.dbus_systembus.add_signal_receiver(self._bluetooth_device_added,
            "DeviceAdded",
            "org.freedesktop.Hal.Manager",
            "org.freedesktop.Hal",
            "/org/freedesktop/Hal/Manager")

        self.main_loop.run()

    def _bluetooth_device_added(self, sender=None):
        """
        Callback function for HAL signal. This method is automatically called
        after a new hardware device has been plugged in. We check if is has
        Bluetooth capabilities, and start scanning if it does.

        @param  sender   The device that has been plugged in.
        """
        device_obj = self.dbus_systembus.get_object("org.freedesktop.Hal", sender)
        device = dbus.Interface(device_obj, "org.freedesktop.Hal.Device")
        try:
            if 'bluetooth_hci' in device.GetProperty('info.capabilities'):
                mac =  ":".join([("%012x" % int(device.GetProperty('bluetooth_hci.address'))) \
                    [a:a+2] for a in range(0, 12, 2)])
                if not mac in self.bluetooth_scanners:
                    scanner = scandevice.ScanDevice(device, self)
                    self.bluetooth_scanners[mac] = scanner
                    scanner.run()
                else:
                    self.bluetooth_scanners[mac].resume()
        except dbus.DBusException:
            #Raised when no such property exists.
            pass

    def stop(self, restart=False):
        """
        Called when the daemon gets the stop command. Stop the logger, cleanly
        close the logfile if restart=False and then stop the daemon.
        
        @param  restart   If this call to stop() is part of a restart operation.
        """
        for scanner in self.bluetooth_scanners.values():
            scanner.stop(restart)
        daemon.Daemon.stop(self)
