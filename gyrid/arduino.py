#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
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

        self.dev, self.resolution = self.get_conf()

        self.has_been_connected = False

        if self.dev:
            self.angle = 0
            self.asc = True
            self.first_inquiry = True

            mac = self.mac.replace(':', '')
            self.time_format = self.mgr.config.get_value('time_format')

            self.mgr.makedirs(self.mgr.base_location + mac)
            logfile = self.mgr.base_location + mac + '/angle.log'
            self.log = logging.getLogger('%s-angle' % mac)
            handler = zippingfilehandler.CompressingRotatingFileHandler(self.mgr,
                logfile, False)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.log.addHandler(handler)
            self.log.setLevel(logging.INFO)

        self.conn = self.get_conn()

    def write(self, string):
        """
        Try to write the given string to the serial connection.
        """
        try:
            self.conn.write(string)
        except (AttributeError, OSError):
            if self.conn:
                self.conn.close()
                self.conn = None
            return False
        else:
            return True

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
                resolution = int(l[2]) if len(l) >= 3 else 10
                if mac and mac == self.mac:
                    return '/dev/' + l[1], resolution
        return None, None

    def get_conn(self):
        """
        Setup and return the serial connection with the Arduino.
        """
        if self.dev and os.path.exists(self.dev):
            try:
                conn = serial.Serial(self.dev, 19200)
                time.sleep(2)
                conn.write('0')
                conn.write('s')
                time.sleep(0.0035 * 180)
                self.angle = 0
                self.mgr.debug("%s: Antenna initialised to %i degrees" % (
                    self.mac, self.angle))
                self.mgr.net_send_line(','.join([str(i) for i in ['STATE',
                    'bluetooth', self.mac.replace(':','').lower(),
                    '%0.3f' % time.time(), 'antenna_rotation', self.angle]]))
                self.asc = True
                self.first_inquiry = True
                self.has_been_connected = True
                return conn
            except (serial.SerialException, OSError):
                return None
        return None

    def turn(self):
        """
        Turn the platform based on the current angle and the turning
        resolution.
        """
        if self.conn and not self.first_inquiry:
            d_angle = 180.0/self.resolution

            if self.asc:
                angle = self.angle + d_angle
            else:
                angle = self.angle - d_angle

            if not (0 < angle < 180):
                self.asc = not self.asc

            if angle < 0:
                angle = 0

            if angle > 180:
                angle = 180

            if self.write('%i' % angle) and self.write('s'):
                time.sleep(0.0035 * 180)
                self.angle = angle
                self.mgr.debug("%s: Antenna turning to %i degrees" % (
                    self.mac, self.angle))
                self.mgr.net_send_line(','.join([str(i) for i in ['STATE',
                    'bluetooth', self.mac.replace(':','').lower(),
                    '%0.3f' % time.time(), 'antenna_rotation',
                    '%0.2f' % self.angle]]))

        self.first_inquiry = False

    def write_log(self, address, device_class, rssi):
        """
        Write a detection to the angle log, which contains all
        fields of the rssi log plus the angle of the platform
        at which the detection was received.
        """
        if self.dev and not self.conn:
            self.conn = self.get_conn()

        if self.has_been_connected:
            timestamp = int(time.time())
            self.log.info(",".join([time.strftime(self.time_format,
                time.localtime(timestamp)), str(address),
                str(rssi), "%0.2f" % self.angle]))

    def stop(self):
        self.conn.close()
