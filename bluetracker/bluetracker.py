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
import sys
import bluetooth
import dbus
import dbus.mainloop.glib
import time
import gobject
import threading

import daemon

class Main(daemon.Daemon):
    """
    Main class of the Bluetooth tracker; subclass of daemon for easy
    daemonising.
    """
    def __init__(self, lockfile, logfile):
        """
        Initialistation of the daemon and opening of the logfile.

        @param  lockfile   URL of the lockfile.
        @param  logfile    URL of the logfile.
        """
        daemon.Daemon.__init__(self, lockfile, stdout='/dev/stdout',
                               stderr='/dev/stderr')
        self.logfile_url = logfile
        self.logfile = open(self.logfile_url, 'a')

        self.main_loop = gobject.MainLoop()
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._dbus_systembus = dbus.SystemBus()
        hal_obj = self._dbus_systembus.get_object(
            'org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
        self._dbus_hal = dbus.Interface(hal_obj, 'org.freedesktop.Hal.Manager')

    def threaded(f):
        """
        Wrapper to start a function within a new thread.

        @param  f   The function to run inside the thread.
        """
        def wrapper(*args):
            t = threading.Thread(target=f, args=args)
            t.start()
        return wrapper

    def write(self, timestamp, mac_address, device_class):
        """
        Append the parameters to the logfile on a new line and flush the file.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        """
        self.logfile.write(",".join([str(timestamp),
                                     str(mac_address),
                                     str(device_class)]))
        self.logfile.write("\n")
        self.logfile.flush()

    def write_info(self, info):
        """
        Append a timestamp and the information to the logfile on a new line
        and flush the file.

        @param  info   The information to write.
        """
        tijd = str(time.time())
        self.logfile.write(",".join([tijd[:tijd.find('.')], info]))
        self.logfile.write("\n")
        self.logfile.flush()

    def run(self):
        """
        Called after the daemon gets the (re)start command
        Open the logfile if it's not already open (necessary to be able to
        restart the daemon), and start the Bluetooth discoverer.
        """
        #Check for Bluetooth device.
        #if len(self._dbus_hal.FindDeviceByCapability('bluetooth_hci')) < 1:
            #sys.stderr.write("Error: no Bluetooth device found.\n")
            #sys.exit(1)

        if 'logfile' not in self.__dict__:
            self.logfile = open(self.logfile_url, 'a')
            self.write_info("I: Restarted")
        else:
            self.write_info("I: Started")

        self._dbus_systembus.add_signal_receiver(self._bluetooth_device_added,
            "DeviceAdded",
            "org.freedesktop.Hal.Manager",
            "org.freedesktop.Hal",
            "/org/freedesktop/Hal/Manager")

        gobject.threads_init()
        self.start_discover()
        self.main_loop.run()

    @threaded
    def start_discover(self):
        """
        Start the Discoverer and start scanning. This function is decorated
        to start in a new thread automatically. The scan ends if there is no
        Bluetooth device (anymore).
        """
        try:
            self.discoverer = Discoverer(self)
        except bluetooth.BluetoothError:
            #No Bluetooth receiver found, return to end the function.
            #We will automatically start again after a Bluetooth device
            #has been plugged in thanks to HAL signal receiver.
            return

        while not self.discoverer.done:
            try:
                self.discoverer.process_event()
            except bluetooth._bluetooth.error, e:
                if e[0] == 32:
                    #The Bluetooth receiver has been plugged out, end the loop.
                    #We will automatically start again after a Bluetooth device
                    #has been plugged in thanks to HAL signal receiver.
                    self.write_info("E: Bluetooth receiver lost")
                    self.discoverer.done = True
        del(self.discoverer)

    def _bluetooth_device_added(self, sender=None):
        """
        Callback function for HAL signal. This method is automatically called
        after a new hardware device has been plugged in. We check if is has
        Bluetooth capabilities, and start scanning if it does.

        @param  sender   The device that has been plugged in.
        """
        device_obj = self._dbus_systembus.get_object("org.freedesktop.Hal", sender)
        device = dbus.Interface(device_obj, "org.freedesktop.Hal.Device")
        try:
            if ('bluetooth_hci' in device.GetProperty('info.capabilities')) and \
               (not 'discoverer' in self.__dict__):
                self.write_info("I: Bluetooth receiver found")
                self.start_discover()
        except dbus.DBusException:
            #Raised when no such property exists.
            pass

    def stop(self, restart=False):
        """
        Called when the daemon gets the stop command. Cleanly close the
        logfile and then stop the daemon.
        """
        if not restart:
            self.write_info("I: Stopped")
        self.logfile.close()
        del(self.logfile)
        daemon.Daemon.stop(self)

class Discoverer(bluetooth.DeviceDiscoverer):
    """
    Bluetooth discover, this is the device scanner. A few modification have
    been made from the original DeviceDiscoverer.
    """
    def __init__(self, main):
        """
        Initialisation of the DeviceDiscoverer. Store the reference to main and
        start scanning.

        @param  main  Reference to a Main instance.
        """
        bluetooth.DeviceDiscoverer.__init__(self)
        self.main = main
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
        Called when discovered a new device. Get a UNIX timestamp and call
        the write method of Main to write the timestamp, the address and
        the device_class of the device to the logfile.

        @param  address        Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  name           The name of the Bluetooth device. Since we don't
                                query names, this value will be None.
        """
        tijd = str(time.time())
        self.main.write(tijd[:tijd.find('.')], address, device_class)

    def inquiry_complete(self):
        """
        Called after the inquiry is complete; restart scanning by calling
        find(). We create an endless loop here to continuously scan for
        devices.
        """
        self.find()
