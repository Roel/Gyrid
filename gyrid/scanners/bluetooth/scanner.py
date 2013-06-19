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

import copy
import dbus
import dbus.mainloop.glib
import math
import time
from threading import Timer
import sys

from gyrid import arduino, core
import discoverer
import logger

class ScanPattern(object):
    def __init__(self, mgr, scanner,
            sensor_mac = None,
            start_time = None,
            stop_time = None,
            start_angle = 0,
            stop_angle = 0,
            scan_angle = 0,
            inquiry_length = None,
            buffer_time = 0,
            turn_resolution = 0):
        self.mgr = mgr
        self.scanner = scanner
        self.sensor_mac = sensor_mac
        self.start_time = start_time
        self.stop_time = stop_time
        self.start_angle = start_angle
        self.stop_angle = stop_angle
        self.scan_angle = scan_angle
        self.inquiry_length = inquiry_length
        self.buffer_time = buffer_time
        self.turn_resolution = turn_resolution

        self.waiting_time = 10

        if not self.inquiry_length:
            self.inquiry_length = int(math.ceil(self.mgr.config.get_value('buffer_size')/1.28))

        self.inquiry_duration = 1.28*self.inquiry_length

        self.done = False
        self.scan_direction_up = self.stop_angle >= self.start_angle
        self.pattern_finished = True

        self.angle_current_idx = 0
        if stop_angle != start_angle:
            self.angle_startpoints = range(start_angle, stop_angle, (stop_angle-start_angle)/turn_resolution)
        else:
            self.angle_startpoints = []
        self.angle_startpoints.append(stop_angle)
        print self.angle_startpoints

        i = 0
        scan_around_startpoint_instead_of_from_startpoint = abs(self.stop_angle-self.start_angle) != self.turn_resolution*self.scan_angle
        while i < len(self.angle_startpoints):
            if 0 < i < len(self.angle_startpoints)-1 and scan_around_startpoint_instead_of_from_startpoint:
                if self.scan_direction_up:
                    self.angle_startpoints[i] = self.angle_startpoints[i]-self.scan_angle/2
                else:
                    self.angle_startpoints[i] = self.angle_startpoints[i]+self.scan_angle/2
            elif i == len(self.angle_startpoints)-1:
                if scan_around_startpoint_instead_of_from_startpoint:
                    if self.scan_direction_up:
                        self.angle_startpoints[i] = self.angle_startpoints[i]-self.scan_angle
                    else:
                        self.angle_startpoints[i] = self.angle_startpoints[i]+self.scan_angle
                elif len(self.angle_startpoints) != 1:
                    del(self.angle_startpoints[i])
            i += 1

        print self.angle_startpoints
        self.pattern_duration = len(self.angle_startpoints)*(self.inquiry_duration+self.buffer_time)

    def __eq__(self, p):
        if p == None:
            return False

        eq = True
        eq = eq and self.sensor_mac == p.sensor_mac
        eq = eq and self.start_time == p.start_time
        eq = eq and self.stop_time == p.stop_time
        eq = eq and self.start_angle == p.start_angle
        eq = eq and self.stop_angle == p.stop_angle
        eq = eq and self.scan_angle == p.scan_angle
        eq = eq and self.inquiry_length == p.inquiry_length
        eq = eq and self.buffer_time == p.buffer_time
        eq = eq and self.turn_resolution == p.turn_resolution
        return eq

    def __ne__(self, p):
        return not self.__eq__(p)

    def __cmp__(self, p):
        if self.start_time == p.start_time and self.stop_time == p.stop_time:
            return 0

        if self.start_time == p.start_time:
            return 1 if self.stop_time > p.stop_time else -1

        return 1 if self.start_time > p.start_time else -1

    def stop(self):
        self.done = True

    def what_now(self, inquiry_function, args):
        t = time.time()

        if self.start_time and t < (self.start_time - self.waiting_time):
            st = self.waiting_time
            turntime = self.scanner.arduino.turn_time(self.angle_startpoints[0])
            if turntime and turntime < st:
                self.scanner.arduino.turn(self.angle_startpoints[0])
                st = st - turntime
            print "sleeping for %f seconds (waiting to start)" % st
            time.sleep(st)
        elif self.start_time and t < self.start_time:
            st = self.start_time - t
            turntime = self.scanner.arduino.turn_time(self.angle_startpoints[0])
            if turntime and turntime < st:
                self.scanner.arduino.turn(self.angle_startpoints[0])
                st = st - turntime
            print "sleeping for %f seconds (waiting to start)" % st
            time.sleep(st)
        elif (self.stop_time and (t <= self.stop_time or not self.pattern_finished)) or \
            not self.stop_time:
            if self.pattern_finished and self.start_time:
                st = self.pattern_duration - ((t-self.start_time) % self.pattern_duration)
                if self.pattern_duration-st <= 0.2:
                    print "diff %f" % (self.pattern_duration-st)
                    st = 0
                if st > 0:
                    if st > self.waiting_time:
                        st = self.waiting_time
                        turntime = self.scanner.arduino.turn_time(self.angle_startpoints[0])
                        if turntime and turntime < st:
                            self.scanner.arduino.turn(self.angle_startpoints[0])
                            st = st - turntime
                        print "sleeping for %f seconds (sync)" % st
                        time.sleep(st)
                        return
                    else:
                        turntime = self.scanner.arduino.turn_time(self.angle_startpoints[0])
                        if turntime and turntime < st:
                            self.scanner.arduino.turn(self.angle_startpoints[0])
                            st = st - turntime
                        if self.scan_angle > 0 and st > self.scanner.arduino.sweep_init_time:
                            st = st - self.scanner.arduino.sweep_init_time
                        elif self.scan_angle > 0 and st <= self.scanner.arduino.sweep_init_time:
                            st = 0
                        if st > 0:
                            print "sleeping for %f seconds (sync)" % st
                            time.sleep(st)

            new_angle = self.angle_startpoints[self.angle_current_idx]
            self.angle_current_idx += 1
            if self.angle_current_idx == len(self.angle_startpoints):
                self.angle_current_idx = 0
                self.pattern_finished = True
            else:
                self.pattern_finished = False
            self.scanner.arduino.turn(new_angle)
            if self.scan_angle > 0:
                if self.scan_direction_up:
                    self.scanner.arduino.sweep(new_angle, new_angle+self.scan_angle, self.inquiry_duration)
                else:
                    self.scanner.arduino.sweep(new_angle, new_angle-self.scan_angle, self.inquiry_duration)
            inquiry_function(*args)
            if self.buffer_time > 0:
                t = time.time()
                if not self.start_time:
                    self.start_time = 0
                if self.pattern_finished:
                    st = self.pattern_duration - ((t-self.start_time) % self.pattern_duration)
                else:
                    sti = (self.inquiry_duration+self.buffer_time) - ((t-self.start_time) % (self.inquiry_duration+self.buffer_time))
                    if sti < self.buffer_time:
                        st = sti
                    else:
                        st = self.buffer_time
                if st > self.waiting_time:
                    st = self.waiting_time
                turntime = self.scanner.arduino.turn_time(self.angle_startpoints[self.angle_current_idx])
                if turntime and turntime < st:
                    self.scanner.arduino.turn(self.angle_startpoints[self.angle_current_idx])
                    st = st - turntime
                if self.scan_angle > 0 and st > self.scanner.arduino.sweep_init_time:
                    st = st - self.scanner.arduino.sweep_init_time
                print "sleeping for %f seconds (sync + turn)" % st
                time.sleep(st)
        elif self.stop_time:
            self.done = True

