#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2010  Roel Huybrechts
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
Module that handles network support. This module connects to the Gyrid
networking middleware running at localhost TCP port 25830 through Python's
socket module.
"""

import socket
import threading
import time

class Network(threading.Thread):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, mgr):
        """
        Initialisation.

        @param   mgr   Reference to ScanManager instance.
        """
        threading.Thread.__init__(self)
        self.mgr = mgr

        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._running = True

        self.start()

    def run(self):
        """
        Start the thread, connecting to the socket.
        """
        while self._running:
            self._connect()

    def _connect(self):
        """
        Connect to the socket, sleep for a minute when it fails.
        """
        try:
            self.s.connect(('127.0.0.1', 25830))
            self.mgr.debug("Connected to the networking component")
            self.send_line("LOCAL,gyrid_uptime,%i" % self.mgr.startup_time)
        except socket.error, e:
            if e[0] == 9:
                self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            else:
                if self.mgr.network_middleware.poll() == 2:
                    self.mgr.log_info("Disabling networking support due to " + \
                        "missing SSL credentials. Make sure the client key " + \
                        "and certificate are present at the specified location")
                    self.stop()
                    del(self.mgr.network)
                elif self.mgr.network_middleware.poll() == 3:
                    self.mgr.log_info("Disabling networking support due to " + \
                        "bad SSL credentials")
                    self.stop()
                    del(self.mgr.network)
                elif self.mgr.network_middleware.poll() != None:
                    self.mgr.init_network_middleware()
                elif self.mgr.network_middleware.poll() == None:
                    time.sleep(60)

    def send_line(self, line):
        """
        Try to send the given line over the socket to the Gyrid networking
        component.

        @param   line   The line to send.
        """
        try:
            self.s.send('%s\r\n' % line.strip())
        except socket.error, e:
            if e[0] == 32:
                self.mgr.debug("No connection to the networking component")
                self.s.close()

    def stop(self):
        """
        Stop the thread, close the socket.
        """
        try:
            self._running = False
            self.s.close()
        except:
            pass
