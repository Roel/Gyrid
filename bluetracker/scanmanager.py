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
import threading
import time
import sys

import configuration
import discoverer
import logger

def threaded(f):
    """
    Wrapper to start a function within a new thread.

    @param  f   The function to run inside the thread.
    """
    def wrapper(*args):
        t = threading.Thread(target=f, args=args)
        t.start()
    return wrapper

class ScanManager(object):    
    def __init__(self, main, debug_mode):
        """
        Initialisation.
        
        @param  main   Reference to main instance.
        """
        self.main = main
        self.debug_mode = debug_mode
        
        self.config = configuration.Configuration(self, self.main.configfile)

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._dbus_systembus = dbus.SystemBus()
        bluez_obj = self._dbus_systembus.get_object('org.bluez', '/')
        self._dbus_bluez_manager = dbus.Interface(bluez_obj, 'org.bluez.Manager')
                
        self._dbus_systembus.add_signal_receiver(self._bluetooth_adapter_added,
            bus_name = "org.bluez",
            signal_name = "AdapterAdded")
            
    def _bluetooth_adapter_added(self, path=None):
        device_obj = self._dbus_systembus.get_object("org.bluez", path)
        device = dbus.Interface(device_obj, "org.bluez.Adapter")
        self.debug("Found Bluetooth adapter with address %s (%s)" %
                (device.GetProperties()['Address'],
                 str(path).split('/')[-1]))
        return device
        
    def debug(self, message):
        """
        Write message to stderr if debug mode is enabled.
        
        @param  message   The text to print.
        """
        if self.debug_mode:
            time_format = self.config.get_value('time_format')
            extra_time = ""
            if False in [i in time_format for i in '%H', '%M', '%S']:
                extra_time = " (%H:%M:%S)"
            sys.stderr.write("%s%s Bluetracker: %s.\n" % \
                (time.strftime(self.config.get_value('time_format')), 
                time.strftime(extra_time), message))
        
    def log_info(self, message):
        """
        Implement this method in a subclass.
        """
        raise NotImplementedError
                
    def run(self):
        """
        Implement this method in a subclass.
        """
        raise NotImplementedError

    def stop(self):
        """
        Implement this method in a subclass.
        """
        raise NotImplementedError


class SerialScanManager(ScanManager):
    def __init__(self, main, debug_mode):
        ScanManager.__init__(self, main, debug_mode)
        self.logger = logger.Logger(self, self.main.logfile)

    def log_info(self, message):
        self.logger.write_info(message)

    def _bluetooth_adapter_added(self, path=None):
        adapter = ScanManager._bluetooth_adapter_added(self, path)
        adapter.SetProperty('Discoverable', False)
        if not 'discoverer' in self.__dict__:
            self.logger.write_info("I: Bluetooth adapter found with address %s" %
                adapter.GetProperties()['Address'])
            self._start_discover(adapter,
                int(str(path).split('/')[-1].strip('hci')))
        
    def run(self):
        for adapter in self._dbus_bluez_manager.ListAdapters():
            adap_obj = self._dbus_systembus.get_object('org.bluez', adapter)
            adap_iface = dbus.Interface(adap_obj, 'org.bluez.Adapter')
            adap_iface.SetProperty('Discoverable', False)
            self.debug("Found Bluetooth adapter with address %s (%s)" %
                (adap_iface.GetProperties()['Address'],
                 str(adapter).split('/')[-1]))

        try:
            self.default_adap_path = self._dbus_bluez_manager.DefaultAdapter()
            device_obj = self._dbus_systembus.get_object("org.bluez",
                self.default_adap_path)
            self.default_adap_iface = dbus.Interface(device_obj, "org.bluez.Adapter")
        except DBusException:
            #No adapter found
            pass
        else:
            if self.default_adap_iface.GetProperties()['Discovering']:
                self.debug("Adapter %s (%s) is still discovering, waiting for the scan to end" % \
                    (self.default_adap_iface.GetProperties()['Address'],
                     str(self.default_adap_path).split('/')[-1]))
                self.default_adap_iface.connect_to_signal(
                    "PropertyChanged", self._device_prop_changed)
            else:
                self._start_discover(self.default_adap_iface,
                    int(str(self.default_adap_path).split('/')[-1].strip('hci')))

    def stop(self):
        self.logger.stop()

    def _device_prop_changed(self, property, value):
        """
        Called if the properties of the scandevice have changed. In casu
        it is used to listen for the Discovering=False signal to restart
        scanning.
        """
        if property == "Discovering" and \
                value == False and \
                'discoverer' not in self.__dict__:
            self._start_discover(self.default_adap_iface,
                int(str(self.default_adap_path).split('/')[-1].strip('hci')))

    @threaded
    def _start_discover(self, device, device_id):
        """
        Start the Discoverer and start scanning. Start the logger in order to
        get the pool_checker running. This function is decorated to start in
        a new thread automatically. The scan ends if there is no Bluetooth
        device (anymore).
        
        @param  device_id   The device to use for scanning.
        """
        self.discoverer = discoverer.Discoverer(self, device_id)
            
        address = device.GetProperties()['Address']
        
        self.debug("Started scanning with adapter %s (%s)" %
            (address, 'hci%i' % device_id))
        self.logger.write_info('I: Started scanning with %s' % address)
        self.logger.start()
        while not self.discoverer.done:
            try:
                self.discoverer.process_event()
            except bluetooth._bluetooth.error, e:
                if e[0] == 32:
                    #The Bluetooth adapter has been plugged out, end the loop.
                    #We will automatically start again after a Bluetooth adapter
                    #has been plugged in thanks to BlueZ signal receiver.
                    self.debug("Bluetooth adapter %s (%s) lost" %
                        (address, 'hci%i' % device_id))
                    self.logger.write_info("E: Bluetooth adapter %s lost" %
                        address)
                    self.logger.stop()
                    self.discoverer.done = True
        self.debug("Stopped scanning")
        del(self.discoverer)
