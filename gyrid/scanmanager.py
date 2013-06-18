#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
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
import hashing
import logger
import network
import wigy

import scanners.bluetooth
import scanners.wifi

import scapy.all

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

        self.config = configuration.Configuration(self, self.main.configfile)
        self.info_logger = logger.InfoLogger(self, self.get_info_log_location())
        self.time_format = self.config.get_value('time_format')
        self.enable_hashing = self.config.get_value('enable_hashing')

    def init(self):
        """
        Full initialisation. Initialise everything, called when the program is
        starting up.
        """
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        dbus.mainloop.glib.threads_init()
        self._dbus_systembus = dbus.SystemBus()

        if self.init_network_middleware() == True:
            self.network = network.Network(self)

        if self.config.get_value('minimum_rssi') != None:
            self.log_info("Using a minimum RSSI value of %i, " % \
                self.config.get_value('minimum_rssi') + \
                "detections with a lower RSSI value are ignored")

        self.hashing = hashing.Hashing(self)
        self.read_blacklist()

        bluetooth = scanners.bluetooth.Bluetooth(self)
        wifi = scanners.wifi.WiFi(self)

    def init_network_middleware(self):
        """
        Start the network middleware.

        @return  true   When the middleware is started,
                 false  when the middleware is not started.
        """
        if len(self.config.get_value('network_server_host')) > 0:
            dir = os.path.dirname(os.path.abspath(__file__))
            m_path = dir[:dir.rfind('/')] + '/network_middleware.py'
            if not os.path.isfile(m_path):
                m_path = '/usr/share/gyrid/network_middleware.py'

            self.network_middleware = subprocess.Popen(
                ["/usr/bin/python", m_path])
            time.sleep(2)
            return True
        else:
            return False

    def read_blacklist(self):
        """
        Read the blacklist file and save values in class variable.
        When the file does not exist, the blacklist is cleared.
        """
        path = self.config.get_value('blacklist_file')
        if os.path.isfile(path):
            self.blacklist = set()
            file = open(path, 'r')
            macs_listed = 0
            for line in file:
                l = line.strip()
                macs = self.is_start_mac(l)
                if macs > 0:
                    self.blacklist.add(l.upper())
                    macs_listed += macs
            file.close()
            if macs_listed > 0:
                self.log_info("Using blacklist file, detections " + \
                    "of %i " % macs_listed + \
                    "listed MAC-address(es) are ignored")
        else:
            self.blacklist = set()

    def net_send_line(self, line):
        """
        Try to send the given line over the socket to the Gyrid networking
        component via the network module. This is failsafe, also when networking
        support is disabled.

        @param   line   The line to send.
        """
        if 'network' in self.__dict__:
            self.network.send_line(line)

    def privacy_process(self, string, force=False):
        """
        Process given string to produce a more privacy robust output.
        """
        if self.enable_hashing or force:
            return self.hashing.hash(string)
        return string

    def is_valid_mac(self, string):
        """
        Determine if the given string is a valid MAC-address.

        @param  string   The string to test.
        @return          The MAC-address if it is valid, else False.
        """
        string = string.strip().upper()
        if len(string) == 17 and \
            re.match(r"([0-F][0-F]:){5}[0-F][0-F]", string):
            return string
        else:
            return False

    def is_start_mac(self, string):
        """
        Determine if the given string is the start of a valid MAC-address.
        Returns the number of possible valid MAC-addresses covered.
        Returns 0 if the string is not a valid start of a MAC-address.

        @param  string   The string to test.
        @return          The number of valid MAC-addresses covered.
        """
        string = string.strip().upper()
        for i in range(6):
            if (i*3)+2 <= len(string) <= (i*3)+3 and \
                re.match(r"^([0-F][0-F]:){%i}[0-F][0-F]:?$" % i, string):
                    return 256**(5-i)
        return 0

    def set_debug_mode(self, debug, silent):
        """
        Enable or disable debug mode.

        @param  debug   True to enable debug mode.
        @param  silent  True to enable silent (no logging) debug mode.
        """
        self.debug_mode = debug
        self.debug_silent = silent

    @threaded
    def frequency_loop(self, interface):
        freq = 2412
        endfreq = 2472

        while freq <= (endfreq-5):
            freq += 5
            self.debug("Setting frequency to %i Hz" % freq)
            wigy.set_frequency(interface, freq)
            time.sleep(10)

    def format_time(self, t=None):
        if not t:
            t = time.time()

        ms = ''
        if '%Q' in self.time_format:
            ms = ('%0.3f' % float('.' + str(t).split('.')[1]))[1:]

        return time.strftime(self.time_format, time.localtime(t)).replace('%Q', ms)

    def debug(self, message, force=False):
        """
        Write message to stderr if debug mode is enabled.

        @param  message   The text to print.
        @param  force     Force printing even if debug mode is disabled.
        """
        if self.debug_mode or force:
            d = {'time': self.format_time(),
                 'message': message}
            sys.stdout.write("%(time)s Gyrid: %(message)s.\n" % d)

    def makedirs(self, path, mode=0755):
        """
        Create directories recursively. Only creates path if it doesn't exist
        yet.

        @param  path   The path to be created.
        @param  mode   The permissions used to create the directories.
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

    def get_inquiry_log_location(self):
        """
        Get the location of the logfile for inquiry starttimes.

        Implement this method in a subclass.
        """
        raise NotImplementedError

    def stop(self):
        """
        Use this function in a subclass.

        Dims the lights on shutdown.
        """
        if 'network' in self.__dict__:
            self.network.stop()

        if self.config.get_value('alix_led_support') and \
                (False not in [os.path.exists('/sys/class/leds/alix:%i' % i) \
                for i in [1, 2, 3]]):

            for i in [3]:
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

    def get_wifidevraw_log_location(self, mac):
        mac = mac.replace(':','')
        self.makedirs(self.base_location + mac)
        return self.base_location + mac + '/wifi-DRW.log'

    def get_wifiraw_log_location(self, mac):
        mac = mac.replace(':','')
        self.makedirs(self.base_location + mac)
        return self.base_location + mac + '/wifi-RAW.log'

    def get_wifi_log_location(self, mac, type):
        mac = mac.replace(':','')
        self.makedirs(self.base_location + mac)
        return self.base_location + mac + '/wifi-%s.log' % type

    def get_inquiry_log_location(self, mac):
        mac = mac.replace(':','')
        self.makedirs(self.base_location + mac)
        return self.base_location + mac + '/inquiry.log'

    def get_info_log_location(self):
        return self.base_location + 'messages.log'
