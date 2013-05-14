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
import binascii
import os
import socket
import struct
import sys
import threading
import time
import zlib

import gyrid.configuration as configuration
import gyrid.protocol.network as proto

from OpenSSL import SSL

from twisted.internet import reactor, ssl, task
from twisted.internet.error import CannotListenError
from twisted.internet.protocol import Factory, ReconnectingClientFactory
from twisted.protocols.basic import Int16StringReceiver, LineReceiver

class Network(object):
    """
    Main class that instanciates the factories and fires up the connections.
    """
    def __init__(self):
        """
        Initialisation. Everything happens basically here.
        """
        self.config = configuration.Configuration(FakeScanManager(),
            '/etc/gyrid/gyrid.conf')
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

class AckItem(object):
    """
    Class that defines an item in the AckMap.
    """

    # The maximum value of the timer after which the item is resent.
    max_misses = 5

    def __init__(self, msg, timer=0):
        """
        Initialisation.

        @param   msg      The msg to store.
        @param   timer    The initial value of the timer. An item is resent
                             when this value is negative or exceeds
                             AckItem.max_misses.
        """
        self.ackmap = None
        self.msg = msg
        self.timer = timer
        self.checksum = AckMap.checksum(msg.SerializeToString())

    def __eq__(self, item):
        return (item.msg == self.msg and
                item.checksum == self.checksum)

    def __hash__(self):
        return int(self.checksum, 16)

    def incrementTimer(self):
        """
        Increment the timer by a value of 1.
        """
        if self.timer >= 0:
            self.timer += 1

    def checkResend(self):
        """
        Check if the data should be resent, and do so when required.
        """
        if self.ackmap != None:
            if self.timer > 10 * AckItem.max_misses:
                # Protection against cache overflow when a line repeatedly fails to be ack'ed.
                self.ackmap.clearItem(self.checksum)

            elif self.timer < 0 or (self.timer % AckItem.max_misses == 0):
                self.msg.cached = True
                self.checksum = AckMap.checksum(self.msg.SerializeToString())
                client = self.ackmap.factory.client
                if client != None:
                    client.sendMsg(self.msg, await_ack=False)

class AckMap(object):
    """
    Class that stores the temporary cache, waiting for ack'ing by the server.
    """
    @staticmethod
    def checksum(data):
        """
        Calculate the CRC32 checksum for the given data string.

        @param   data   The data to process.
        @return         The CRC32 checksum.
        """
        r = '%x' % abs(zlib.crc32(data))
        if len(r) % 2 != 0:
            r = '0' + r
        return r

    def __init__(self, factory):
        """
        Initialisation. Start the checker loop which checks old cached lines
        and resends when necessary.

        @param   factory   Refence to InetClientFactory instance.
        """
        self.factory = factory
        self.ackmap = set()

        self.check_loop = task.LoopingCall(self.__check)

    def restartChecker(self):
        """
        Start or restart the checker loop based on the current keepalive interval.
        """
        self.stopChecker()
        self.startChecker()

    def startChecker(self):
        """
        Start the checker loop.
        """
        interval = self.factory.config['enable_keepalive']
        self.interval = interval if interval > 0 else 60

        try:
            self.check_loop.start(self.interval, now=False)
        except AssertionError:
            pass

    def stopChecker(self):
        """
        Stop the checker loop.
        """
        try:
            self.check_loop.stop()
        except AssertionError:
            pass

    def addItem(self, ackItem):
        """
        Add an item to the map.
        """
        ackItem.ackmap = self
        self.ackmap.add(ackItem)

    def clearItem(self, checksum):
        """
        Clear the item with the given checksum from the cache, i.e. when it
        has been ack'ed by the server.

        @param   checksum   The checksum to check.
        """
        item = None
        for i in self.ackmap:
            if i.checksum == checksum:
                item = i
                break

        if item != None:
            self.ackmap.difference_update([item])

    def clear(self):
        """
        Clear the entire map.
        """
        self.ackmap.clear()

    def __check(self):
        """
        Called automatically by the checker loop; should not be called
        directly. Checks each item in the map and resends when necessary.
        """
        for v in self.ackmap:
            v.incrementTimer()
            v.checkResend()

