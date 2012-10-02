#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner.
# Copyright (C) 2009-2010  Roel Huybrechts
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

import random
import time

import gyrid.discoverer

class Discoverer(gyrid.discoverer.Discoverer):
    """
    Discoverer that 'discovers' fake devices on a random basis.
    Used for stresstesting.
    """
    def __init__(self, mgr, logger, logger_rssi, device_id, mac):
        """
        Initialisation of the Discoverer. Store the reference to the loggers and
        query the necessary configuration options.

        @param  mgr          Reference to a Scanmanger instance.
        @param  logger       Reference to a Logger instance.
        @param  logger_rssi  Reference to a logger instance which records
                               the RSSI values.
        @param  device_id    The ID of the Bluetooth device used for scanning.
        @param  mac          The MAC address of the Bluetooth scanning device.
        """
        gyrid.discoverer.Discoverer.__init__(self, mgr, logger, logger_rssi,
            device_id, mac)

    def init(self):
        """
        Initialise the MAC addresses of the fake devices.

        @return  0 on success, 1 on failure.
        """
        self.macs = [
            "00:23:7A:4F:13:2C", "00:1B:AF:BB:4D:2F", "00:1F:DE:48:32:2A",
            "00:26:68:70:89:E4", "00:16:20:83:F8:4D", "00:1E:A3:AE:E4:D5",
            "00:17:B0:57:14:A7", "00:22:FD:7C:EF:DA", "00:16:DB:32:EC:CD",
            "00:16:B8:5C:B0:A6", "18:86:AC:28:AF:7E", "00:1E:AE:03:E8:C1",
            "00:1D:3B:A4:97:82", "00:0E:07:46:9C:50", "00:60:57:B4:26:2F",
            "00:22:65:8E:46:1C", "00:17:E6:94:D2:EB", "18:86:AC:34:9C:57",
            "00:1E:3B:37:1E:15", "00:1C:35:7A:8E:BF", "18:86:AC:42:7D:DA",
            "00:1B:EE:7B:95:59", "00:23:D6:E3:A8:57", "00:12:D2:BA:33:07",
            "00:17:E7:29:B7:71", "00:12:1C:77:0E:DD", "00:1E:3B:33:D5:A1",
            "00:1E:45:63:36:64", "00:25:67:6C:2C:9C", "00:1F:5C:04:B0:18",
            "00:1B:59:6E:E2:E2", "00:21:D2:FA:6B:33", "00:1D:98:70:16:C6",
            "00:16:20:D1:1A:99", "00:1E:E2:A5:29:BA", "00:22:A9:F5:7C:98",
            "00:1F:E4:B5:79:B2", "00:26:68:65:E2:9B", "00:1B:33:06:EF:2F",
            "00:19:4F:3E:C7:4D", "00:24:91:6F:26:12", "00:1B:AF:07:E0:31",
            "00:21:06:6C:55:E5", "00:24:90:F2:B8:91", "00:1A:16:52:F9:26",
            "00:24:03:BF:47:BB", "00:25:D0:F3:99:DE", "00:24:7C:14:C7:B9",
            "00:1B:98:00:30:CA", "00:21:AB:BB:6A:E4", "00:21:D1:A3:BB:1F",
            "00:25:48:15:77:E3", "00:22:FD:14:CC:01", "00:25:CF:70:24:00",
            "00:1A:DC:F6:28:BC", "00:1D:28:81:9F:07", "00:17:B0:57:0F:A6",
            "00:12:37:68:F8:2E", "00:12:D2:73:73:29", "00:1E:3A:25:23:B5",
            "00:24:EF:CA:81:1A", "00:25:D0:68:C1:15", "00:1A:89:8B:93:87",
            "00:26:69:B6:3D:14", "00:24:04:E3:9C:AE", "00:0F:DE:BD:DF:06",
            "00:1A:16:35:36:B4", "18:86:AC:A6:2F:9F", "00:24:03:54:BD:5D",
            "00:1E:3B:34:97:EA", "00:21:AA:A7:0A:04", "08:00:28:4E:D3:C9",
            "00:1F:E4:FB:03:7E", "00:1E:45:97:8F:23", "00:25:47:2A:96:98",
            "00:1A:8A:B3:F7:72", "00:09:2D:D5:B9:D0", "00:1F:01:39:0F:77",
            "00:21:AA:AB:BA:C7", "00:1E:DC:55:D0:AA", "00:18:42:E9:89:1B",
            "00:1C:35:79:EB:D1", "00:25:E5:D8:AF:15", "00:1A:DC:F5:2C:4D",
            "00:21:AA:4C:89:B7", "00:1B:AF:9D:01:55", "00:12:56:E6:B2:A4",
            "00:18:0F:A1:2E:F1", "00:1F:5C:D3:8F:1D", "00:1A:89:0B:DD:E5",
            "00:1D:3B:15:68:50", "00:24:7D:55:70:C6", "00:25:CF:F8:C0:8E",
            "00:15:2A:52:19:F4", "00:1B:33:EE:20:9C", "00:1D:98:0A:E6:0D",
            "00:1F:DE:8F:B5:69", "00:1B:AF:A4:A2:66", "00:0A:D9:D4:16:23",
            "00:1F:E4:57:9A:09", "00:25:47:5B:9D:82", "00:25:D0:72:8F:C4",
            "00:21:FE:DB:E3:31", "00:1D:E9:0C:D1:3B", "00:1E:3B:3A:EA:5F",
            "00:22:FD:7C:F3:0B", "00:1F:CC:65:B8:8E", "00:26:CC:1A:F6:B0",
            "00:23:7A:DE:9B:75", "00:19:79:C7:83:92", "00:1E:A3:75:F3:A4",
            "00:22:66:5F:63:43", "00:1F:DE:37:87:2A", "00:21:BA:69:66:A5",
            "00:1E:3A:B6:18:EE", "00:25:48:62:C7:41", "00:19:79:D2:D5:B6",
            "00:25:47:7A:A8:52", "00:21:9E:C7:FC:67", "00:17:B0:13:DF:46",
            "00:1F:5D:AB:D2:2C", "9C:18:74:52:90:7A", "00:26:5D:F4:FA:F9",
            "00:1F:00:28:F1:7C", "00:24:83:AF:53:3D", "00:25:67:07:2D:22",
            "00:21:D1:65:41:B6", "00:1E:3B:13:78:A2", "00:21:D1:65:41:B3",
            "00:26:68:00:B1:E3", "00:1A:89:C6:C7:DA", "00:25:57:90:69:99",
            "00:1E:3B:16:99:1A", "00:15:DE:20:04:20", "00:1F:5D:BD:45:96",
            "00:1C:43:CB:A5:CF", "00:02:EE:49:54:59", "00:12:D2:6E:CD:47",
            "00:16:B8:DA:51:78", "00:24:91:94:39:3B", "00:23:D6:31:26:C0",
            "9C:18:74:8E:36:19", "00:1E:3A:14:FC:F1", "9C:18:74:F7:0C:F8",
            "00:17:E6:7A:F5:D9", "00:1E:E2:A6:21:B0", "00:24:7C:E8:F6:8C",
            "00:16:20:D5:3D:E5", "00:24:90:4C:90:6B", "00:1D:6E:E0:76:F3",
            "00:1E:3B:A0:DA:4C", "00:25:D0:22:9E:BD", "00:1D:28:E9:A9:51",
            "00:1F:00:23:DE:E1", "00:24:7C:EF:3B:6E", "00:25:D0:8C:76:C2",
            "00:23:39:73:7C:F9", "00:23:B4:8B:4C:41", "00:1B:59:2A:2E:52",
            "00:25:48:A7:A6:03", "00:1E:3B:A9:B2:A7", "00:24:90:76:B8:D6",
            "00:22:FD:EA:0E:01", "00:80:98:E7:52:3B", "00:21:08:D1:33:FB",
            "00:13:70:0C:A5:1B", "00:1F:5D:BD:49:E3", "00:1E:3B:AC:95:9B",
            "00:26:5D:7F:13:53", "00:17:E3:E0:FF:C6", "00:25:D0:00:3B:38",
            "00:1E:45:97:8E:B2", "00:24:EF:F6:1C:22", "00:24:7C:34:A5:B9",
            "00:16:DB:BD:23:16", "00:1B:33:4A:A9:60", "00:1D:6E:23:E1:F7",
            "00:1D:E9:E7:47:F4", "00:1E:3B:A5:B8:20", "00:26:68:6D:C1:5A",
            "00:1E:3B:27:7B:D4", "00:1C:9A:EB:19:FB", "00:23:3A:08:0A:4F",
            "00:21:D2:66:AF:A5", "00:1D:3B:A4:97:3B", "00:1D:3B:7C:45:A7",
            "00:26:68:FC:56:AE", "00:1F:00:23:B3:DE", "00:26:68:78:89:64",
            "00:1E:A3:B6:B0:93", "00:26:5D:7F:19:78", "00:1E:E1:E3:6B:1A",
            "00:22:A9:A8:49:EF", "60:D0:A9:05:3F:86", "00:24:03:B4:33:74",
            "00:25:E7:BD:8E:73", "00:12:D1:79:6A:F1", "00:1C:D4:14:B9:5C",
            "00:1E:3B:AC:9E:79", "00:1D:28:40:60:BA", "00:19:63:7C:A9:BE",
            "00:16:DB:BB:AC:91", "00:1F:5C:EE:02:AD", "00:1F:E4:15:36:24",
            "00:60:57:87:69:84", "00:1A:DC:EB:B8:87", "00:1C:CC:AA:BF:15",
            "00:23:D6:86:12:51", "00:26:68:3A:95:7D", "00:16:B8:C0:23:4D",
            "00:1D:98:70:16:D2", "00:1D:98:EB:EF:79", "00:1C:D4:47:A7:05",
            "00:12:D2:37:8D:30", "00:18:C5:F0:C6:A3", "00:1D:F6:02:47:4C",
            "00:1E:3A:27:08:EE", "00:1E:3A:7A:49:F0", "00:23:3A:69:BE:37",
            "00:25:47:2F:4B:BB", "00:60:57:33:C1:C7", "00:21:D2:20:A2:3D",
            "00:21:06:71:94:DA", "00:23:D6:96:6E:E0", "00:23:6C:AA:56:34",
            "00:1F:01:26:FC:D4", "00:22:98:88:D5:D8", "00:24:03:CA:B5:61",
            "00:1E:3B:34:68:EF", "00:1A:8A:C3:F8:CA", "00:24:7C:6D:A9:BE",
            "00:1A:16:52:49:96", "00:1D:98:EF:08:8C", "00:60:57:24:B8:C8",
            "00:12:D1:83:35:C6", "00:26:69:F7:D2:A7", "00:24:7D:5D:AA:C6",
            "00:22:FD:7C:FD:DD", "00:22:66:99:0A:DE", "00:19:2D:FF:49:5A",
            "00:1F:CC:94:CF:2B", "00:23:D6:4A:03:BE", "00:1A:DC:F1:0B:23",
            "00:60:57:26:71:04", "00:1E:E2:2E:02:91", "00:23:D6:4A:03:B0",
            "00:21:FE:B0:46:2D", "00:17:B0:59:AE:E6", "00:1C:35:81:63:1C",
            "00:1B:AF:A4:6F:27", "00:1B:33:04:22:19", "00:17:E6:E0:E9:0B",
            "00:1E:A4:EC:CE:18", "00:17:E7:1E:00:63", "00:17:B0:69:1E:31",
            "00:1F:E4:C3:D4:69", "00:24:90:CA:53:47", "00:25:48:23:0B:74",
            "00:1A:DC:F6:25:1E", "00:24:03:59:5B:88", "00:22:FC:E0:B4:85",
            "00:1A:DC:F0:65:E9", "00:1D:98:58:1E:B4", "00:22:FC:5D:6B:0E",
            "00:25:47:DA:25:11", "00:26:68:7F:F5:2A", "00:24:7C:87:F8:01",
            "00:23:B4:32:77:A2", "00:26:5F:34:AD:46", "00:24:7C:0F:DE:F4",
            "00:25:67:87:89:BD", "00:1E:45:97:68:89", "00:17:B0:11:09:AE",
            "00:24:90:10:95:BE", "00:23:B4:AA:C4:B2"]
        return 0

    def find(self):
        """
        Start 'scanning'. Continuously calls device_discovered with a fake MAC
        address, deviceclass and RSSI value.
        """
        while True:
            self.device_discovered(self.macs[int(random.random()*len(
                self.macs))], 256, int(random.random()*-100))
            time.sleep(0.01+random.random()*0.016)
        return ""
