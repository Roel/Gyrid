import os
import sys
import bluetooth
import time

import daemon

class Main(daemon.Daemon):
    """
    Main class of the Bluetooth tracker; subclass of daemon for easy
    daemonising.
    """
    def __init__(self, lockfile, logfile):
        """
        Initialistation of the daemon and opening of the logfile.

        @param  lockfile   URL of the lockfile.
        @param  logfile    URL of the logfile.
        """
        daemon.Daemon.__init__(self, lockfile)
        self.logfile_url = logfile
        self.logfile = open(self.logfile_url, 'a')

    def write(self, timestamp, mac_address, device_class):
        """
        Append the parameters to the logfile on a new line and flush the file.

        @param  timestamp      UNIX timestamp.
        @param  mac_address    Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        """
        self.logfile.write(",".join([str(timestamp),
                                     str(mac_address),
                                     str(device_class)]))
        self.logfile.write("\n")
        self.logfile.flush()

    def run(self):
        """
        Called after the daemon gets the (re)start command
        Open the logfile if it's not already open (necessary to be able to
        restart the daemon), and start the Bluetooth discoverer.
        """
        #discoverer = Discoverer(main)

        #while not discoverer.done:
        #    discoverer.process_event()
        if 'logfile' not in self.__dict__:
            self.logfile = open(self.logfile_url, 'a')

        while True:
            tijd = str(time.time())
            self.write(tijd[:tijd.find('.')], '11:22:33:44:55:66', 52400)
            time.sleep(5)

    def stop(self):
        """
        Called when the daemon gets the stop command. Cleanly close the
        logfile and then stop the daemon.
        """
        self.logfile.close()
        del(self.logfile)
        daemon.Daemon.stop(self)

class Discoverer(bluetooth.DeviceDiscoverer):
    """
    Bluetooth discover, this is the device scanner. A few modification have
    been made from the original DeviceDiscoverer.
    """
    def __init__(self, main):
        """
        Initialisation of the DeviceDiscoverer. Store the reference to main and
        start scanning.

        @param  main  Reference to a Main instance.
        """
        bluetooth.DeviceDiscoverer.__init__(self)
        self.main = main
        self.find()

    def find(self):
        """
        Start scanning.
        """
        self.find_devices(flush_cache=True, lookup_names=False, duration=8)

    #FIXME: is this really necessary?
    def pre_inquiry(self):
        self.done = False

    def device_discovered(self, address, device_class, name):
        """
        Called when discovered a new device. Get a UNIX timestamp and call
        the write method of Main to write the timestamp, the address and
        the device_class of the device to the logfile.

        @param  address        Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  name           The name of the Bluetooth device. Since we don't
                                query names, this value will be None.
        """
        tijd = str(time.time())
        self.main.write(tijd[:tijd.find('.')], address, device_class)

    def inquiry_complete(self):
        """
        Called after the inquiry is complete; restart scanning by calling
        find(). We create an endless loop here to continuously scan for
        devices.
        """
        self.find()
