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
import logger
import daemon

class Main(daemon.Daemon):
    """
    Main class of the Bluetooth tracker; subclass of daemon for easy
    daemonising.
    """
    def __init__(self, lockfile, logfile, configfile):
        """
        Initialistation of the daemon, threading, logging and DBus connection.

        @param  lockfile      URL of the lockfile.
        @param  logfile       URL of the logfile.
        @param  configfile    URL of the configfile.
        """
        daemon.Daemon.__init__(self, lockfile, stdout='/dev/stdout',
                               stderr='/dev/stderr')
                              
        gobject.threads_init()
        self.logger = logger.Logger(logfile, configfile)
        self.main_loop = gobject.MainLoop()
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._dbus_systembus = dbus.SystemBus()
        hal_obj = self._dbus_systembus.get_object(
            'org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
        self._dbus_hal = dbus.Interface(hal_obj, 'org.freedesktop.Hal.Manager')

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

        self._dbus_systembus.add_signal_receiver(self._bluetooth_device_added,
            "DeviceAdded",
            "org.freedesktop.Hal.Manager",
            "org.freedesktop.Hal",
            "/org/freedesktop/Hal/Manager")

        self._start_discover()
        self.main_loop.run()

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
                self.logger.write_info("I: Bluetooth receiver found")
                self._start_discover()
        except dbus.DBusException:
            #Raised when no such property exists.
            pass

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
        daemon.Daemon.stop(self)
