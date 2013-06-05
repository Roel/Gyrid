#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
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

"""
Module implementing the Bluetooth scanning functionality.
"""

import dbus
import dbus.mainloop.glib
import time

from gyrid import core, discoverer, logger


class Bluetooth(core.ScanProtocol):
    """
    Bluetooth protocol definition.
    """
    def __init__(self, mgr):
        """
        Initialisation.

        @param   mgr   Reference to ScanManager instance.
        """
        core.ScanProtocol.__init__(self, mgr)

        self.excluded_devices = self.mgr.config.get_value('excluded_devices')

        bluez_obj = self.mgr._dbus_systembus.get_object('org.bluez', '/')
        self._dbus_bluez_manager = dbus.Interface(bluez_obj,
            'org.bluez.Manager')

        self.mgr._dbus_systembus.add_signal_receiver(self.hardware_added,
            bus_name = "org.bluez",
            signal_name = "AdapterAdded")

        self.active_adapters = []
        self.loggers = {}
        self.scanners = {}

        self.initialise_hardware()

    def is_excluded(self, dev_id, mac):
        """
        Check if the given device is excluded from scanning.

        @param  dev_id   The device ID of the Bluetooth adapter.
                            F. ex.: 0 in the case of hci0
        @param  mac      The MAC-address of the device.
        """
        if dev_id in self.excluded_devices:
            self.mgr.log_info("Ignoring Bluetooth adapter %s (excluded)" % mac)
            return True
        else:
            return False

    def initialise_hardware(self):
        """
        Initialise the Bluetooth hardware already present on the system.
        """
        for adapter in self._dbus_bluez_manager.ListAdapters():
            adap_obj = self.mgr._dbus_systembus.get_object('org.bluez', adapter)
            adap_iface = dbus.Interface(adap_obj, 'org.bluez.Adapter')
            addr = adap_iface.GetProperties()['Address']
            self.mgr.debug("Found Bluetooth adapter with address %s" % addr)

            scanner = BluetoothScanner(self.mgr, self, adap_iface, adapter)
            self.scanners[scanner.mac] = scanner

    def hardware_added(self, path):
        """
        Called when a Bluetooth adapter is added to the system.

        @param  path   The path of the adapter, as specified by DBus.
        """
        device_obj = self.mgr._dbus_systembus.get_object("org.bluez", path)
        device = dbus.Interface(device_obj, "org.bluez.Adapter")
        self.mgr.debug("Found Bluetooth adapter with address %s" %
                device.GetProperties()['Address'])

        scanner = BluetoothScanner(self.mgr, self, device, path)
        self.scanners[scanner.mac] = scanner

class BluetoothScanner(core.Scanner):
    """
    Bluetooth scanner implementation.
    """
    def __init__(self, mgr, protocol, device, path):
        """
        Initialisation of a Bluetooth adapter for scanning.

        @param   mgr        Reference to ScanManager instance.
        @param   protocol   Reference to Bluetooth ScanProtocol.
        @param   device     BlueZ DBus interface of the Bluetooth device.
        @param   path       BlueZ DBus path of the Bluetooth device.
        """
        core.Scanner.__init__(self, mgr, protocol)
        self.mac = device.GetProperties()['Address']
        self.device = device
        self.dev_id = int(str(path).split('/')[-1].strip('hci'))

        if not self.protocol.is_excluded(self.dev_id, self.mac):
            device.SetProperty('Discoverable', False)
            self.start_scanning()

    def property_changed(self, property, value, path):
        """
        Called if the properties of the scandevice have changed. In casu
        it is used to listen for the Discovering=False signal to restart
        scanning.
        """
        if property == "Discovering" and \
                value == False:
            if self.mac not in self.active_adapters \
                and not self.protocol.is_excluded(self.dev_id, self.mac):
                self.start_scanning()

    @core.threaded
    def start_scanning(self):
        """
        Start the Discoverer and start scanning. Start the logger in order to
        get the pool_checker running. This function is decorated to start in
        a new thread automatically. The scan ends if there is no Bluetooth
        device (anymore).

        @param  device_id   The device to use for scanning.
        """
        self.mac
        if self.mac != '00:00:00:00:00:00':
            if self.device.GetProperties()['Discovering']:
                if self.mac in self.protocol.active_adapters:
                    self.protocol.active_adapters.remove(self.mac)
                self.mgr.debug("Adapter %s is still discovering, " % self.mac + \
                    "waiting for the scan to end")
                self.device.connect_to_signal("PropertyChanged",
                    self.property_changed, path_keyword='path')
            else:
                self.protocol.active_adapters.append(self.mac)
                if self.mac not in self.protocol.loggers:
                    _logger = logger.ScanLogger(self.mgr, self.mac)
                    _logger_rssi = logger.RSSILogger(self.mgr, self.mac)
                    _logger_inquiry = logger.InquiryLogger(self.mgr, self.mac)
                    self.protocol.loggers[self.mac] = (_logger, _logger_rssi, _logger_inquiry)
                else:
                    _logger, _logger_rssi, _logger_inquiry = self.protocol.loggers[self.mac]

                _discoverer = discoverer.Discoverer(self.mgr, _logger, _logger_rssi,
                    _logger_inquiry, self.dev_id, self.mac)

                if _discoverer.init() == 0:
                    self.mgr.log_info("Started scanning with Bluetooth adapter %s" % self.mac)
                    self.mgr.net_send_line("STATE,bluetooth,%s,%0.3f,started_scanning" % (
                        self.mac.replace(':',''), time.time()))
                    _logger.start()
                    end_cause = _discoverer.find()
                    _logger.stop()
                    self.mgr.log_info("Stopped scanning with Bluetooth adapter %s%s" % \
                        (self.mac, end_cause))
                    self.mgr.net_send_line("STATE,bluetooth,%s,%0.3f,stopped_scanning" % (
                        self.mac.replace(':',''), time.time()))

                if self.mac in self.protocol.active_adapters:
                    self.protocol.active_adapters.remove(self.mac)
                del(_discoverer)
