#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner.
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

import dbus
import dbus.mainloop.glib
import struct
import time

import scapy.all
import pcap

from gyrid import core, logger, tools
import gyrid.tools.macvendor
import wigy

class WiFi(core.ScanProtocol):
    def __init__(self, mgr):
        core.ScanProtocol.__init__(self, mgr)

        self.mgr._dbus_systembus.add_signal_receiver(self.hardware_added,
                bus_name="org.freedesktop.NetworkManager",
                signal_name="DeviceAdded")

        self.frequencies = [2412, 2417, 2422, 2427, 2432, 2437, 2442, 2447,
                            2452, 2457, 2462, 2467, 2472, 5180, 5200, 5220,
                            5240, 5260, 5280, 5300, 5320, 5500, 5520, 5540,
                            5560, 5580, 5600, 5620, 5640, 5660, 5680, 5700,
                            5745, 5765, 5785, 5805, 5825]

        self.scanners = {}
        self.initialise_hardware()

    def initialise_hardware(self):
        o = self.mgr._dbus_systembus.get_object('org.freedesktop.NetworkManager',
                '/org/freedesktop/NetworkManager')
        for dev in dbus.Interface(o, "org.freedesktop.NetworkManager").GetDevices():
            self.hardware_added(dev)

    def hardware_added(self, path):
        device_obj = self.mgr._dbus_systembus.get_object("org.freedesktop.NetworkManager", path)
        prop_iface = dbus.Interface(device_obj, "org.freedesktop.DBus.Properties")
        props = prop_iface.GetAll("org.freedesktop.NetworkManager.Device")
        iface = str(props['Interface'])
        print "devicetype", props['DeviceType']
        print "managed", props['Managed']
        print "udi", props['Udi']
        print "interface", props['Interface']

        if props['DeviceType'] == 2:
            wprops = prop_iface.GetAll("org.freedesktop.NetworkManager.Device.Wireless")
            print wprops['PermHwAddress']

            scanner = WiFiScanner(self.mgr, self, props, wprops, path)
            self.scanners[scanner.mac] = scanner

class MACAddress(object):
    def __init__(self, bytes):
        self.bytes = bytes

    def isMulticast(self):
        return bool(self.bytes[0] & 0b1)

    def isUnique(self):
        return not self.bytes[0] & 0b10

    def __str__(self):
        return ':'.join(['%02x' % i for i in self.bytes])

class PktParser(object):
    def parse(self, pktlen, pkt):
        if pktlen < self.minimumLength:
            raise ValueError

        r = {}
        for f in self.fmt:
            if self.fmt[f][0] == '':
                ud = struct.unpack_from(str(pktlen) + 'B', pkt)
            else:
                ud = struct.unpack_from(self.fmt[f][0], pkt)
            if len(ud) == 1:
                v = ud[0]
            else:
                v = ud
            r[f] = (v, self.fmt[f][1])
            try:
                r[f] = self.__getattribute__(f)(r[f][0])
            except AttributeError:
                pass
        return r

class RadioTap(PktParser):
    def __init__(self):
        self.minimumLength = 34

        self.fmt = { 'datarate': ('17xb', '500 Kbps'),
                     'frequency': ('18xh', 'Hz'),
                     'ssi': ('22xb', 'dBm') }

    def datarate(self, v):
        return (v*0.5, 'Mbps')

class Dot11(PktParser):
    def __init__(self):
        self.minimumLength = 34 + 2

        self.types = { 0b00: 'Management',
                       0b10: 'Control',
                       0b01: 'Data',
                       0b11: 'Reserved' }

        self.allflags = ['tods', 'fromds', 'morefragm', 'retry', 'pwrmgmt', 'moredata', 'protected', 'order']

        self.fmt = { 'type': ('34xB', ''),
                     'flags' : ('34x1xB', ''),
                     'fcs_matches' : ('', '')}

    def fcs_matches(self, v):
        fcs = ''.join(['%02x' % i for i in v[-4:]])
        import binascii, array
        cs = binascii.crc32(array.array('B', v[34:-4]))
        print '%x' % cs
        return fcs

    def type(self, v):
        return self.types[((v|0b11110011)^0b11110011)>>2]

    def flags(self, v):
        r = []
        for i in range(len(self.allflags)-1):
            if v & 2**i:
                r.append(self.allflags[i])
        return r