class ScanPatternFactory(object):
    def __init__(self, mgr, protocol):
        self.mgr = mgr
        self.proctol = protocol

        self.default_scan_pattern = None

        self.patterns = []

    def make_patterns(self, scanner):
        r = []
        for p in self.patterns:
            if p.get('sensor_mac', scanner.mac) == scanner.mac:
                r.append(ScanPattern(self.mgr, scanner, **p))

        r.sort()
        for i in range(1, len(r)):
            if not r[i-1].stop_time or (r[i].start_time < r[i-1].stop_time + r[i-1].pattern_duration):
                r[i-1].stop_time = r[i].start_time - r[i-1].pattern_duration

        if len(r) == 0 and self.default_scan_pattern:
            r.append(ScanPattern(self.mgr, scanner, **self.default_scan_pattern))

        return set(r)

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

        self.scan_pattern_factory = ScanPatternFactory(self.mgr, self)

        self.active_adapters = []
        self.loggers = {}
        self.scanners = {}

        self.initialise_hardware()

    def is_excluded(self, path, mac):
        """
        Check if the given device is excluded from scanning.

        @param  mac      The MAC-address of the device.
        """
        dev_id = int(str(path).split('/')[-1].strip('hci'))
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

            if not self.is_excluded(adapter, addr):
                scanner = BluetoothScanner(self.mgr, self, adap_iface, adapter)
                self.scanners[scanner.mac] = scanner
                scanner.apply_scan_patterns(self.scan_pattern_factory.make_patterns(scanner))

                if scanner.available:
                    scanner.start()

    def hardware_added(self, path):
        """
        Called when a Bluetooth adapter is added to the system.

        @param  path   The path of the adapter, as specified by DBus.
        """
        device_obj = self.mgr._dbus_systembus.get_object("org.bluez", path)
        device = dbus.Interface(device_obj, "org.bluez.Adapter")
        self.mgr.debug("Found Bluetooth adapter with address %s" %
                device.GetProperties()['Address'])

        if not self.is_excluded(path, device.GetProperties()['Address']):
            scanner = BluetoothScanner(self.mgr, self, device, path)
            self.scanners[scanner.mac] = scanner
            scanner.apply_scan_patterns(self.scan_pattern_factory.make_patterns(scanner))

            if scanner.available:
                scanner.start()

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
        self.scan_patterns = set()
        self.current_pattern = None
        self.dev_id = int(str(path).split('/')[-1].strip('hci'))

        self.available = not self.device.GetProperties()['Discovering']
        if not self.available:
            self.mgr.debug("Adapter %s is still discovering, " % self.mac + \
                    "waiting for the scan to end")
            self.device.connect_to_signal("PropertyChanged",
                self.property_changed, path_keyword='path')
        else:
            self.protocol.active_adapters.append(self.mac)

        self.arduino = arduino.Arduino(self.mgr, self.mac)
        self.minimum_rssi = self.mgr.config.get_value('minimum_rssi')

        if self.mac not in self.protocol.loggers:
            self.logger = logger.ScanLogger(self.mgr, self.mac)
            self.logger_rssi = logger.RSSILogger(self.mgr, self.mac)
            self.logger_inquiry = logger.InquiryLogger(self.mgr, self.mac)
            self.protocol.loggers[self.mac] = (self.logger, self.logger_rssi, self.logger_inquiry)
        else:
            self.logger, self.logger_rssi, self.logger_inquiry = self.protocol.loggers[self.mac]

        self.discoverer = discoverer.Discoverer(self, self.dev_id, self.mac)

        device.SetProperty('Discoverable', False)
        Timer(20, self.add_pattern).start()
        Timer(60, self.clear_patterns).start()

    def clear_patterns(self):
        print "clearing patterns"
        self.scan_patterns.clear()

    def add_pattern(self):
        self.apply_scan_patterns( set([
            ScanPattern(self.mgr, self, start_time=60, inquiry_length=8, buffer_time=12-10.24, start_angle = 0, stop_angle = 180, scan_angle=180, turn_resolution =1)
            ]))

    def get_active_scan_pattern(self):
        t = time.time()
        p = sorted(list(self.scan_patterns))
        for i in p:
            print i.start_time

        for i in p:
            if (t <= i.stop_time or not i.stop_time):
                return i

        if len(p) > 0:
            if t <= p[-1].stop_time or not p[-1].stop_time:
                return p[-1]

        return None

    @core.threaded
    def start(self):
        self.init()
        while (not self.mgr.main.stopping):
            pattern = self.get_active_scan_pattern()
            if self.current_pattern == None or (self.current_pattern.pattern_finished and pattern != self.current_pattern):
                self.current_pattern = pattern
                if pattern:
                    print "WHIIIIEE GOT SOME NEW THINGS TO TRY :D :D"
                else:
                    print "IT'S OVER. DONE. 4EVAH!?"

            if self.current_pattern:
                self.current_pattern.what_now(self.discoverer.inquiry_with_rssi, [self.current_pattern.inquiry_length])
            else:
                print "nothing to do, sleeping for 1 sec"
                time.sleep(1)

    def init(self):
        if self.discoverer.init() == 0:
            self.mgr.log_info("Started scanning with Bluetooth adapter %s" % self.mac)
            self.mgr.net_send_line("STATE,bluetooth,%s,%0.3f,started_scanning" % (
                self.mac.replace(':',''), time.time()))
            self.logger.start()

    def apply_scan_patterns(self, scan_patterns):
        current_patterns = copy.deepcopy(self.scan_patterns)
        current_patterns.update(scan_patterns)

        r = []
        for p in current_patterns:
            if p.sensor_mac == None or p.sensor_mac == scanner.mac:
                r.append(p)

        r.sort()
        for i in range(1, len(r)):
            if not r[i-1].stop_time or (r[i].start_time < r[i-1].stop_time + r[i-1].pattern_duration):
                r[i-1].stop_time = r[i].start_time - r[i-1].pattern_duration

        self.scan_patterns = set(r)

    def property_changed(self, property, value, path):
        """
        Called if the properties of the scandevice have changed. In casu
        it is used to listen for the Discovering=False signal to restart
        scanning.
        """
        if property == "Discovering" and value == False:
            if self.mac not in self.protocol.active_adapters \
                and not self.protocol.is_excluded(self.dev_id, self.mac) \
                and not self.scan_pattern:
                    self.available = True
                    self.protocol.active_adapters.append(self.mac)
                    self.start()

    def device_discovered(self, address, device_class, rssi):
        """
        Called when discovered a device. Get a UNIX timestamp and call the
        update method of Logger to update the timestamp, the address and
        the device_class of the device in the pool.

        @param  address        Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  rssi           The RSSI (RX power level) value of the
                                discovery. None when none recorded.
        """
        angle = self.arduino.get_angle()
        if (rssi == None or \
            not (self.minimum_rssi != None and rssi < self.minimum_rssi)) \
            and (True not in (address.upper().startswith(
                black_mac) for black_mac in self.mgr.blacklist)):

            try:
                device_class = int(device_class)
            except ValueError:
                device_class = -1

            hwid = self.mgr.privacy_process(address)
            hwid = hwid.replace(':', '')

            timestamp = time.time()

            if self.mgr.debug_mode:
                import gyrid.tools.deviceclass as deviceclass
                import gyrid.tools.macvendor as macvendor

                device = ', '.join([str(deviceclass.get_major_class(
                    device_class)), str(deviceclass.get_minor_class(
                    device_class))])
                rssi_s = ' with RSSI %d' % rssi if rssi != None else ''

                d = {'hwid': hwid, 'dc': device, 'time': str(timestamp),
                     'rssi': rssi_s, 'sc': self.mac}

                self.mgr.debug(
                    "%(sc)s: Found device %(hwid)s [%(dc)s]" % d + \
                    "%(rssi)s" % d, force=True)

            self.logger.update_device(timestamp, hwid, device_class)

            if rssi != None:
                self.logger_rssi.write(timestamp, hwid, device_class, rssi, angle)

    def inquiry_started(self, duration):
        self.logger_inquiry.write(time.time(), duration)
        self.mgr.debug("%s: New inquiry" % self.mac)

    def stopped_scanning(self, reason):
        self.logger.stop()

    @core.threaded
    def start_scanning(self):
        """
        Start the Discoverer and start scanning. Start the logger in order to
        get the pool_checker running. This function is decorated to start in
        a new thread automatically. The scan ends if there is no Bluetooth
        device (anymore).

        @param  device_id   The device to use for scanning.
        """
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
                    _logger_inquiry, self.dev_id, self.mac, self.scan_pattern)

                if _discoverer.init() == 0:
                    self.mgr.log_info("Started scanning with Bluetooth adapter %s" % self.mac)
                    self.mgr.net_send_line("STATE,bluetooth,%s,%0.3f,started_scanning" % (
                        self.mac.replace(':',''), time.time()))
                    _logger.start()
                    end_cause = _discoverer.loop_scan()
                    _logger.stop()
                    self.mgr.log_info("Stopped scanning with Bluetooth adapter %s%s" % \
                        (self.mac, end_cause))
                    self.mgr.net_send_line("STATE,bluetooth,%s,%0.3f,stopped_scanning" % (
                        self.mac.replace(':',''), time.time()))

                if self.mac in self.protocol.active_adapters:
                    self.protocol.active_adapters.remove(self.mac)
                del(_discoverer)
