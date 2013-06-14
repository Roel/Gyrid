#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner daemon.
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

import logging
import logging.handlers
import os
import serial
import time
from threading import Timer

import zippingfilehandler

class Arduino(object):
    """
    This class provides support for the Arduino rotating antenna platform.
    """
    def __init__(self, mgr, mac):
        """
        Initialisation.

        @param  mgr    Reference to the Scanmanager instance.
        @param  mac    The MAC-address of the Bluetooth scanning device.
        """
        self.mgr = mgr
        self.mac = mac

        self.dev = self.get_conf()
        self.conn = self.get_conn()

        self.angle = 0

    def write(self, string):
        """
        Try to write the given string to the serial connection.
        """
        try:
            self.conn.write(string)
        except (AttributeError, OSError, serial.SerialException):
            if self.conn:
                self.conn.close()
                self.conn = None
            return False
        else:
            return True

    def set_angle(self, angle):
        self.angle = angle

    def turn(self, angle):
        self.write('%ir' % angle)
        time.sleep(0.0035 * abs(self.angle-angle))
        self.angle = angle

    def sweep(self, start_angle, stop_angle, duration):
        self.write('%ia' % start_angle)
        self.write('%ib' % stop_angle)
        self.write('%id' % (duration*1000/abs(stop_angle-start_angle)))
        self.write('s')
        Timer(duration, self.set_angle, [stop_angle]).start()

    def get_conf(self):
        """
        Read the Arduino configuration file. This should be in CSV format,
        containing the following fields: MAC-address of the scanning device,
        filename of the device node of the corresponding Arduino (without
        /dev/), turning resolution (i.e. in how many parts the 180 degree
        arc is divided).

        @return   str,int   Full device node path, turning resolution.
        """
        path = self.mgr.config.get_value('arduino_conffile')
        if os.path.isfile(path):
            file = open(path, 'r')
            for line in file:
                l = line.strip().split(',')
                mac = self.mgr.is_valid_mac(l[0])
                if self.mac and mac and mac != self.mac:
                    return
                return '/dev/' + l[1]
        return None

    def get_conn(self):
        """
        Setup and return the serial connection with the Arduino.
        """
        if self.dev and os.path.exists(self.dev):
            try:
                conn = serial.Serial(self.dev, 19200)
                time.sleep(2)
                conn.write('0')
                conn.write('r')
                time.sleep(0.0035 * 180)
                self.angle = 0
                #self.mgr.debug("%s: Antenna initialised to %i degrees" % (
                #    self.mac, self.angle))
                #self.mgr.net_send_line(','.join([str(i) for i in ['STATE',
                #    'bluetooth', self.mac.replace(':','').lower(),
                #    '%0.3f' % time.time(), 'antenna_rotation', self.angle]]))
                self.asc = True
                self.first_inquiry = True
                self.has_been_connected = True
                return conn
            except (serial.SerialException, OSError):
                return None
        return None

    def stop(self):
        if self.conn:
            self.conn.close()
