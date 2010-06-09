#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
# Copyright (C) 2009-2010  Roel Huybrechts
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
import re
import sys
import threading
import time

import configuration
import discoverer
import logger
import reporter

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
    def __init__(self, main):
        """
        Bare initialisation. Initialise only the necessary things in order to
        make a shutdown possible.

        @param  main   Reference to main instance.
        """
        self.main = main
        self.debug_mode = False
        self.debug_silent = False
        self.track_mode = None
        self.startup_time = int(time.time())

        self.config = configuration.Configuration(self, self.main.configfile)
        self.info_logger = logger.InfoLogger(self, self.get_info_log_location())
        self.time_format = self.config.get_value('time_format')

    def init(self):
        """
        Full initialisation. Initialise everything, called when the program is
        starting up.
        """
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._dbus_systembus = dbus.SystemBus()

        self.interactive_mode = \
            len(self.config.get_value('interacting_devices')) > 0
        if self.interactive_mode:
            self.reporter = reporter.Reporter(self)
            report_generator = reporter.ReportGenerator(self.reporter)
            self.stats_generator = reporter.StatsGenerator(report_generator)

        bluez_obj = self._dbus_systembus.get_object('org.bluez', '/')
        self._dbus_bluez_manager = dbus.Interface(bluez_obj, 'org.bluez.Manager')

        self._dbus_systembus.add_signal_receiver(self._bluetooth_adapter_added,
            bus_name = "org.bluez",
            signal_name = "AdapterAdded")

    def is_valid_mac(self, string):
        """
        Determine if the given string is a valid MAC-address.

        @param  string   The string to test.
        @return          The MAC-address if it is valid, else False.
        """
        string = string.strip().upper()
        if len(string) == 17 and \
            re.match("([0-F][0-F]:){5}[0-F][0-F]", string):
            return string
        else:
            return False

    def set_debug_mode(self, debug, silent):
        """
        Enable or disable debug mode.

        @param  debug   True to enable debug mode.
        @param  silent  True to enable silent (no logging) debug mode.
        """
        self.debug_mode = debug
        self.debug_silent = silent

    def set_track_mode(self, mac):
        """
        Enable or disable track mode.

        @param  mac    The MAC-address to track, None to disable track mode.
        """
        self.track_mode = self.is_valid_mac(mac)

    def _bluetooth_adapter_added(self, path=None):
        """
        Called automatically when a Bluetooth adapter is added to the system.

        @param  path   The path of the adapter, as specified by DBus.
        """
        device_obj = self._dbus_systembus.get_object("org.bluez", path)
        device = dbus.Interface(device_obj, "org.bluez.Adapter")
        self.debug("Found Bluetooth adapter with address %s" %
                device.GetProperties()['Address'])
        return device

    def debug(self, message, force=False):
        """
        Write message to stderr if debug mode is enabled.

        @param  message   The text to print.
        @param  force     Force printing even if debug mode is disabled.
        """
        if self.debug_mode or force:
            extra_time = ""
            if False in [i in self.time_format for i in ['%H', '%M', '%S']]:
                extra_time = " (%H:%M:%S)"
            sys.stdout.write("%s%s Gyrid: %s.\n" % \
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

    def get_scan_log_location(self, mac):
        """
        Get the location of the scan logfile based on the MAC-address of the
        Bluetooth adapter.

        Implement this method in a subclass.
        """
        raise NotImplementedError

    def get_rssi_log_location(self, mac):
        """
        Get the location of the RSSI logfile based on the MAC-address of the
        Bluetooth adapter.

        Implement this method in a subclass.
        """
        raise NotImplementedError

    def get_info_log_location(self):
        """
        Get the location of the logfile for informational messages.

        Implement this method in a subclass.
        """
        raise NotImplementedError

    def get_stats_location(self):
        """
        Get the location of the file used to store the statistics.

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
        Use this function in a subclass.

        Dims the lights on shutdown.
        """
        if self.config.get_value('alix_led_support') and \
                (False not in [os.path.exists('/sys/class/leds/alix:%i' % i) \
                for i in [1, 2, 3]]):

            for i in [2, 3]:
                file = open('/sys/class/leds/alix:%i/brightness' % i, 'w')
                file.write('0')
                file.close()

class SerialScanManager(ScanManager):
    def __init__(self, main):
        self.base_location = '/var/log/gyrid/serial/'
        self.makedirs(self.base_location)
        ScanManager.__init__(self, main)

    def get_scan_log_location(self, mac):
        return self.base_location + 'scan.log'

    def get_rssi_log_location(self, mac):
        return self.base_location + 'rssi.log'

    def get_info_log_location(self):
        return self.base_location + 'messages.log'

    def get_stats_location(self):
        return self.base_location + 'stats.txt'

    def _bluetooth_adapter_added(self, path=None):
        adapter = ScanManager._bluetooth_adapter_added(self, path)
        adapter.SetProperty('Discoverable', False)
        self.scan_with_default()

    def run(self):
        for adapter in self._dbus_bluez_manager.ListAdapters():
            adap_obj = self._dbus_systembus.get_object('org.bluez', adapter)
            adap_iface = dbus.Interface(adap_obj, 'org.bluez.Adapter')
            adap_iface.SetProperty('Discoverable', False)
            self.debug("Found Bluetooth adapter with address %s" %
                adap_iface.GetProperties()['Address'])

        self.scan_with_default()

    def scan_with_default(self):
        if not 'discoverer' in self.__dict__:
            try:
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
        ScanManager.stop(self)

    def _dev_prop_changed(self, property, value):
        """
        Called if the properties of the scandevice have changed. In casu
        it is used to listen for the Discovering=False signal to restart
        scanning.
        """
        if property == "Discovering" and \
                value == False and \
                'discoverer' not in self.__dict__:
            self.scan_with_default()

    @threaded
    def _start_discover(self, device, device_id):
        """
        Start the Discoverer and start scanning. Start the logger in order to
        get the pool_checker running. This function is decorated to start in
        a new thread automatically. The scan ends if there is no Bluetooth
        device (anymore).

        @param  device_id   The device to use for scanning.
        """
        addr = device.GetProperties()['Address']
        if device.GetProperties()['Discovering']:
            self.debug("Adapter %s is still discovering, waiting " % addr + \
                "for the scan to end")
            device.connect_to_signal("PropertyChanged", self._dev_prop_changed)
        else:
            _logger = logger.ScanLogger(self, addr)
            _logger_rssi = logger.RSSILogger(self, addr)
            self.discoverer = discoverer.Discoverer(self, _logger,
                _logger_rssi, device_id)
            if self.discoverer.init() == 0:
                self.log_info("Started scanning with %s" % addr)
                _logger.start()
                end_cause = self.discoverer.find()
                self.log_info("Stopped scanning with %s%s" % (addr, end_cause))
            del(self.discoverer)
            self.scan_with_default()


class ParallelScanManager(ScanManager):
    def __init__(self, main):
        self.base_location = '/var/log/gyrid/parallel/'
        self.makedirs(self.base_location)
        ScanManager.__init__(self, main)

    def get_scan_log_location(self, mac):
        self.makedirs(self.base_location + mac)
        return self.base_location + '%s/scan.log' % mac

    def get_info_log_location(self):
        return self.base_location + 'messages.log'

    def get_stats_location(self):
        return self.base_location + 'stats.txt'

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
        ScanManager.stop(self)

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
                end_cause = ""
                while not _discoverer.done:
                    try:
                        _discoverer.process_event()
                    except bluetooth._bluetooth.error, e:
                        if e[0] == 32:
                            _logger.stop()
                            _discoverer.done = True
                            end_cause = " (adapter lost)"
                self.log_info("Stopped scanning with adapter %s%s" % (address, end_cause))
            del(_discoverer)
