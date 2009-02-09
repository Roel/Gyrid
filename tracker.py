#!/usr/bin/python

import os
import sys
import bluetooth
import time

import daemon

LOGFILE = '/home/roel/Desktop/bluetooth.log'
LOCKFILE = '/home/roel/Desktop/lock'

class Main(daemon.Daemon):
    def __init__(self, lockfile, logfile):
        daemon.Daemon.__init__(self, lockfile)
        self.logfile = open(logfile, 'a')

    def write(self, timestamp, mac_address, device_class):
        self.logfile.write(",".join([str(timestamp),
                                     str(mac_address),
                                     str(device_class)]))
        self.logfile.write("\n")

    def run(self):
        discoverer = Discoverer(main)
        discoverer.find_devices(flush_cache=True, lookup_names=False, duration=20)

        while not discoverer.done:
            discoverer.process_event()

class Discoverer(bluetooth.DeviceDiscoverer):
    """ Subclassing DeviceDiscoverer to implement action after discovering
    a new device """

    def __init__(self, main):
        bluetooth.DeviceDiscoverer.__init__(self)
        self.main = main

    def pre_inquiry(self):
        self.done = False

    def device_discovered(self, address, device_class, name):
        """ Called when discovered a new device, print its address """
        tijd = str(time.time())
        self.main.write(tijd[:tijd.find('.')], address, device_class)

    def inquiry_complete(self):
        #loop: restart if complete
        self.find_devices(flush_cache=True, lookup_names=False, duration=20)

if __name__ == '__main__':
    main = Main(LOCKFILE, LOGFILE)
    if len(sys.argv) == 2:
        if 'start' == sys.argv[1]:
            main.start()
        elif 'stop' == sys.argv[1]:
            main.stop()
        elif 'restart' == sys.argv[1]:
            main.restart()
        else:
            print "Unknown command"
            sys.exit(2)
        sys.exit(0)
    else:
        print "usage: %s start|stop|restart" % sys.argv[0]
        sys.exit(2)    