class LocalServer(LineReceiver):
    """
    The interacting class of the local server.
    """
    def connectionMade(self):
        """
        Called when the Gyrid daemon connected to this middleware.
        """
        if self.factory.inet_factory.client:
            m = proto.Msg()
            m.type = m.Type_STATE_GYRID
            m.stateGyrid.type = proto.StateGyrid.Type_CONNECTED
            self.factory.inet_factory.client.sendMsg(m, await_ack=False)

    def connectionLost(self, reason):
        """
        Called when the Gyrid daemon disconnected from this middleware.

        @param  reason  The reason of disconnection.
        """
        if self.factory.inet_factory.client:
            m = proto.Msg()
            m.type = m.Type_STATE_GYRID
            m.stateGyrid.type = proto.StateGyrid.Type_DISCONNECTED
            self.factory.inet_factory.client.sendMsg(m, await_ack=False)

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

class InetClient(Int16StringReceiver):
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
        self.factory.ackmap.startChecker()

    def connectionLost(self, reason):
        """
        Called when the connection has been lost.
        Open cache file and write await_ack buffer to cache.
        """
        if not self.factory.cache.closed:
            self.factory.cache.flush()
            self.factory.cache.close()

        if self.factory.config['enable_cache'] and not self.factory.cache_full:
            self.factory.cache = open(self.factory.cache_file, 'ab')
            for i in self.factory.ackmap.ackmap:
                self.factory.cache.write(
                    struct.pack('!H', i.msg.ByteSize()) + \
                    i.msg.SerializeToString())
            self.factory.cache.flush()
            self.factory.ackmap.clear()

        self.factory.connected = False

    def sendLine(self, line):
        """
        Parse the line into a corresponding message and send it.
        These lines originate from Gyrid.

        @param   line   The line to send.
        """
        msg = self.factory.buildMsg(line)
        if msg:
            self.sendMsg(msg)

    def sendMsg(self, msg, await_ack=True):
        """
        Send a message to the Gyrid server. When not connected,
        store the data in the cache.

        @param   msg         The message to send.
        @param   await_ack   Whether the message should be added to the
                             await_ack buffer.
        """
        if (not self.factory.config['enable_data_transfer'] and msg.type in [
            msg.Type_BLUETOOTH_DATAIO, msg.Type_BLUETOOTH_DATARAW, msg.Type_WIFI_DATARAW]) \
                or not self.factory.connected:
            if self.factory.config['enable_cache'] \
                and not self.factory.cache.closed and not self.factory.cache_full \
                and msg.type in [msg.Type_BLUETOOTH_DATAIO, msg.Type_BLUETOOTH_DATARAW,
                    msg.Type_BLUETOOTH_STATE_INQUIRY, msg.Type_STATE_SCANNING, msg.Type_INFO,
                    msg.Type_WIFI_STATE_FREQUENCY, msg.Type_WIFI_DATARAW, msg.Type_STATE_ANTENNA]:
                    self.factory.cache.write(
                        struct.pack('!H', msg.ByteSize()) + \
                        msg.SerializeToString())
        else:
            if self.transport != None:
                Int16StringReceiver.sendString(self, struct.pack('!H', msg.ByteSize()) + \
                    msg.SerializeToString())
                if await_ack and self.factory.config['enable_cache']:
                    self.factory.ackmap.addItem(AckItem(msg))

    def stringReceived(self, data):
        """
        Called when data is received from the server. Parse the data into a message
        and act accordingly.

        @param   data   The received data.
        """
        msg = proto.Msg.FromString(data)

        if msg.type == msg.Type_REQUEST_HOSTNAME:
            m = proto.Msg()
            m.type = m.Type_HOSTNAME
            m.hostname.hostname = socket.gethostname()
            self.sendMsg(m, await_ack=False)

        elif msg.type == msg.Type_REQUEST_KEEPALIVE:
            self.factory.config['enable_keepalive'] = msg.requestKeepalive.interval
            if not msg.requestKeepalive.enable:
                self.factory.config['enable_keepalive'] = -1
            else:
                self.factory.keepalive_loop.start(
                    self.factory.config['enable_keepalive'], now=False)

            msg.success = True
            self.sendMsg(msg, await_ack=False)

        elif msg.type == msg.Type_KEEPALIVE and \
            self.factory.config['enable_keepalive'] > 0:
            self.factory.last_keepalive = int(time.time())
            m = proto.Msg()
            m.type = m.Type_KEEPALIVE
            self.sendMsg(m, await_ack=False)

        elif msg.type == msg.Type_REQUEST_CACHING:
            if msg.requestCaching.pushCache:
                reactor.callInThread(self.pushCache)
            elif msg.requestCaching.clearCache:
                self.clearCache()

            self.factory.config['enable_caching'] = msg.requestCaching.enableCaching

            msg.success = True
            self.sendMsg(msg, await_ack=False)

        elif msg.type == msg.Type_ACK:
            self.factory.ackmap.clearItem(binascii.b2a_hex(msg.ack))

        elif msg.type == msg.Type_REQUEST_STATE:
            self.factory.config['enable_state_scanning'] = msg.requestState.enableScanning
            self.factory.config['enable_state_inquiry'] = msg.requestState.bluetooth_enableInquiry
            self.factory.config['enable_state_frequency'] = msg.requestState.wifi_enableFrequency
            self.factory.config['enable_state_antenna'] = msg.requestState.enableAntenna

            msg.success = True
            self.sendMsg(msg, await_ack=False)

        elif msg.type == msg.Type_REQUEST_UPTIME:
            self.factory.config['enable_uptime'] = msg.requestUptime

            msg.success = True
            self.sendMsg(msg, await_ack=False)

            if msg.requestUptime and self.network.host_up_since != None \
                and self.network.gyrid_up_since != None:
                m = proto.Msg()
                m.type = m.Type_UPTIME
                m.uptime.gyridStartup = self.network.gyrid_up_since
                m.uptime.systemStartup = self.network.host_up_since
                self.sendMsg(m, await_ack=False)

        elif msg.type == msg.Type_REQUEST_STARTDATA:
            self.factory.config['enable_data_transfer'] = msg.requestStartdata.enableData
            self.factory.config['enable_rssi'] = msg.requestStartdata.enableRaw
            self.factory.config['enable_sensor_mac'] = msg.requestStartdata.enableSensorMac

            msg.success = True
            self.sendMsg(msg, await_ack=False)

            #FIXME: start data transfer now

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
                m = proto.Msg()
                m.type = m.Type_UPTIME
                m.uptime.gyridStartup = self.network.gyrid_up_since
                m.uptime.systemStartup = self.network.host_up_since
                self.sendMsg(m, await_ack=False)

    def pushCache(self):
        """
        Push trough the cached data. Clears the cache afterwards.
        """
        if not self.factory.cache.closed:
            self.factory.cache.flush()
            self.factory.cache.close()

        self.factory.cache = open(self.factory.cache_file, 'rb')

        if self.factory.config['enable_cache']:
            read = self.factory.cache.read(2)
            while read:
                bts = struct.unpack('!H', read)[0]
                msg = proto.Msg.FromString(self.factory.cache.read(bts))
                self.sendMsg(msg)
                read = self.factory.cache.read(2)

        self.factory.cache.close()
        self.clearCache()

    def clearCache(self):
        """
        Clears the cache file.
        """
        if not self.factory.cache.closed:
            self.factory.cache.flush()
            self.factory.cache.close()

        self.factory.cache = open(self.factory.cache_file, 'wb')
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

        self.config = {'enable_rssi': False,
                       'enable_sensor_mac': True,
                       'enable_cache': True,
                       'enable_uptime': False,
                       'enable_state_scanning': False,
                       'enable_state_inquiry': False,
                       'enable_state_frequency': False,
                       'enable_state_antenna': False}

        self.connected = False
        self.cache_full = False
        self.cache_file = '/var/tmp/gyrid-network.cache'
        self.cache_maxsize = self.network.config.get_value('network_cache_limit')
        self.cache = open(self.cache_file, 'ab')
        self.ackmap = AckMap(self)

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

        self.config['enable_data_transfer'] = False
        self.config['enable_keepalive'] = -1

        self.cachesize_loop.start(10)
        try:
            self.keepalive_loop.stop()
        except AssertionError:
            pass

    def checkCacheSize(self):
        """
        Check the size of the cache and disable caching when full.
        """
        if not self.cache.closed:
            self.cache.flush()

        if os.path.isfile(self.cache_file) and \
            os.path.getsize(self.cache_file) > (self.cache_maxsize * 1048576):
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

    def buildMsg(self, data):
        """
        Parse the Gyrid data into the corresponding message.

        @param   data   The data to parse.
        @return         A message object.
        """
        def procHwid(data):
            """
            Convert given hardware id to the corresponding bytestring.
            """
            return binascii.a2b_hex(data.strip().replace(':','').lower())

        c = self.config

        if data.startswith('SIGHT_CELL') or data.startswith('CACHE_CELL'):
            m = proto.Msg()
            m.type = m.Type_BLUETOOTH_DATAIO
            d = m.bluetooth_dataIO
            if data.startswith('CACHE_CELL'): m.cached = True
            data = dict(zip(['type', 'sensor_mac', 'timestamp', 'mac',
                'deviceclass', 'move'], data.split(',')))
            d.timestamp = float(data['timestamp'])
            d.hwid = procHwid(data['mac'])
            d.deviceclass = int(data['deviceclass'])
            d.move = d.Move_IN if data['move'] == 'in' else d.Move_OUT
            if c['enable_sensor_mac']: d.sensorMac = procHwid(data['sensor_mac'])
            return m
            
        elif (data.startswith('SIGHT_RSSI') or data.startswith('CACHE_RSSI')) \
                and self.config['enable_rssi']:
            m = proto.Msg()
            m.type = m.Type_BLUETOOTH_DATARAW
            d = m.bluetooth_dataRaw
            if data.startswith('CACHE_RSSI'): m.cached = True
            data = dict(zip(['type', 'sensor_mac', 'timestamp', 'mac', 'rssi'],
                data.split(',')))
            d.timestamp = float(data['timestamp'])
            d.hwid = procHwid(data['mac'])
            d.rssi = int(data['rssi'])
            if c['enable_sensor_mac']: d.sensorMac = procHwid(data['sensor_mac'])
            return m

        elif data.startswith('WIFI_IO') or data.startswith('CWIFI_IO'):
            m = proto.Msg()
            m.type = m.Type_WIFI_DATAIO
            d = m.wifi_dataIO
            if data.startswith('C'): m.cached = True
            data = dict(zip(['type', 'sensor_mac', 'timestamp', 'hwid',
                'devtype', 'move'], data.split(',')))
            d.timestamp = float(data['timestamp'])
            d.hwid = procHwid(data['hwid'])
            if data['devtype'] == 'ACP':
                d.type = d.Type_ACCESSPOINT
            elif data['devtype'] == 'DEV':
                d.type = d.Type_DEVICE
            d.move = d.Move_IN if data['move'] == 'in' else d.Move_OUT
            if c['enable_sensor_mac']: d.sensorMac = procHwid(data['sensor_mac'])
            return m

        elif (data.startswith('WIFI_RAW') or data.startswith('CWIFI_RAW')) \
                and self.config['enable_rssi']: #FIXME: enable_raw
            m = proto.Msg()
            m.type = m.Type_WIFI_DATARAW
            w = m.wifi_dataRaw
            if data.startswith('C'): m.cached = True
            data = dict(zip(['type', 'sensor_mac', 'timestamp', 'freq', 'type', 'subtype', 'hwid1', 'hwid2', 'ssi', 'retry', 'pw_mgmt', 'extra'],
                data.split(',')))

            w.frametype = {'data': w.FrameType_DATA,
                           'ctrl': w.FrameType_CTRL,
                           'mgmt': w.FrameType_MGMT}[data['type']]

            if w.frametype == w.FrameType_DATA:
                w.data.from_ds = 'from-ds' in data['subtype']
                w.data.to_ds = 'to-ds' in data['subtype']

            elif w.frametype == w.FrameType_CTRL:
                if data['subtype'] == 'pspoll':
                    w.ctrl.subType  = w.ctrl.SubType_PSPOLL
                else:
                    w.ctrl.subType  = w.ctrl.SubType_OTHER

            elif w.frametype == w.FrameType_MGMT:
                s = w.mgmt
                s.subType = {'beacon': s.SubType_BEACON,
                             'proberesp': s.SubType_PROBERESP,
                             'probereq': s.SubType_PROBEREQ,
                             'deauth': s.SubType_DEAUTH,
                             'disas': s.SubType_DISAS,
                             'atim': s.SubType_ATIM,
                             'assoreq': s.SubType_ASSOREQ,
                             'assoresp': s.SubType_ASSORESP,
                             'reassoreq': s.SubType_REASSOREQ,
                             'reassoresp': s.SubType_REASSORESP}[data['subtype']]

                if s.subType == s.SubType_BEACON:
                    if data['extra'] == 'ESS':
                        s.beacon.type = s.beacon.Type_ESS
                    elif data['extra'] == 'IBSS':
                        s.beacon.type = s.beacon.Type_IBSS

                elif s.subType == s.SubType_PROBEREQ:
                    s.probeReq.hSsid = binascii.a2b_hex(data['extra'])

            w.timestamp = float(data['timestamp'])
            w.frequency = int(data['freq'])
            w.ssi = int(data['ssi'])
            w.hwid1 = procHwid(data['hwid1'])
            w.hwid2 = procHwid(data['hwid2'])
            if data['retry']: w.retry = True
            if data['pw_mgmt']: w.pw_mgmt = True
            if c['enable_sensor_mac']: w.sensorMac = procHwid(data['sensor_mac'])
            return m

        elif data.startswith('STATE') and ('new_inquiry' in data) and \
            self.config['enable_state_inquiry']:
            data = dict(zip(['type', 'hwType', 'sensor_mac', 'timestamp', 'subtype', 'duration'],
                data.split(',')))
            m = proto.Msg()
            m.type = m.Type_BLUETOOTH_STATE_INQUIRY
            d = m.bluetooth_stateInquiry
            d.timestamp = float(data['timestamp'])
            d.duration = float(data['duration'])
            if c['enable_sensor_mac']: d.sensorMac = procHwid(data['sensor_mac'])
            return m

        elif data.startswith('STATE') and ('frequency' in data) and \
            self.config['enable_state_frequency']:
            data = dict(zip(['type', 'hwType', 'sensor_mac', 'timestamp', 'subtype', 'frequency'],
                data.split(',')))
            m = proto.Msg()
            m.type = m.Type_WIFI_STATE_FREQUENCY
            d = m.wifi_stateFrequency
            d.timestamp = float(data['timestamp'])
            if c['enable_sensor_mac']: d.sensorMac = procHwid(data['sensor_mac'])
            d.frequency = int(data['frequency'])
            return m

        elif data.startswith('STATE') and ('antenna_rotation' in data) and \
            self.config['enable_state_antenna']:
            data = dict(zip(['type', 'hwType', 'sensor_mac', 'timestamp', 'subtype', 'angle'],
                data.split(',')))
            m = proto.Msg()
            m.type = m.Type_STATE_ANTENNA
            d = m.stateAntenna
            d.timestamp = float(data['timestamp'])
            if c['enable_sensor_mac']: d.sensorMac = procHwid(data['sensor_mac'])
            d.angle = int(data['angle'])
            return m

        elif data.startswith('STATE') and ('_scanning' in data) and \
            self.config['enable_state_scanning']:
            data = dict(zip(['type', 'hwtype', 'sensor_mac', 'timestamp', 'info'],
                data.split(',')))
            m = proto.Msg()
            m.type = m.Type_STATE_SCANNING
            d = m.stateScanning
            d.timestamp = float(data['timestamp'])
            d.type = d.Type_STARTED if data['info'] == 'started_scanning' else d.Type_STOPPED
            if c['enable_sensor_mac']: d.sensorMac = procHwid(data['sensor_mac'])
            if data['hwtype'] == 'bluetooth': d.hwType = d.HwType_BLUETOOTH
            if data['hwtype'] == 'wifi': d.hwType = d.HwType_WIFI
            return m

        elif data.startswith('INFO'):
            data = dict(zip(['type', 'timestamp', 'info'],
                data.split(',')))
            m = proto.Msg()
            m.type = m.Type_INFO
            d = m.info
            d.timestamp = float(data['timestamp'])
            d.info = data['info']
            return m

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
        self.ackmap.stopChecker()

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
