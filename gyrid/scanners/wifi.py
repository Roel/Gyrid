#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2013  Roel Huybrechts
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
Module implementing the WiFi scanning functionality.
"""

import dbus
import dbus.mainloop.glib
import struct
import time

import scapy.all

from gyrid import core, logger
import wigy


class WiFi(core.ScanProtocol):
    """
    WiFi protocol definition.
    """
    def __init__(self, mgr):
        """
        Initialisation.

        @param   mgr   Reference to ScanManager instance.
        """
        core.ScanProtocol.__init__(self, mgr)

        self.mgr._dbus_systembus.add_signal_receiver(self.hardware_added,
                bus_name="org.freedesktop.NetworkManager",
                signal_name="DeviceAdded")

        self.frequencies = [2412, 2417, 2422, 2427, 2432, 2437, 2442, 2447,
                            2452, 2457, 2462, 2467, 2472, 5180, 5200, 5220,
                            5240, 5260, 5280, 5300, 5320, 5500, 5520, 5540,
                            5560, 5580, 5600, 5620, 5640, 5660, 5680, 5700,
                            5745, 5765, 5785, 5805, 5825]

        self.frequencies = [2412, 2417, 2422, 2427, 2432, 2437, 2442, 2447,
                            2452, 2457, 2462, 2467, 2472]


        self.radiotap_fields = [(2**0, 'tsft', 8, 'Q'),
                                (2**1, 'flags', 1, 'B'),
                                (2**2, 'rate', 1, 'B'),
                                (2**3, 'channel_freq', 2, 'H'),
                                (2**3, 'channel_type', 2, '2B'),
                                (2**4, 'fhss', 2, '2B'),
                                (2**5, 'ant_signal_dbm', 1, 'b'),
                                (2**6, 'ant_noise_dbm', 1, 'b'),
                                (2**7, 'lock_quality', 2, 'H'),
                                (2**8, 'tx_attenuation', 2, 'H'),
                                (2**9, 'tx_attenuation_db', 2, 'H'),
                                (2**10, 'tx_power_dbm', 1, 'b'),
                                (2**11, 'antenna', 1, 'B'),
                                (2**12, 'ant_signal_db', 1, 'B'),
                                (2**13, 'ant_noise_db', 1, 'B'),
                                (2**14, 'rx_flags', 2, 'H')]

        self.scanners = {}
        self.loggers = {}
        self.initialise_hardware()

    def initialise_hardware(self):
        """
        Initialise the WiFi hardware already present on the system.
        """
        o = self.mgr._dbus_systembus.get_object('org.freedesktop.NetworkManager',
                '/org/freedesktop/NetworkManager')
        for dev in dbus.Interface(o, "org.freedesktop.NetworkManager").GetDevices():
            self.hardware_added(dev)

    def hardware_added(self, path):
        """
        Called when a WiFi adapter is added to the system.

        @param   path   The path of the adapter, as specified by DBus.
        """
        device_obj = self.mgr._dbus_systembus.get_object("org.freedesktop.NetworkManager", path)
        prop_iface = dbus.Interface(device_obj, "org.freedesktop.DBus.Properties")
        props = prop_iface.GetAll("org.freedesktop.NetworkManager.Device")
        iface = str(props['Interface'])

        if props['DeviceType'] == 2:
            wprops = prop_iface.GetAll("org.freedesktop.NetworkManager.Device.Wireless")
            self.mgr.debug("Found WiFi adapter with address %s" % wprops['PermHwAddress'])
            if props['Managed'] == 0: # scan only with unmanaged devices
                scanner = WiFiScanner(self.mgr, self, props, wprops, path)
                self.scanners[scanner.mac] = scanner
            elif props['Managed'] == 1:
                self.mgr.log_info("Ignoring WiFi adapter %s (managed by NetworkManager)" \
                    % wprops['PermHwAddress'])
                self.mgr.blacklist.add(wprops['PermHwAddress'])

    def valid(self, addr):
        """
        Check the validity of the given MAC address. In casu, valid means the address is not
        00:00:00:00:00:00, and it is both unicast and globally unique.

        @param   addr   The MAC address to check, in colon-separated format.
        """
        valid = True
        if addr == "00:00:00:00:00:00":
            valid = False
            return valid
        if int(addr.split(':')[0], 16) & 0b1 == 0b1:
            valid = False
        elif int(addr.split(':')[0], 16) & 0b10 == 0b10:
            valid = False
        return valid

    def multicast(self, addr):
        """
        Check if the given MAC address is multicast.

        @param   addr   The MAC address to check, in colon-separated format.
        @return         True if it is a multicast address, False if it is a unicast address.
        """
        return int(addr.split(':')[0], 16) & 0b1 == 0b1


class WiFiScanner(core.Scanner):
    """
    WiFi scanner implementation.
    """
    def __init__(self, mgr, protocol, device, wifidevice, path):
        """
        Initialisation of a WiFi adapter for scanning.

        @param   mgr          Reference to ScanManager instance.
        @param   protocol     Reference to WiFi ScanProtocol.
        @param   device       DBus interface for the NetworkManager device.
        @param   wifidevice   DBus interface for the NetworkManager wireless device.
        @param   path         DBus path of the NetworkManager device.
        """
        core.Scanner.__init__(self, mgr, protocol)
        self.v = self.protocol.valid

        self.mac = wifidevice['PermHwAddress']
        self.iface = str(device['Interface'])
        self.running = True
        self.fcs_support_logged = False

        self.frequencies = self.protocol.frequencies[:]

        try:
            wigy.set_status(self.iface, 0)
            wigy.set_mode(self.iface, wigy.MODE_ID['Monitor'])
            wigy.set_status(self.iface, 1)
        except IOError, e:
            self.mgr.debug("Failed to initialise WiFi adapter %s: %s" % (self.mac, e))
            self.mgr.main.log_error("Failed to initialise WiFi adapter %s: %s" % (self.mac, e), 'Error')
        else:
            self.start_scanning()
            self.loop_frequencies()


    @core.threaded
    def loop_frequencies(self):
        """
        Loop over all available WiFi frequencies with a one second interval.
        """
        cnt = 0
        freq = 0
        duration = 1
        freqs_done = []
        while self.running and not self.mgr.main.stopping:
            if len(self.frequencies) == 0:
                self.running = False
            elif cnt >= len(self.frequencies):
                cnt = 0
                self.mgr.net_send_line("STATE,wifi,%s,%0.3f,frequency_loop,%i,%s" %
                    (self.mac.replace(':','').lower(), time.time(), duration*1000, ";".join(
                        str(i) for i in freqs_done)))
                freqs_done[:] = []
            else:
                try:
                    if cnt < len(self.frequencies):
                        freq = self.frequencies[cnt]
                        wigy.set_frequency(self.iface, freq)
                        self.mgr.debug("%s: Frequency set to %i Hz" % (self.mac, freq))
                        freqs_done.append(freq)
                        cnt += 1
                except IOError:
                    self.mgr.debug("%s: Frequency of %i Hz is not supported" % (self.mac,
                        self.frequencies[cnt]))
                    self.mgr.main.log_error("%s: Frequency of %i Hz is not supported" % (self.mac,
                        self.frequencies[cnt]), 'Warning')
                    self.frequencies.pop(cnt)
                else:
                    if self.running:
                        self.mgr.net_send_line("STATE,wifi,%s,%0.3f,frequency,%i,%i" %
                            (self.mac.replace(':','').lower(), time.time(), freq, duration*1000))
                        time.sleep(duration)

    @core.threaded
    def start_scanning(self):
        """
        Start scanning with this WiFi adapter.
        """
        self.mgr.log_info("Started scanning with WiFi adapter %s" % self.mac)
        self.mgr.net_send_line("STATE,wifi,%s,%0.3f,started_scanning" % (
            self.mac.replace(':',''), time.time()))

        def v(addr):
            return self.protocol.valid(addr)

        def h(data, force=False):
            if data == "ff:ff:ff:ff:ff:ff":
                return "ff"
            elif data == None:
                return "00"
            else:
                return self.mgr.privacy_process(data, force).replace(':', '')

        def f(fn, timestamp, addr):
            if addr and v(addr):
                return fn(timestamp, h(addr))

        def devraw(timestamp, sensorMac, addr, frequency, ssi):
            if addr and v(addr):
                _logger_devraw.write(timestamp, frequency, h(addr), ssi)
                self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_DEVRAW',
                    timestamp, sensorMac, h(addr), frequency, ssi]))

        def process(pkt):
            """
            Process a captured packet.
            """
            timestamp = time.time()
            if pkt.haslayer(scapy.all.RadioTap):
                pkt_radio = pkt.getlayer(scapy.all.RadioTap)
                
                radiotap_values = {}

                offset = 0
                for i in self.protocol.radiotap_fields:
                    if pkt_radio.fields['present'] & i[0] == i[0]:
                        offset += offset % i[2] # byte padding
                        radiotap_values[i[1]] = struct.unpack_from('%ix%s' % (offset, i[3]),
                            pkt_radio.fields['notdecoded'])[0]
                        offset += i[2]

                if 'flags' in radiotap_values:
                    fl = radiotap_values['flags']
                    if fl & 0b10000 == 0b10000 and fl & 0b1000000 == 0b1000000:
                        return # we don't process packets that are known to be bad
                    elif fl & 0b10000 != 0b10000:
                        if not self.fcs_support_logged:
                            self.fcs_support_logged = True
                            self.mgr.main.log_error("%s: FCS not supported" % self.mac, 'Warning')

                if 'rx_flags' in radiotap_values and radiotap_values['rx_flags'] & 0b10 == 0b10:
                    self.mgr.debug("%s: Bad PLCP packet received" % self.mac)

            if pkt.haslayer(scapy.all.Dot11):
                d11 = pkt.getlayer(scapy.all.Dot11)
                fcfield = d11.sprintf('%FCfield%')

                if d11.addr1 and (True in (d11.addr1.upper().startswith(b) for b in self.mgr.blacklist)):
                    return

                if d11.addr2 and (True in (d11.addr2.upper().startswith(b) for b in self.mgr.blacklist)):
                    return

                retry = ''
                if 'retry' in fcfield:
                    retry = 'R'

                frequency = radiotap_values.get('channel_freq', '')
                ssi = radiotap_values.get('ant_signal_dbm', '')

                pw_mgt = ''
                if 'pw-mgt' in fcfield:
                    pw_mgt = 'P'
                if 'pw-mgt' in fcfield and d11.addr2:
                    f(_logger_dev.update_device, timestamp, d11.addr2)

                if d11.type & 0b10 == 0b10: # data frame
                    if 'from-DS' in fcfield and 'to-DS' in fcfield:
                        _rawlogger.write(timestamp, frequency, 'DATA', 'from-ds;to-ds',
                            h(d11.addr1), h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'data', 'from-ds;to-ds', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_acp.update_device, timestamp, d11.addr2)
                    elif 'from-DS' in fcfield:
                        _rawlogger.write(timestamp, frequency, 'DATA', 'from-ds', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'data', 'from-ds', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_acp.update_device, timestamp, d11.addr2)
                    elif 'to-DS' in fcfield:
                        _rawlogger.write(timestamp, frequency, 'DATA', 'to-ds', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'data', 'to-ds', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_dev.update_device, timestamp, d11.addr2)
                        devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif 'from-DS' not in fcfield and 'to-DS' not in fcfield:
                        _rawlogger.write(timestamp, frequency, 'DATA', '', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'data', '', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_dev.update_device, timestamp, d11.addr2)
                        devraw(timestamp, self.mac, d11.addr2, frequency, ssi)

                elif d11.type & 0b01 == 0b01: # control frame
                    if d11.subtype == 10: # PS-Poll
                        _rawlogger.write(timestamp, frequency, 'CTRL', 'pspoll', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'ctrl', 'pspoll', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_dev.update_device, timestamp, d11.addr2)
                        devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    else:
                        _rawlogger.write(timestamp, frequency, 'CTRL', '', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'ctrl', '', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_acp.seen_device, timestamp, d11.addr2)
                        if f(_logger_dev.seen_device, timestamp, d11.addr2):
                            devraw(timestamp, self.mac, d11.addr2, frequency, ssi)

                elif d11.type & 0b00 == 0b00: # management frame
                    if pkt.haslayer(scapy.all.Dot11Beacon):
                        tpe = d11.getlayer(scapy.all.Dot11Beacon).sprintf("%cap%")
                        if 'IBSS' in tpe:
                            tpe = 'IBSS'
                            f(_logger_dev.update_device, timestamp, d11.addr2)
                            devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                        elif 'ESS' in tpe:
                            tpe = 'ESS'
                            f(_logger_acp.update_device, timestamp, d11.addr2)
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'beacon', h(d11.addr1),
                            h(d11.addr2), ssi, retry, tpe)
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'beacon', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, tpe]))
                    elif pkt.haslayer(scapy.all.Dot11ProbeResp):
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'proberesp', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'proberesp', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_acp.seen_device, timestamp, d11.addr2)
                        if f(_logger_dev.seen_device, timestamp, d11.addr2):
                            devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif pkt.haslayer(scapy.all.Dot11ProbeReq):
                        elt = d11.getlayer(scapy.all.Dot11Elt)
                        ssid = ''
                        if elt.fields['ID'] == 0:
                            ssid = elt.fields['info']
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'probereq', h(d11.addr1),
                            h(d11.addr2), ssi, retry, h(ssid, force=True))
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'probereq', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, h(ssid, force=True)]))
                        f(_logger_dev.update_device, timestamp, d11.addr2)
                        devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif pkt.haslayer(scapy.all.Dot11Deauth): 
                        reason = pkt.getlayer(scapy.all.Dot11Deauth).fields.get('reason', '')
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'deauth', h(d11.addr1),
                            h(d11.addr2), ssi, retry, reason)
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'deauth', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, reason]))
                        f(_logger_acp.seen_device, timestamp, d11.addr2)
                        if f(_logger_dev.seen_device, timestamp, d11.addr2):
                            devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif pkt.haslayer(scapy.all.Dot11Disas): 
                        reason = pkt.getlayer(scapy.all.Dot11Disas).fields.get('reason', '')
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'disas', h(d11.addr1),
                            h(d11.addr2), ssi, retry, reason)
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'disas', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, reason]))
                        f(_logger_acp.seen_device, timestamp, d11.addr2)
                        if f(_logger_dev.seen_device, timestamp, d11.addr2):
                            devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif pkt.haslayer(scapy.all.Dot11ATIM):
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'atim', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'atim', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_dev.update_device, timestamp, d11.addr2)
                        devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif pkt.haslayer(scapy.all.Dot11AssoReq):
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'assoreq', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'assoreq', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_dev.update_device, timestamp, d11.addr2)
                        devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif pkt.haslayer(scapy.all.Dot11AssoResp):
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'assoresp', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'assoresp', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_acp.seen_device, timestamp, d11.addr2)
                    elif pkt.haslayer(scapy.all.Dot11ReassoReq):
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'reassoreq', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'reassoreq', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_dev.update_device, timestamp, d11.addr2)
                        devraw(timestamp, self.mac, d11.addr2, frequency, ssi)
                    elif pkt.haslayer(scapy.all.Dot11ReassoResp):
                        _rawlogger.write(timestamp, frequency, 'MGMT', 'reassoresp', h(d11.addr1),
                            h(d11.addr2), ssi, retry, '')
                        self.mgr.net_send_line(','.join(str(i) for i in ['WIFI_RAW', self.mac, timestamp,
                            frequency, 'mgmt', 'reassoresp', h(d11.addr1), h(d11.addr2), ssi,
                            retry, pw_mgt, '']))
                        f(_logger_acp.seen_device, timestamp, d11.addr2)

        def stoppercheck(pkt):
            """
            Method used to stop the WiFi sniffing when we are shutting down.
            """
            return self.mgr.main.stopping

        if self.mac not in self.protocol.loggers:
            _rawlogger = logger.WiFiRawLogger(self.mgr, self.mac)
            _logger_devraw = logger.WiFiDevRawLogger(self.mgr, self.mac)
            _logger_dev = logger.WiFiLogger(self.mgr, self.mac, 'DEV')
            _logger_acp = logger.WiFiLogger(self.mgr, self.mac, 'ACP')
            self.protocol.loggers[self.mac] = (_rawlogger, _logger_devraw, _logger_dev, _logger_acp)
        else:
            _rawlogger, _logger_devraw, _logger_dev, _logger_acp = self.protocol.loggers[self.mac]

        _logger_dev.start()
        _logger_acp.start()
        stations = {}
        try:
            scapy.all.sniff(iface=self.iface, prn=process, store=0, stop_filter=stoppercheck)
        except IOError:
            pass

        self.running = False
        try:
            wigy.set_status(self.iface, 0)
        except IOError:
            pass
        _logger_dev.stop()
        _logger_acp.stop()
        self.mgr.log_info("Stopped scanning with WiFi adapter %s" % self.mac)
        self.mgr.net_send_line("STATE,wifi,%s,%0.3f,stopped_scanning" % (
            self.mac.replace(':',''), time.time()))
