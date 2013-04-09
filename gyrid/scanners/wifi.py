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
import time

import scapy.all

from gyrid import core, logger, tools
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

class WiFiScanner(core.Scanner):
    def __init__(self, mgr, protocol, device, wifidevice, path):
        core.Scanner.__init__(self, mgr, protocol)

        self.mac = wifidevice['PermHwAddress']
        self.iface = str(device['Interface'])
        self.running = True

        self.frequencies = self.protocol.frequencies[:]

        self.stations = set()
        self.mobiles = set()

        if device['Managed'] == 0: #keep our hands off managed devices (these are used for internet access!)
            wigy.set_mode(self.iface, wigy.MODE_ID['Monitor'])
            wigy.set_status(self.iface, 1)
            wigy.set_frequency(self.iface, 2437)
            #self.scan_wifi(iface, wprops['PermHwAddress'])
            self.start_scanning()
            self.loop_frequencies()
            #self.frequency_loop(iface)
        #self.debug("Found WiFi adapter with address %s" %
        #        device.GetProperties()['Address'])

    @core.threaded
    def loop_frequencies(self):
        cnt = 0
        while self.running and self.mgr.main.stopping == False:
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
        
    @core.threaded
    def start_scanning(self):
        def process(pkt):
            #try:
            #print(pkt.payload.__dict__)
            #print pkt.show()
            #print "********************************************"
            if pkt.haslayer(scapy.all.Dot11):
                pkt_dot11 = pkt.getlayer(scapy.all.Dot11)
                if pkt_dot11.type & 0b10 == 0b10: # data frame
                    timestamp = time.time()
                    if pkt_dot11.addr1 in self.stations or pkt_dot11.addr1 in self.mobiles:
                        self.mgr.debug("%s detected in data frame" % pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.mobiles:
                            _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    if pkt_dot11.addr2 in self.stations or pkt_dot11.addr2 in self.mobiles:
                        self.mgr.debug("%s detected in data frame" % pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    return
                    #print "data frame"
                    if pkt_dot11.FCfield & 0b11 == 0b11:
                        #print "from-DS to-DS"
                        #print pkt_dot11.addr1, tools.macvendor.get_vendor(pkt_dot11.addr1)
                        #print pkt_dot11.addr2, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #_logger.update_device(timestamp, pkt_dot11.addr2, -1)
                        #_logger.update_device(timestamp, pkt_dot11.addr1, -1)
                        if pkt_dot11.addr1 not in self.stations:
                            self.mgr.debug("%s is STATION based on 11 data frame" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed station based on 11 data frame" % pkt_dot11.addr1)
                        self.stations.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if pkt_dot11.addr2 not in self.stations:
                            self.mgr.debug("%s is STATION based on 11 data frame" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed station based on 11 data frame" % pkt_dot11.addr2)
                        self.stations.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                    elif pkt_dot11.FCfield & 0b10 == 0b10:
                        #print "from-DS"
                        #print pkt_dot11.addr1, tools.macvendor.get_vendor(pkt_dot11.addr1)
                        if pkt_dot11.addr2 not in self.stations:
                            self.mgr.debug("%s is STATION based on 10 data frame" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed station based on 10 data frame" % pkt_dot11.addr2)
                        self.stations.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        if pkt_dot11.addr1 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on 10 data frame" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed mobile based on 10 data frame" % pkt_dot11.addr1)
                        self.mobiles.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.stations:
                            self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    elif pkt_dot11.FCfield & 0b01 == 0b01:
                        #print "to-DS"
                        #print pkt_dot11.addr2, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        if pkt_dot11.addr1 not in self.stations:
                            self.mgr.debug("%s is STATION based on 01 data frame" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed station based on 01 data frame" % pkt_dot11.addr1)
                        self.stations.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if pkt_dot11.addr2 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on 01 data frame" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed mobile based on 01 data frame" % pkt_dot11.addr2)
                        self.mobiles.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.stations:
                            self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    elif pkt_dot11.FCfield & 0b00 == 0b00:
                        #print " "
                        #print pkt_dot11.addr1, tools.macvendor.get_vendor(pkt_dot11.addr1)
                        #print pkt_dot11.addr2, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        if pkt_dot11.addr1 not in self.stations:
                            self.mgr.debug("%s is MOBILE based on 00 data frame" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed mobile based on 00 data frame" % pkt_dot11.addr1)
                        self.mobiles.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.mobiles:
                            self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if pkt_dot11.addr2 not in self.stations:
                            self.mgr.debug("%s is MOBILE based on 00 data frame" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed mobile based on 00 data frame" % pkt_dot11.addr2)
                        self.mobiles.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                        _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    #print pkt.show()
                    #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr1)
                    #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                    #print pkt_dot11.addr3#, tools.macvendor.get_vendor(pkt_dot11.addr3)
                    #print "**************************************************"
                elif pkt_dot11.type & 0b01 == 0b01: # control frame
                    if pkt_dot11.subtype & 0b1101 == 0b1101:
                        #print "control frame"
                        #print "ack frame"
                        pass
                elif pkt_dot11.type & 0b00 == 0b00: # management frame 
                    timestamp = time.time()
                    if pkt.haslayer(scapy.all.Dot11ProbeReq):
                        #print "mgmt frame"
                        #print "probe request"
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        if pkt_dot11.addr2 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on probe request" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed mobile based on probe request" % pkt_dot11.addr2)
                        self.mobiles.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.stations:
                            self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        _logger.update_device(timestamp, pkt_dot11.addr2, -1)
                    elif pkt.haslayer(scapy.all.Dot11ProbeResp):
                        #print "mgmt frame"
                        #print "probe response"
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        if pkt_dot11.addr2 not in self.stations:
                            self.mgr.debug("%s is STATION based on probe response" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed station based on probe response" % pkt_dot11.addr2)
                        self.stations.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        if pkt_dot11.addr1 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on probe response" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed mobile based on probe response" % pkt_dot11.addr1)
                        self.mobiles.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.stations:
                            self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    elif pkt.haslayer(scapy.all.Dot11AssoReq):
                        #print "mgmt frame"
                        #print "association request"
                        #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt.show()
                        if pkt_dot11.addr1 not in self.stations:
                            self.mgr.debug("%s is STATION based on association request" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed station based on association request" % pkt_dot11.addr1)
                        self.stations.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if pkt_dot11.addr2 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on association request" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed mobile based on association request" % pkt_dot11.addr2)
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
                        if pkt_dot11.addr2 not in self.stations:
                            self.mgr.debug("%s is STATION based on association response" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed station based on association response" % pkt_dot11.addr2)
                        self.stations.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        if pkt_dot11.addr1 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on association response" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed mobile based on association response" % pkt_dot11.addr1)
                        self.mobiles.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.stations:
                            self.mgr.debug("%s is station too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        _logger.update_device(timestamp, pkt_dot11.addr1, -1)
                    elif pkt.haslayer(scapy.all.Dot11ReassoReq):
                        #print "mgmt frame"
                        #print "reassociation request"
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        if pkt_dot11.addr1 not in self.stations:
                            self.mgr.debug("%s is STATION based on reassociation request" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed station based on reassociation request" % pkt_dot11.addr1)
                        self.stations.add(pkt_dot11.addr1)
                        if pkt_dot11.addr1 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr1)
                        if pkt_dot11.addr2 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on reassociation request" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed mobile based on reassociation request" % pkt_dot11.addr2)
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
                        if pkt_dot11.addr2 not in self.stations:
                            self.mgr.debug("%s is STATION based on reassociation response" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed station based on reassociation response" % pkt_dot11.addr2)
                        self.stations.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        if pkt_dot11.addr1 not in self.mobiles:
                            self.mgr.debug("%s is MOBILE based on reassociation response" % pkt_dot11.addr1)
                        else:
                            self.mgr.debug("%s confirmed mobile based on reassociation response" % pkt_dot11.addr1)
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
                        if pkt_dot11.addr2 not in self.stations:
                            self.mgr.debug("%s is STATION based on beacon" % pkt_dot11.addr2)
                        else:
                            self.mgr.debug("%s confirmed station based on beacon" % pkt_dot11.addr2)
                        self.stations.add(pkt_dot11.addr2)
                        if pkt_dot11.addr2 in self.mobiles:
                            self.mgr.debug("%s is mobile too !!!!1111!!!11!!!11!11!!!1111!!" % pkt_dot11.addr2)
                        #print pkt_dot11.addr1#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print pkt_dot11.addr2#, tools.macvendor.get_vendor(pkt_dot11.addr2)
                        #print "---"
                        #_logger.update_device(timestamp, pkt_dot11.addr3, -1)
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

#{'sent_time': 0, 'fields': {'proto': 1L, 'FCfield': 79L, 'subtype': 15L, 'addr4': None, 'addr2': '49:e7:bd:98:bb:1f', 'addr3': None, 'addr1': 'fe:9c:d4:22:4f:22', 'SC': None, 'type': 1L, 'ID': 59848}, 'aliastypes': [<class 'scapy.layers.dot11.Dot11'>], 'post_transforms': [], 'underlayer': <RadioTap  version=0 pad=0 len=26 present=TSFT+Flags+Rate+Channel+dBm_AntSignal+Antenna+b14 notdecoded='\xbf\x87\x0b\x00\x00\x00\x00\x00R\x16q\t\xa0\x00\xd3\x00\x00\x00' |<Dot11  subtype=15L type=Control proto=1L FCfield=to-DS+from-DS+MF+retry+wep ID=59848 addr1=fe:9c:d4:22:4f:22 addr2=49:e7:bd:98:bb:1f addr3=None SC=None addr4=None |<Dot11WEP  iv='\\\x17\x18' keyid=221 wepdata="\x04\x0f\xca\xe6.\xe8xc\x7f\x1b\xf2\xd2\x02@\x05\x04\xf4R\x89q\x8f'\xbf\xdeo/ \x03\xb2\xc8\xdd\xf3o\x94\xb1\xfcn\xed\x15\xd9\xcd\xd1" icv=3123401899 |>>>, 'fieldtype': {'proto': <Field (Dot11).proto>, 'FCfield': <Field (Dot11).FCfield>, 'subtype': <Field (Dot11).subtype>, 'addr4': <Field (Dot11).addr4>, 'addr2': <Field (Dot11).addr2>, 'addr3': <Field (Dot11).addr3>, 'addr1': <Field (Dot11).addr1>, 'SC': <Field (Dot11).SC>, 'type': <Field (Dot11).type>, 'ID': <Field (Dot11).ID>}, 'time': 1364375323.016097, 'initialized': 1, 'overloaded_fields': {}, 'packetfields': [], 'payload': <Dot11WEP  iv='\\\x17\x18' keyid=221 wepdata="\x04\x0f\xca\xe6.\xe8xc\x7f\x1b\xf2\xd2\x02@\x05\x04\xf4R\x89q\x8f'\xbf\xdeo/ \x03\xb2\xc8\xdd\xf3o\x94\xb1\xfcn\xed\x15\xd9\xcd\xd1" icv=3123401899 |>, 'default_fields': {'proto': 0, 'FCfield': 0, 'subtype': 0, 'addr4': '00:00:00:00:00:00', 'addr2': '00:00:00:00:00:00', 'addr3': '00:00:00:00:00:00', 'addr1': '00:00:00:00:00:00', 'SC': 0, 'type': 0, 'ID': 0}}


        def stoppercheck(pkt):
            if self.mgr.main.stopping:
                _logger.stop()
            return self.mgr.main.stopping

        _logger = logger.ScanLogger(self.mgr, self.mac)
        _logger.start()
        stations = {}
        try:
            scapy.all.sniff(iface=self.iface, prn=process, store=0, stop_filter=stoppercheck)
        except IOError:
            _logger.stop()
            #pass

    def stop_scanning(self):
        pass
