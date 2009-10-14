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
import dbus
import dbus.mainloop.glib
import os
import sys
import threading
import time

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
        @param  debug_mode   Whether to use debug mode.
        """
        self.main = main
        self.debug_mode = debug_mode

        self.config = configuration.Configuration(self, self.main.configfile)
        self.info_logger = logger.Logger(self, 'info')

        self.time_format = self.config.get_value('time_format')

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._dbus_systembus = dbus.SystemBus()
        bluez_obj = self._dbus_systembus.get_object('org.bluez', '/')
        self._dbus_bluez_manager = dbus.Interface(bluez_obj, 'org.bluez.Manager')

        self._dbus_systembus.add_signal_receiver(self._bluetooth_adapter_added,
            bus_name = "org.bluez",
            signal_name = "AdapterAdded")
            
    def _bluetooth_adapter_added(self, path=None):
        """
        Called automatically when a Bluetooth adapter is added to the system.

        @param  path   The path of the adapter, as specified by DBus.
        """
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
            extra_time = ""
            if False in [i in self.time_format for i in ['%H', '%M', '%S']]:
                extra_time = " (%H:%M:%S)"
            sys.stderr.write("%s%s Gyrid: %s.\n" % \
                (time.strftime(self.config.get_value('time_format')), 
                time.strftime(extra_time), message))

    def makedirs(self, path, mode=0755):
        """
        Create directories recursively. Only creates path if it doesn't exist
        yet.

        @param  path   The path to be created.
        @param  mode   The rights used to create the directories.
        """
        if not os.path.exists(path):
            os.makedirs(path, mode)

    def log_info(self, message):
        """
        Write messages to the info log.

        @param  message   The message to write.
        """
        self.debug(message)
        self.info_logger.write_info(message)

    def get_log_location(self, mac):
        """
        Get the location of the logfile based on the MAC-address of the Bluetooth
        adapter. Make sure to implement the case where mac=='info' representing
        the logger that logs status messages.

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

    def get_log_location(self, mac):
        base = '/var/log/gyrid/serial/'
        self.makedirs(base)
        
        if mac == 'info':
            return base + 'messages.log'
        else:
            return base + 'scan.log'

    def _bluetooth_adapter_added(self, path=None):
        adapter = ScanManager._bluetooth_adapter_added(self, path)
        adapter.SetProperty('Discoverable', False)
        self.scan_with_default()

    def run(self):
        for adapter in self._dbus_bluez_manager.ListAdapters():
            adap_obj = self._dbus_systembus.get_object('org.bluez', adapter)
            adap_iface = dbus.Interface(adap_obj, 'org.bluez.Adapter')
            adap_iface.SetProperty('Discoverable', False)
            self.debug("Found Bluetooth adapter with address %s (%s)" %
                (adap_iface.GetProperties()['Address'],
                 str(adapter).split('/')[-1]))

        self.scan_with_default()

    def scan_with_default(self):
        try:
            if not 'discoverer' in self.__dict__:
                default_adap_path = self._dbus_bluez_manager.DefaultAdapter()
                device_obj = self._dbus_systembus.get_object("org.bluez",
                    default_adap_path)
                default_adap_iface = dbus.Interface(device_obj,
                    "org.bluez.Adapter")
        except dbus.DBusException:
            #No adapter found
            pass
        else:
            self._start_discover(default_adap_iface,
                int(str(default_adap_path).split('/')[-1].strip('hci')))

    def stop(self):
        self.info_logger.stop()

    def _dev_prop_changed(self, property, value):
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
        if device.GetProperties()['Discovering']:
            self.debug("Adapter %s (%s) is still discovering, waiting for the scan to end" % \
                (device.GetProperties()['Address'],
                 str(device).split('/')[-1]))
            device.connect_to_signal("PropertyChanged", self._dev_prop_changed)
        else:
            _logger = logger.Logger(self, device.GetProperties()['Address'])
            self.discoverer = discoverer.Discoverer(self, _logger, device_id)
            address = device.GetProperties()['Address']
            
            self.debug("Started scanning with adapter %s (%s)" %
                (address, 'hci%i' % device_id))
            _logger.write_info('I: Started scanning with %s' % address)
            _logger.start()
            while not self.discoverer.done:
                try:
                    self.discoverer.process_event()
                except bluetooth._bluetooth.error, e:
                    if e[0] == 32:
                        self.debug("Bluetooth adapter %s (%s) lost" %
                            (address, 'hci%i' % device_id))
                        _logger.write_info("E: Bluetooth adapter %s lost" %
                            address)
                        _logger.stop()
                        self.discoverer.done = True
            self.log_info("Stopped scanning")
            del(self.discoverer)
            self.scan_with_default()


class ParallelScanManager(ScanManager):
    def __init__(self, main, debug_mode):
        ScanManager.__init__(self, main, debug_mode)

    def get_log_location(self, mac):
        base = '/var/log/gyrid/parallel/'
        self.makedirs(base)

        if mac == 'info':
            return base + 'messages.log'
        else:
            self.makedirs(base + mac)
            return base + '%s/scan.log' % mac

    def run(self):
        for adapter in self._dbus_bluez_manager.ListAdapters():
            adap_obj = self._dbus_systembus.get_object('org.bluez', adapter)
            adap_iface = dbus.Interface(adap_obj, 'org.bluez.Adapter')
            adap_iface.SetProperty('Discoverable', False)
            adap_mac = adap_iface.GetProperties()['Address']
            self.debug("Found Bluetooth adapter with address %s" % adap_mac)
            self._start_discover(adap_iface, int(str(adapter).split('/')[-1].strip('hci')))

    def _bluetooth_adapter_added(self, path=None):
        device = ScanManager._bluetooth_adapter_added(self, path)
        self._start_discover(device, int(str(path).split('/')[-1].strip('hci')))

    def stop(self):
        pass

    @threaded
    def _start_discover(self, device, device_id):
        """
        Start the Discoverer and start scanning. Start the logger in order to
        get the pool_checker running. This function is decorated to start in
        a new thread automatically. The scan ends if there is no Bluetooth
        device (anymore).
        
        @param  device_id   The device to use for scanning.
        """
        address = device.GetProperties()['Address']
        if address != '00:00:00:00:00:00':
            _logger = logger.Logger(self, address)
            if device.GetProperties()['Discovering']:
                self.debug("Adapter %s (%s) is still discovering, waiting for the scan to end" % \
                    (self.default_adap_iface.GetProperties()['Address'],
                     str(self.default_adap_path).split('/')[-1]))
                #device.connect_to_signal("PropertyChanged", self._dev_prop_changed)
            else:
                _discoverer = discoverer.Discoverer(self, _logger, device_id)

                self.log_info("Started scanning with adapter %s" % address)
                _logger.start()
                while not _discoverer.done:
                    try:
                        _discoverer.process_event()
                    except bluetooth._bluetooth.error, e:
                        if e[0] == 32:
                            _logger.stop()
                            _discoverer.done = True
                self.log_info("Stopped scanning with adapter %s" % address)
            del(_discoverer)