class ManagementFrame(PktParser):
    def __init__(self):
        self.minimumLength = 34 + 2 + 2 + (3*6) + 2 + 4

        self.fmt = { 'subtype' : ('34xB', ''),
                     'addr1' : ('34x1x3x6B', ''),
                     'addr2' : ('34x1x3x6x6B', ''),
                     'addr3' : ('34x1x3x6x6x6B', '') }

    def subtype(self, v):
        return bin(((v|0b00001111)^0b00001111)>>4)

    def addr1(self, v):
        m = MACAddress(v)
        return str(m)
    
    def addr2(self, v):
        m = MACAddress(v)
        return str(m)

    def addr3(self, v):
        m = MACAddress(v)
        return str(m)
    
def valid(addr):
    valid = True
    if addr == "00:00:00:00:00:00":
        valid = False
    if int(addr.split(':')[0], 16) & 0b1:
        valid = False
    if int(addr.split(':')[0], 16) & 0b10:
        valid = False
    return valid

def multicast(addr):
    return int(addr.split(':')[0], 16) & 0b1

class WiFiScanner(core.Scanner):
    def __init__(self, mgr, protocol, device, wifidevice, path):
        core.Scanner.__init__(self, mgr, protocol)

        self.mac = wifidevice['PermHwAddress']
        self.iface = str(device['Interface'])
        self.running = True
        self.pcap = pcap.pcapObject()

        self.frequencies = self.protocol.frequencies[:]

        self.stations = set()
        self.mobiles = set()

        self.prs_radiotap = RadioTap()
        self.prs_dot11 = Dot11()
        self.prs_mgmt = ManagementFrame()

        if device['Managed'] == 0: #keep our hands off managed devices (these are used for internet access!)
            try:
                wigy.set_status(self.iface, 0)
                wigy.set_mode(self.iface, wigy.MODE_ID['Monitor'])
                wigy.set_status(self.iface, 1)
            except IOError, e:
                self.mgr.debug("Failed to initialise adapter %s: %s" % (self.mac, e))
            else:
                #wigy.set_frequency(self.iface, 2437)
                #self.scan_wifi(iface, wprops['PermHwAddress'])
                self.start_scanning()
                self.loop_frequencies()
            #self.frequency_loop(iface)
        #self.debug("Found WiFi adapter with address %s" %
        #        device.GetProperties()['Address'])

    @core.threaded
    def loop_frequencies(self):
        cnt = 0
        while self.running and not self.mgr.main.stopping:
            if len(self.frequencies) == 0:
                self.running = False
            elif cnt >= len(self.frequencies):
                cnt = 0
            else:
                try:
                    if cnt < len(self.frequencies):
                        wigy.set_frequency(self.iface, self.frequencies[cnt])
                        self.mgr.debug("Frequency set to %i Hz" % self.frequencies[cnt])
                        cnt += 1
                        time.sleep(1)
                except IOError:
                    self.mgr.debug("Frequency of %i Hz is not supported" % self.frequencies[cnt])
                    self.frequencies.pop(cnt)
        print self.stations
        print self.mobiles
        for i in self.mobiles:
            if valid(i):
                print i, tools.macvendor.get_vendor(i)

    @core.threaded
    def start_scanning_pcap(self):
        def process(pktlen, data, timestamp):
            #print pktlen
            #print struct.unpack_from('2xh4bqbbhhb', data)
            #print struct.unpack_from(fmt_radiotap['ssi_dbm'], data)[0]
            try:
                print self.prs_radiotap.parse(pktlen, data)
                d = self.prs_dot11.parse(pktlen, data)
                print d
                if d['type'] == 'Management':
                    print self.prs_mgmt.parse(pktlen, data)
            except ValueError:
                print "Malformed packet"

        self.pcap.open_offline('/tmp/pcap.log')#, 1600, 0, 100)
        #self.pcap.open_live(self.iface, 1600, 0, 100)

        while self.running and not self.mgr.main.stopping:
            self.pcap.dispatch(1, process)

    @core.threaded
    def start_scanning(self):
        import binascii, array
        scapy.all.Dot11.enable_FCS(True)
        def process(pkt):
            #try:
            #print(pkt.__dict__)
            #print pkt.show()
            #print "********************************************"
            if pkt.haslayer(scapy.all.RadioTap):
                pkt_radio = pkt.getlayer(scapy.all.RadioTap)
                
                radiotap_values = {}

                offset = 0
                for i in radiotap_fields:
                    if pkt_radio.fields['present'] & i[0] == i[0]:
                        offset += offset % i[2] # byte padding
                        radiotap_values[i[1]] = struct.unpack_from('%ix%s' % (offset, i[3]), pkt_radio.fields['notdecoded'])[0]
                        offset += i[2]

                if 'flags' not in radiotap_values:
                    return
                else:
                    f = radiotap_values['flags']
                    if f & 0b10000 == 0b10000 and f & 0b1000000 == 0b1000000:
                        print "Bad packet received"
                        return
                    elif f & 0b10000 != 0b10000:
                        print "FCS not supported"

                if 'rx_flags' in radiotap_values and radiotap_values['rx_flags'] & 0b10 == 0b10:
                    print "Bad PLCP packet received"
                
                ssi = '%i' % radiotap_values.get('ant_signal_dbm', '')
                if radiotap_values.get('ant_signal_dbm', -1) >= 0:
                    print pkt_radio.__dict__
                    print radiotap_values

                #fcs_support = pkt_radio.fields['present'] & 0b1 == 0b1
                #if not fcs_support:
                #    self.mgr.debug("Warning: FCS not supported")
            else:
                return

            if pkt.haslayer(scapy.all.Dot11):
                pkt_dot11 = pkt.getlayer(scapy.all.Dot11)
                #print binascii.crc32(array.array('B', pkt_dot11[:len(pkt_dot11)-4]))
                #print pkt_dot11[len(pkt_dot11)-4:]
                #print pkt_dot11.sprintf('%FCfield%')#fields['FCfield'])
                if 'retry' in pkt_dot11.sprintf('%FCfield%'):
                    ssi += " retry"

                if 'pw-mgt' in pkt_dot11.sprintf('%FCfield%') and pkt_dot11.addr2 and valid(pkt_dot11.addr2):
                    if pkt_dot11.addr2 not in self.mobiles:
                        self.mgr.debug("%s is MOBILE based on pwr-mgt %s" % (pkt_dot11.addr2, ssi))
                    else:
                        self.mgr.debug("%s confirmed mobile based on pwr-mgt %s" % (pkt_dot11.addr2, ssi))
                    self.mobiles.add(pkt_dot11.addr2)
                    if pkt_dot11.addr2 in self.stations:
                        self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)

                #if 'MD' in pkt_dot11.sprintf('%FCfield%') and pkt_dot11.addr2 and valid(pkt_dot11.addr2) and multicast(pkt_dot11.addr1) and pkt_dot11.haslayer(scapy.all.Dot11Beacon):
                #    if pkt_dot11.addr2 not in self.stations:
                #        self.mgr.debug("%s is STATION based on more-data %s" % (pkt_dot11.addr2, ssi))
                #    else:
                #        self.mgr.debug("%s confirmed station based on more-data %s" % (pkt_dot11.addr2, ssi))
                #    self.stations.add(pkt_dot11.addr2)
                #    if pkt_dot11.addr2 in self.mobiles:
                #        self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)

                if pkt_dot11.type & 0b10 == 0b10: # data frame
                    timestamp = time.time()
                    #if pkt_dot11.addr1 in self.stations or pkt_dot11.addr1 in self.mobiles:
                    #    self.mgr.debug("%s detected in data frame %s" % (pkt_dot11.addr1, ssi))
                    #    if pkt_dot11.addr1 in self.mobiles:
                    #        _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    #if pkt_dot11.addr2 in self.stations or pkt_dot11.addr2 in self.mobiles:
                    #    self.mgr.debug("%s detected in data frame %s" % (pkt_dot11.addr2, ssi))
                    #    if pkt_dot11.addr2 in self.mobiles:
                    #        _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    #return
                    #print "data frame"
                    #if pkt_dot11.haslayer(scapy.all.IP):
                    #    pkt.getlayer(scapy.all.IP).show()
                    if 'from-DS' in pkt_dot11.sprintf("%FCfield%") and 'to-DS' in pkt_dot11.sprintf("%FCfield%"):
                        #print "from-DS to-DS"
                        #print pkt_dot11.addr1, tools.macvendor.get_vendor(pkt_dot11.addr1)
                        #print pkt_dot11.addr2, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #_logger.update_device(timestamp, pkt_dot11.addr2, -1)
                        #_logger.update_device(timestamp, pkt_dot11.addr1, -1)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.stations:
                                self.mgr.debug("%s is STATION based on 11 data frame %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on 11 data frame %s" % (pkt_dot11.addr1, ssi))
                            self.stations.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.stations:
                                self.mgr.debug("%s is STATION based on 11 data frame %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on 11 data frame %s" % (pkt_dot11.addr2, ssi))
                            self.stations.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                    elif 'from-DS' in pkt_dot11.sprintf("%FCfield%"):
                        #print "from-DS"
                        #print pkt_dot11.addr1, tools.macvendor.get_vendor(pkt_dot11.addr1)
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.stations:
                                self.mgr.debug("%s is STATION based on 10 data frame %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on 10 data frame %s" % (pkt_dot11.addr2, ssi))
                            self.stations.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on 10 data frame %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on 10 data frame %s" % (pkt_dot11.addr1, ssi))
                            self.mobiles.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                            _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    elif 'to-DS' in pkt_dot11.sprintf("%FCfield%"):
                        #print "to-DS"
                        #print pkt_dot11.addr2, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.stations:
                                self.mgr.debug("%s is STATION based on 01 data frame %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on 01 data frame %s" % (pkt_dot11.addr1, ssi))
                            self.stations.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on 01 data frame %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on 01 data frame %s" % (pkt_dot11.addr2, ssi))
                            self.mobiles.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    elif 'from-DS' not in pkt_dot11.sprintf("%FCfield%") and 'to-DS' not in pkt_dot11.sprintf("%FCfield%"):
                        #print " "
                        #print pkt_dot11.addr1, tools.macvendor.get_vendor(pkt_dot11.addr1)
                        #print pkt_dot11.addr2, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on 00 data frame %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on 00 data frame %s" % (pkt_dot11.addr1, ssi))
                            self.mobiles.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                            _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on 00 data frame %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on 00 data frame %s" % (pkt_dot11.addr2, ssi))
                            self.mobiles.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    #print pkt.show()
                    #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr1)
                    #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                    #print pkt_dot11.addr3#, tools.macvendor.get_vendor(pkt_dot11.addr3)
                    #print "**************************************************"
                elif pkt_dot11.type & 0b01 == 0b01: # control frame
                    timestamp = time.time()
                    if pkt_dot11.subtype == 10: # PS-Poll
                        #print pkt_dot11.__dict__
                        #return
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on ps-poll %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on ps-poll %s" % (pkt_dot11.addr2, ssi))
                            self.mobiles.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.stations:
                                self.mgr.debug("%s is STATION based on ps-poll %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on ps-poll %s" % (pkt_dot11.addr1, ssi))
                            self.stations.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)

                    else:
                        if pkt_dot11.addr1 in self.stations or pkt_dot11.addr1 in self.mobiles:
                            self.mgr.debug("%s detected in control frame %s" % (pkt_dot11.addr1, ssi))
                            if pkt_dot11.addr1 in self.mobiles:
                                _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                        if pkt_dot11.addr2 in self.stations or pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s detected in control frame %s" % (pkt_dot11.addr2, ssi))
                            if pkt_dot11.addr2 in self.mobiles:
                                _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                elif pkt_dot11.type & 0b00 == 0b00: # management frame

                    timestamp = time.time()
                    #for i in pkt_dot11.payload:
                    #    print i

                    if pkt.haslayer(scapy.all.Dot11ProbeReq):
                        #print "mgmt frame"
                        #print "probe request"
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on probe request %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on probe request %s" % (pkt_dot11.addr2, ssi))
                            self.mobiles.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    elif pkt.haslayer(scapy.all.Dot11ProbeResp):
                        #print "mgmt frame"
                        #print "probe response"
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        
                        # cant be sure this originates from AP ~ IBSS
                        #if valid(pkt_dot11.addr2):
                        #    if pkt_dot11.addr2 not in self.stations:
                        #        self.mgr.debug("%s is STATION based on probe response %s" % (pkt_dot11.addr2, ssi))
                        #    else:
                        #        self.mgr.debug("%s confirmed station based on probe response %s" % (pkt_dot11.addr2, ssi))
                        #    self.stations.add(pkt_dot11.addr2)
                        #    if pkt_dot11.addr2 in self.mobiles:
                        #        self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on probe response %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on probe response %s" % (pkt_dot11.addr1, ssi))
                            self.mobiles.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                            _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    elif pkt.haslayer(scapy.all.Dot11Deauth) or pkt.haslayer(scapy.all.Dot11Disas):
                        if pkt_dot11.addr1 in self.stations or pkt_dot11.addr1 in self.mobiles:
                            self.mgr.debug("%s detected in mgmt frame %s" % (pkt_dot11.addr1, ssi))
                            if pkt_dot11.addr1 in self.mobiles:
                                _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                        if pkt_dot11.addr2 in self.stations or pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s detected in mgmt frame %s" % (pkt_dot11.addr2, ssi))
                            if pkt_dot11.addr2 in self.mobiles:
                                _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                        print pkt.getlayer(scapy.all.Dot11Deauth).fields['reason']
                    elif pkt.haslayer(scapy.all.Dot11ATIM):
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on atim %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on atim %s" % (pkt_dot11.addr1, ssi))
                            self.mobiles.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                            _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on atim %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on atim %s" % (pkt_dot11.addr2, ssi))
                            self.mobiles.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)

                    elif pkt.haslayer(scapy.all.Dot11AssoReq):
                        #print "mgmt frame"
                        #print "association request"
                        #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.stations:
                                self.mgr.debug("%s is STATION based on association request %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on association request %s" % (pkt_dot11.addr1, ssi))
                            self.stations.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on association request %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on association request %s" % (pkt_dot11.addr2, ssi))
                            self.mobiles.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    elif pkt.haslayer(scapy.all.Dot11AssoResp):
                        #print "mgmt frame"
                        #print "association request"
                        #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.stations:
                                self.mgr.debug("%s is STATION based on association response %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on association response %s" % (pkt_dot11.addr2, ssi))
                            self.stations.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on association response %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on association response %s" % (pkt_dot11.addr1, ssi))
                            self.mobiles.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                            _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    elif pkt.haslayer(scapy.all.Dot11ReassoReq):
                        #print "mgmt frame"
                        #print "reassociation request"
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.stations:
                                self.mgr.debug("%s is STATION based on reassociation request %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on reassociation request %s" % (pkt_dot11.addr1, ssi))
                            self.stations.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on reassociation request %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on reassociation request %s" % (pkt_dot11.addr2, ssi))
                            self.mobiles.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    elif pkt.haslayer(scapy.all.Dot11ReassoResp):
                        #print "mgmt frame"
                        #print "association request"
                        #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        if valid(pkt_dot11.addr2):
                            if pkt_dot11.addr2 not in self.stations:
                                self.mgr.debug("%s is STATION based on reassociation response %s" % (pkt_dot11.addr2, ssi))
                            else:
                                self.mgr.debug("%s confirmed station based on reassociation response %s" % (pkt_dot11.addr2, ssi))
                            self.stations.add(pkt_dot11.addr2)
                            if pkt_dot11.addr2 in self.mobiles:
                                self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        if valid(pkt_dot11.addr1):
                            if pkt_dot11.addr1 not in self.mobiles:
                                self.mgr.debug("%s is MOBILE based on reassociation response %s" % (pkt_dot11.addr1, ssi))
                            else:
                                self.mgr.debug("%s confirmed mobile based on reassociation response %s" % (pkt_dot11.addr1, ssi))
                            self.mobiles.add(pkt_dot11.addr1)
                            if pkt_dot11.addr1 in self.stations:
                                self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                            _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    elif pkt.haslayer(scapy.all.Dot11Beacon):
                        #p = pkt.getlayer(scapy.all.Dot11Elt)
                        #print "beacon"
                        #if p.fields['ID'] == 0:
                        #    print p.fields['info']
                        #print "mgmt frame"
                        #print pkt.show()
                        if 'IBSS' in pkt_dot11.getlayer(scapy.all.Dot11Beacon).sprintf("%cap%"):
                            ssi += ' IBSS'
                            if valid(pkt_dot11.addr2):
                                if pkt_dot11.addr2 not in self.mobiles:
                                    self.mgr.debug("%s is MOBILE based on beacon %s" % (pkt_dot11.addr2, ssi))
                                else:
                                    self.mgr.debug("%s confirmed mobile based on beacon %s" % (pkt_dot11.addr2, ssi))
                                self.mobiles.add(pkt_dot11.addr2)
                                if pkt_dot11.addr2 in self.stations:
                                    self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                                _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                        if 'ESS' in pkt_dot11.getlayer(scapy.all.Dot11Beacon).sprintf("%cap%"):
                            ssi += ' ESS'
                            if valid(pkt_dot11.addr2):
                                if pkt_dot11.addr2 not in self.stations:
                                    self.mgr.debug("%s is STATION based on beacon %s" % (pkt_dot11.addr2, ssi))
                                else:
                                    self.mgr.debug("%s confirmed station based on beacon %s" % (pkt_dot11.addr2, ssi))
                                self.stations.add(pkt_dot11.addr2)
                                if pkt_dot11.addr2 in self.mobiles:
                                    self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print "---"
                #else:
                #    print pkt.show()
                #    print bin(pkt_dot11.type)
                #    print bin(pkt_dot11.subtype)
                #    print "**************************************************"
                    #print bin(pkt_dot11.FCfield)
            #self.debug("From " + str(pkt.payload.fields.get('addr1', None)) + ", to: " + str(pkt.payload.fields.get('addr2', None)) + '. Type ' + bin(pkt.payload.fields.get('type', -1)) + ". Subtype " + bin(pkt.payload.fields.get('subtype', -1)))
            #if pkt.payload.fields.get('type', -1) == 0b01:
            #if 'type' in pkt.payload.fields:
            #    print bin(pkt.payload.fields.get('FCfield', None))
            #    print pkt.payload.get('underlayer', None)
                #print pkt.payload.__dict__
                #print "----"
            #except:
            #    return
            #print pkt.payload



        def stoppercheck(pkt):
            return self.mgr.main.stopping

        radiotap_fields = [(2**0, 'tsft', 8, 'Q'),
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
                           (2**14, 'rx_flags', 2, 'H') ]

        _logger = logger.ScanLogger(self.mgr, self.mac)
        _logger.start()
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
        _logger.stop()

    def stop_scanning(self):
        pass
