#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
# Copyright (C) 2009-2011  Roel Huybrechts
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
import subprocess
import sys
import threading
import time

import configuration
import discoverer
import logger
import network

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
        self.startup_time = int(time.time())
        self.active_adapters = []

        self.config = configuration.Configuration(self, self.main.configfile)
        self.info_logger = logger.InfoLogger(self, self.get_info_log_location())
        self.time_format = self.config.get_value('time_format')
        self.excluded_devices = self.config.get_value('excluded_devices')

    def init(self):
        """
        Full initialisation. Initialise everything, called when the program is
        starting up.
        """
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        dbus.mainloop.glib.threads_init()
        self._dbus_systembus = dbus.SystemBus()

        if len(self.config.get_value('network_server_host')) > 0:
            dir = os.path.dirname(os.path.abspath(__file__))
            m_path = dir[:dir.rfind('/')] + '/network_middleware.py'
            if not os.path.isfile(m_path):
                m_path = '/usr/share/gyrid/network_middleware.py'

            self.network_middleware = subprocess.Popen(
                ["/usr/bin/python", m_path])
            time.sleep(2)

            self.network = network.Network(self)

        if self.config.get_value('minimum_rssi') != None:
            self.log_info("Using a minimum RSSI value of %i, " % \
                self.config.get_value('minimum_rssi') + \
                "detections with a lower RSSI value are ignored")

        self.loggers = {}

        bluez_obj = self._dbus_systembus.get_object('org.bluez', '/')
        self._dbus_bluez_manager = dbus.Interface(bluez_obj,
            'org.bluez.Manager')

        self._dbus_systembus.add_signal_receiver(self._bluetooth_adapter_added,
            bus_name = "org.bluez",
            signal_name = "AdapterAdded")

    def net_send_line(self, line):
        """
        Try to send the given line over the socket to the Gyrid networking
        component via the network module. This is failsafe, also when networking
        support is disabled.

        @param   line   The line to send.
        """
        if 'network' in self.__dict__:
            self.network.send_line(line)

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
            d = {'time': time.strftime(self.config.get_value('time_format')),
                 'extra_time': time.strftime(extra_time),
                 'message': message}
            sys.stdout.write("%(time)s%(extra_time)s Gyrid: %(message)s.\n" % d)

    def makedirs(self, path, mode=0755):
        """
        Create directories recursively. Only creates path if it doesn't exist
        yet.

        @param  path   The path to be created.
        @param  mode   The permissions used to create the directories.
        """
        if not os.path.exists(path):
            os.makedirs(path, mode)

    def is_excluded(self, dev_id, mac):
        """
        Check if the given device is excluded from scanning.

        @param  dev_id   The device ID of the Bluetooth adapter.
                            F. ex.: 0 in the case of hci0
        @param  mac      The MAC-address of the device.
        """
        if dev_id in self.excluded_devices:
            self.log_info("Ignoring Bluetooth adapter %s (excluded)" % mac)
            return True
        else:
            return False

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

class DefaultScanManager(ScanManager):
    def __init__(self, main):
        self.base_location = '/var/log/gyrid/'
        self.makedirs(self.base_location)
        ScanManager.__init__(self, main)

    def get_scan_log_location(self, mac):
        mac = mac.replace(':','')
        self.makedirs(self.base_location + mac)
        return self.base_location + mac + '/scan.log'

    def get_rssi_log_location(self, mac):
        mac = mac.replace(':','')
        self.makedirs(self.base_location + mac)
        return self.base_location + mac + '/rssi.log'

    def get_info_log_location(self):
        return self.base_location + 'messages.log'

    def _bluetooth_adapter_added(self, path=None):
        adapter = ScanManager._bluetooth_adapter_added(self, path)
        dev_id = int(str(path).split('/')[-1].strip('hci'))
        addr = adapter.GetProperties()['Address']
        if not self.is_excluded(dev_id, addr):
            adapter.SetProperty('Discoverable', False)
            self._start_discover(adapter, dev_id)

    def run(self):
        for adapter in self._dbus_bluez_manager.ListAdapters():
            adap_obj = self._dbus_systembus.get_object('org.bluez', adapter)
            adap_iface = dbus.Interface(adap_obj, 'org.bluez.Adapter')
            dev_id = int(str(adapter).split('/')[-1].strip('hci'))
            addr = adap_iface.GetProperties()['Address']
            self.debug("Found Bluetooth adapter with address %s" % addr)
            if not self.is_excluded(dev_id, addr):
                adap_iface.SetProperty('Discoverable', False)
                time.sleep(0.1)
                self._start_discover(adap_iface, dev_id)

    def _dev_prop_changed(self, property, value, path):
        """
        Called if the properties of the scandevice have changed. In casu
        it is used to listen for the Discovering=False signal to restart
        scanning.
        """
        if property == "Discovering" and \
                value == False:
            adap_obj = self._dbus_systembus.get_object('org.bluez', path)
            adap_iface = dbus.Interface(adap_obj, 'org.bluez.Adapter')
            dev_id = int(str(path).split('/')[-1].strip('hci'))
            addr = adap_iface.GetProperties()['Address']
            if addr not in self.active_adapters \
                and not self.is_excluded(dev_id, addr):
                self._start_discover(adap_iface, dev_id)

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
            if device.GetProperties()['Discovering']:
                if address in self.active_adapters:
                    self.active_adapters.remove(address)
                self.debug("Adapter %s is still discovering, " % address + \
                    "waiting for the scan to end")
                device.connect_to_signal("PropertyChanged",
                    self._dev_prop_changed, path_keyword='path')
            else:
                self.active_adapters.append(address)
                if address not in self.loggers:
                    _logger = logger.ScanLogger(self, address)
                    _logger_rssi = logger.RSSILogger(self, address)
                    self.loggers[address] = [_logger, _logger_rssi]
                else:
                    _logger = self.loggers[address][0]
                    _logger_rssi = self.loggers[address][1]
                _discoverer = discoverer.Discoverer(self, _logger, _logger_rssi,
                    device_id, address)

                if _discoverer.init() == 0:
                    self.log_info("Started scanning with adapter %s" % address)
                    _logger.start()
                    end_cause = _discoverer.find()
                    self.log_info("Stopped scanning with adapter %s%s" % \
                        (address, end_cause))
                if address in self.active_adapters:
                    self.active_adapters.remove(address)
                del(_discoverer)
