#!/usr/bin/python
#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
# Copyright (C) 2010-2011  Roel Huybrechts
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
Script that provides the Gyrid networking middleware. This script listens at
localhost TCP port 25830 for connections from the scanning daemon and passes
the received data on to the remote Gyrid server. Both connections are managed
with the Twisted framework and the connection to the remote server is tunnelled
through SSL.

Erroneous exit codes:
 1: Cannot listen on port 25830, probably another middleware running.
 2: SSL client key and/or certificate missing.
 3: SSL credentials rejected by server.
"""

import atexit
import os
import socket
import sys
import threading

import gyrid.configuration as configuration

from OpenSSL import SSL

from twisted.internet import ssl, reactor
from twisted.internet.error import CannotListenError
from twisted.internet.protocol import ReconnectingClientFactory, Factory
from twisted.protocols.basic import LineReceiver

class Network(object):
    """
    Main class that instanciates the factories and fires up the connections.
    """
    def __init__(self):
        """
        Initialisation. Everything happens basically here.
        """
        self.config = configuration.Configuration(FakeScanManager(),
            '/etc/gyrid.conf')
        atexit.register(self.exit)
        self.exit_code = 0

        inet_factory = InetClientFactory(self)
        local_factory = LocalServerFactory(self, inet_factory)
        self.enable_ssl = True
        self.host = self.config.get_value('network_server_host')
        self.port = self.config.get_value('network_server_port')
        self.local_port = 25830

        if False not in ['None' == self.config.get_value(
            'network_ssl_client_%s' % i) for i in ['crt', 'key']]:
            self.enable_ssl = False
        elif False in [os.path.isfile(self.config.get_value(
            'network_ssl_client_%s' % i)) for i in ['crt', 'key']]:
            self.exit_code = 2
            self.exit()

        if len(self.host) > 0:
            try:
                reactor.listenTCP(self.local_port, local_factory,
                    interface='127.0.0.1')
            except CannotListenError, e:
                if e[2][0] == 98:
                    self.exit_code = 1
                    self.exit()
            else:
                if self.enable_ssl:
                    reactor.connectSSL(self.host[0], self.port, inet_factory,
                        InetCtxFactory(self))
                    reactor.run()
                else:
                    reactor.connectTCP(self.host[0], self.port, inet_factory)
                    reactor.run()

    def exit(self):
        """
        Exit the middleware. This is called automatically upon reactor shutdown,
        but can be called manually out of the reactor loop as well.
        """
        sys.stderr = None
        sys.stout = None
        sys.exit(self.exit_code)

    def stop(self):
        """
        Stop the reactor.
        """
        reactor.stop()

class FakeScanManager(object):
    def __init__(self):
        """
        Initialisation.
        """
        def main():
            def log_error(level, message):
                pass

        self.main = main

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

class LocalServer(LineReceiver):
    """
    The interacting class of the local server.
    """
    def lineReceived(self, data):
        """
        Called when a line has been received, send the data via the inet
        client to the Gyrid server.
        """
        if self.factory.inet_factory.client:
            self.factory.inet_factory.client.sendLine(data)

class LocalServerFactory(Factory):
    """
    The factory class of the local server.
    """
    protocol = LocalServer

    def __init__(self, network, inet_factory):
        """
        Initialisation.

        @param   network        Reference to a Network instance.
        @param   inet_factory   Reference to an InetClientFactory instance.
        """
        self.network = network
        self.inet_factory = inet_factory

class InetClient(LineReceiver):
    """
    The interacting class of the inet client.
    """
    def __init__(self, network, factory):
        """
        Initialisation.

        @param   network   Reference to a Network instance.
        @param   factory   Reference to our factory.
        """
        self.network = network
        self.network.client = self
        self.factory = factory

    def sendLine(self, data):
        """
        Send a line to the Gyrid server.

        @param   data   The line to send.
        """
        data = str(data).strip()
        r = self.factory.filter(data)
        if r != None:
            LineReceiver.sendLine(self, r)

    def lineReceived(self, data):
        """
        Called when a line was received.

        @param   data   The received data.
        """
        data = data.strip()
        dl = data.split(',')
        if dl[0] == 'SMSG':
            if dl[1] == 'hostname':
                self.sendLine("SMSG,hostname,%s" % socket.gethostname())
            elif dl[1] == 'keepalive':
                self.sendLine("SMSG,keepalive,ok")
            else:
                r = self.factory.set_config(dl)
                if r != None:
                    self.sendLine(r)

class InetClientFactory(ReconnectingClientFactory):
    """
    The factory class of the inet client.
    """
    def __init__(self, network):
        """
        Initialisation.

        @param   network   Reference to a Network instance.
        """
        self.network = network
        self.client = None
        self.maxDelay = 120

        self.init()

    def init(self):
        """
        Initialise per-connection variables.
        """
        self.config = {'enable_rssi': False,
                       'enable_sensor_mac': True,
                       'enable_timestamp': True}

    def filter(self, data):
        """
        Filter outgoing data according to the configuration options.

        @param   data  The data to filter.
        @param         The filtered data, None if nothing should go out.
        """
        if data.startswith('SIGHT_CELL'):
            data = dict(zip(['sensor_mac', 'timestamp', 'mac',
                'deviceclass', 'move'], data.split(',')[1:]))
        elif data.startswith('SIGHT_RSSI') and not self.config['enable_rssi']:
            return None
        elif data.startswith('SIGHT_RSSI'):
            data = dict(zip(['sensor_mac', 'timestamp', 'mac', 'rssi'],
                data.split(',')[1:]))
        else:
            return data

        try:
            for item in self.config:
                if self.config[item] == False:
                    data[item.lstrip('enable_')] = ''
        except KeyError:
            pass

        return ','.join([data[j] for j in [i for i in ['sensor_mac',
            'timestamp', 'mac', 'deviceclass', 'move',
            'rssi'] if i in data] if data[j]])

    def set_config(self, list):
        """
        Set the value of a configuration option.

        @param   list     A list of the fields contained in the received
                            CSV-string.
        @return           The string that should be sent to the client,
                            None if nothing should go out.
        """
        if len(list) > 1 and list[1] in self.config:
            if len(list) > 2 and list[2].lower() == 'true':
                self.config[list[1]] = True
            elif len(list) > 2 and list[2].lower() == 'false':
                self.config[list[1]] = False
            return "SMSG,%s,%s" % (list[1], self.config[list[1]])
        else:
            return None

    def buildProtocol(self, addr):
        """
        Build the InetClient protocol, return an InetClient instance.
        """
        self.resetDelay()
        self.client = InetClient(self.network, self)
        return self.client

    def clientConnectionLost(self, connector, reason):
        """
        Called when the connection to the server is lost.
        """
        ReconnectingClientFactory.clientConnectionLost(
            self, connector, reason)

        self.init()

        if 'ssl handshake failure' in str(reason):
            self.network.exit_code = 3
            self.network.stop()

    def clientConnectionFailed(self, connector, reason):
        """
        Called when the connection to the server failed.
        """
        ReconnectingClientFactory.clientConnectionFailed(
            self, connector, reason)

class InetCtxFactory(ssl.ClientContextFactory):
    """
    The SSL context class of the inet client.
    """
    def __init__(self, network):
        """
        Initialisation.

        @param   network   Reference to a Network instance.
        """
        self.network = network

    def getContext(self):
        """
        Return the SSL client context.
        """
        self.method = SSL.SSLv23_METHOD
        ctx = ssl.ClientContextFactory.getContext(self)
        ctx.use_certificate_file(self.network.config.get_value(
            'network_ssl_client_crt'))
        ctx.use_privatekey_file(self.network.config.get_value(
            'network_ssl_client_key'))

        return ctx

if __name__ == '__main__':
    n = Network()
