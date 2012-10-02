#!/usr/bin/python
#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner.
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
import time
import zlib

import gyrid.configuration as configuration

from OpenSSL import SSL

from twisted.internet import reactor, ssl, task
from twisted.internet.error import CannotListenError
from twisted.internet.protocol import Factory, ReconnectingClientFactory
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

        f = open('/proc/uptime', 'r')
        self.host_up_since = int(time.time()) - int(float(f.readline().strip().split()[0]))
        f.close()

        self.gyrid_up_since = None

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
        class Main:
            def log_error(self, level, message):
                pass

        self.main = Main()

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
    def connectionMade(self):
        """
        Called when the Gyrid daemon connected to this middleware.
        """
        if self.factory.inet_factory.client:
            self.factory.inet_factory.client.sendLine(
                'MSG,gyrid,connected')

    def connectionLost(self, reason):
        """
        Called when the Gyrid daemon disconnected from this middleware.

        @param  reason  The reason of disconnection.
        """
        if self.factory.inet_factory.client:
            self.factory.inet_factory.client.sendLine(
                'MSG,gyrid,disconnected')

    def lineReceived(self, data):
        """
        Called when a line has been received, send the data via the inet
        client to the Gyrid server.
        """
        if data.startswith('LOCAL') and self.factory.inet_factory.client:
            self.factory.inet_factory.client.processLocalData(data)
        elif self.factory.inet_factory.client:
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

    def connectionMade(self):
        """
        Called when a new connection has been made.
        Close the cache.
        """
        if not self.factory.cache.closed:
            self.factory.cache.flush()
            self.factory.cache.close()

        try:
            self.factory.cachesize_loop.stop()
        except AssertionError:
            pass

        self.factory.connected = True

    def connectionLost(self, reason):
        """
        Called when the connection has been lost.
        Open cache file and write await_ack buffer to cache.
        """
        if self.factory.config['enable_cache'] and self.factory.cache.closed \
            and not self.factory.cache_full:
            self.factory.cache = open(self.factory.cache_file, 'a')

            for v in self.factory.await_ack.values():
                self.factory.cache.write('%s\n' % v)
            self.factory.cache.flush()
            self.factory.await_ack.clear()

        self.factory.connected = False

    def sendLine(self, data, await_ack=True):
        """
        Send a line to the Gyrid server. When not connected,
        store the data in the cache.

        @param   data        The line to send.
        @param   await_ack   Whether the line should be added to the
                             await_ack buffer.
        """
        data = str(data).strip()
        if self.factory.config['enable_cache'] and not self.factory.connected \
            and not self.factory.cache.closed and not self.factory.cache_full \
            and not data.startswith('MSG') and not data.startswith('STATE'):
            self.factory.cache.write(data + '\n')
        else:
            r = self.factory.filter(data)
            if r != None and self.transport != None:
                LineReceiver.sendLine(self, r)
                if await_ack and not r.startswith('MSG') \
                    and not r.startswith('STATE') \
                    and self.factory.config['enable_cache']:
                    self.factory.await_ack[self.factory.checksum(r)] = data

    def lineReceived(self, data):
        """
        Called when a line was received.

        @param   data   The received data.
        """
        data = data.strip().lower()
        dl = data.split(',')
        if dl[0] == 'msg':
            if dl[1] == 'hostname':
                self.sendLine("MSG,hostname,%s" % socket.gethostname())
            elif self.factory.config['enable_keepalive'] > 0 and \
                len(dl) == 2 and dl[1] == 'keepalive':
                self.factory.last_keepalive = int(time.time())
                self.sendLine("MSG,keepalive")
            elif dl[1] == 'cache' and len(dl) == 3:
                if dl[2] == 'push':
                    reactor.callInThread(self.pushCache)
                elif dl[2] == 'clear':
                    self.clearCache()
            else:
                r = self.factory.setConfig(dl)
                if r != None:
                    self.sendLine(r)
            if dl[1] == 'enable_keepalive' and len(dl) > 2 and dl[2] > 0:
                self.factory.keepalive_loop.start(
                    self.factory.config['enable_keepalive'], now=False)
            elif dl[1] == 'enable_uptime' and self.factory.config[
                'enable_uptime'] == True \
                and self.network.host_up_since != None \
                and self.network.gyrid_up_since != None:
                self.sendLine("MSG,uptime,%i,%i" % \
                    (self.network.gyrid_up_since, self.network.host_up_since))
        elif dl[0] == 'ack' and len(dl) == 2:
            if dl[1] in self.factory.await_ack:
                del(self.factory.await_ack[dl[1]])

    def processLocalData(self, data):
        """
        Process data meant for local variables.

        @param  data   The data to process.
        """
        data = data.strip().lower().split(',')
        if len(data) >= 3 and data[1] == 'gyrid_uptime':
            self.network.gyrid_up_since = int(float(data[2]))
            if self.factory.config['enable_uptime'] \
                and self.network.host_up_since != None \
                and self.network.gyrid_up_since != None:
                self.sendLine("MSG,uptime,%i,%i" % \
                    (self.network.gyrid_up_since, self.network.host_up_since))

    def pushCache(self):
        """
        Push trough the cached data. Clears the cache afterwards.
        """
        if not self.factory.cache.closed:
            self.factory.cache.flush()
            self.factory.cache.close()

        self.factory.cache = open(self.factory.cache_file, 'r')
        for line in self.factory.cache:
            line = line.strip()
            r = self.factory.filter(line)
            if r != None and self.factory.config['enable_cache']:
                self.factory.await_ack[self.factory.checksum(r)] = line
        self.factory.cache.close()

        self.clearCache()

        for line in self.factory.await_ack.values():
            self.sendLine(line, await_ack=False)

    def clearCache(self):
        """
        Clears the cache file.
        """
        if not self.factory.cache.closed:
            self.factory.cache.flush()
            self.factory.cache.close()

        self.factory.cache = open(self.factory.cache_file, 'w')
        self.factory.cache.truncate()
        self.factory.cache.close()

        self.factory.cache_full = False

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

        self.connected = False
        self.cache_full = False
        self.cache_file = '/var/tmp/gyrid-network.cache'
        self.cache = open(self.cache_file, 'a')
        self.await_ack = {}

        self.keepalive_loop = task.LoopingCall(self.keepalive)
        self.cachesize_loop = task.LoopingCall(self.checkCacheSize)

        self.buildProtocol(None)
        self.init()

    def init(self):
        """
        Initialise per-connection variables.
        Starts and stops looping calls.
        """
        self.last_keepalive = -1

        self.config = {'enable_rssi': False,
                       'enable_sensor_mac': True,
                       'enable_cache': True,
                       'enable_keepalive': -1,
                       'enable_uptime': False,
                       'enable_state_scanning': False,
                       'enable_state_inquiry': False}

        self.cachesize_loop.start(10)
        try:
            self.keepalive_loop.stop()
        except AssertionError:
            pass

    def checksum(self, data):
        """
        Calculate the CRC32 checksum for the given data string.

        @param   data   The data to process.
        @return         The CRC32 checksum.
        """
        return hex(abs(zlib.crc32(data)))[2:]

    def checkCacheSize(self):
        """
        Check the size of the cache and disable caching when full (250MB).
        """
        if not self.cache.closed:
            self.cache.flush()

        if os.path.isfile(self.cache_file) and \
            os.path.getsize(self.cache_file) > (250*1048576):
            self.cache.flush()
            self.cache.close()
            self.cache_full = True
            try:
                self.cachesize_loop.stop()
            except AssertionError:
                pass

    def keepalive(self):
        """
        Checks if a keepalive has been received recently and closes
        the connection otherwise.
        """
        t = self.config['enable_keepalive']
        if self.last_keepalive < int(time.time() - (t+0.1*t)):
            self.connected = False
            if self.client:
                self.client.transport._writeDisconnected = True
                self.client.transport.loseConnection()

    def filter(self, data):
        """
        Filter outgoing data according to the configuration options.

        @param   data  The data to filter.
        @return        The filtered data, None if nothing should go out.
        """
        if data.startswith('MSG'):
            return data
        elif data.startswith('SIGHT_CELL'):
            data = dict(zip(['sensor_mac', 'timestamp', 'mac',
                'deviceclass', 'move'], data.split(',')[1:]))
        elif data.startswith('SIGHT_RSSI') and self.config['enable_rssi']:
            data = dict(zip(['sensor_mac', 'timestamp', 'mac', 'rssi'],
                data.split(',')[1:]))
        elif data.startswith('STATE') and ('new_inquiry' in data) and \
            self.config['enable_state_inquiry']:
            data = dict(zip(['type', 'sensor_mac', 'timestamp', 'info'],
                data.split(',')))
        elif data.startswith('STATE') and ('_scanning' in data) and \
            self.config['enable_state_scanning']:
            data = dict(zip(['type', 'sensor_mac', 'timestamp', 'info'],
                data.split(',')))
        elif data.startswith('INFO'):
            data = dict(zip(['type', 'timestamp', 'info'],
                data.split(',')))
        else:
            return None

        try:
            for item in self.config:
                if self.config[item] == False:
                    data[item.lstrip('enable_')] = ''
        except KeyError:
            pass

        return ','.join([data[j] for j in [i for i in ['type', 'sensor_mac',
            'timestamp', 'mac', 'deviceclass', 'move',
            'rssi', 'info'] if i in data] if data[j]])

    def setConfig(self, list):
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
            elif len(list) > 2:
                try:
                    self.config[list[1]] = int(list[2])
                except ValueError:
                    try:
                        self.config[list[1]] = float(list[2])
                    except ValueError:
                        self.config[list[1]] = str(list[2])

            return "MSG,%s,%s" % (list[1], self.config[list[1]])
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
        Re-initialise per-connection variables and looping calls.
        """
        ReconnectingClientFactory.clientConnectionLost(
            self, connector, reason)

        self.init()

    def clientConnectionFailed(self, connector, reason):
        """
        Called when the connection to the server failed.
        """
        ReconnectingClientFactory.clientConnectionFailed(
            self, connector, reason)

        if 'OpenSSL.SSL.Error' in str(reason):
            self.network.exit_code = 3
            self.network.stop()

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
        try:
            ctx.use_certificate_file(self.network.config.get_value(
                'network_ssl_client_crt'))
            ctx.use_privatekey_file(self.network.config.get_value(
                'network_ssl_client_key'))
        except SSL.Error:
            self.network.exit_code = 3
            self.network.stop()

        return ctx

if __name__ == '__main__':
    n = Network()
