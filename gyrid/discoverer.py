#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
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

import bluetooth
import bluetooth._bluetooth as bluez
import math
import struct
import time

class Discoverer(object):
    """
    Bluetooth discover, this class provides device discovery. Heavily based on
    the PyBluez advanced inquiry with RSSI example.
    """
    def __init__(self, mgr, logger, logger_rssi, logger_inquiry, device_id, mac):
        """
        Initialisation of the Discoverer. Store the reference to the loggers and
        query the necessary configuration options.

        @param  mgr             Reference to a Scanmanger instance.
        @param  logger          Reference to a Logger instance.
        @param  logger_rssi     Reference to a Logger instance which records
                                  the RSSI values.
        @param  logger_inquiry  Reference to a Logger instance which records
                                  the inquiry status.
        @param  device_id       The ID of the Bluetooth device used for scanning.
        @param  mac             The MAC address of the Bluetooth scanning device.
        """
        self.mgr = mgr
        self.logger = logger
        self.logger_rssi = logger_rssi
        self.logger_inquiry = logger_inquiry
        self.device_id = device_id
        self.mac = mac
        self.buffer_size = int(math.ceil(
            self.mgr.config.get_value('buffer_size')/1.28))
        self.minimum_rssi = self.mgr.config.get_value('minimum_rssi')
        self.done = False

    def init(self):
        """
        Initialise the Bluetooth device used for scanning.

        @return  0 on success, 1 on failure.
        """
        try:
            self.sock = bluez.hci_open_dev(self.device_id)
        except:
            s = 'Error opening Bluetooth device %i' % self.device_id
            self.mgr.main.log_error('Error', '%s.' % s)
            self.mgr.debug(s)
            return 1

        try:
            mode = self._read_inquiry_mode()
        except:
            s = 'Error reading inquiry mode on device %i. ' % self.device_id + \
                'We need a 1.2+ Bluetooth device'
            self.mgr.main.log_error('Error', '%s.' % s)
            self.mgr.debug(s)
            return 1

        if mode != 1:
            try:
                result = self._write_inquiry_mode(1)
            except:
                s = 'Error writing inquiry mode on device %i' % self.device_id
                self.mgr.main.log_error('Error', '%s.' % s)
                self.mgr.debug(s)
                return 1

            if result != 0:
                s = 'Adapter %s does not support RSSI enabled ' % self.mac \
                    + 'inquiries, disabling RSSI detections'
                self.mgr.log_info(s)
                try:
                    result = self._write_inquiry_mode(0)
                except:
                    s = 'Error writing inquiry mode on device %i' % \
                        self.device_id
                    self.mgr.main.log_error('Error', '%s.' % s)
                    self.mgr.debug(s)
                    return 1

                if result != 0:
                    s = 'Error setting inquiry mode on ' + \
                        'device %i' % self.device_id
                    self.mgr.main.log_error('Error', '%s.' % s)
                    self.mgr.debug(s)
                    return 1

        return 0

    def _read_inquiry_mode(self):
        """
        Returns the current mode, or -1 on failure.
        """
        # save current filter
        old_filter = self.sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 14)

        # Setup socket filter to receive only events related to the
        # read_inquiry_mode command
        flt = bluez.hci_filter_new()
        opcode = bluez.cmd_opcode_pack(bluez.OGF_HOST_CTL,
                bluez.OCF_READ_INQUIRY_MODE)
        bluez.hci_filter_set_ptype(flt, bluez.HCI_EVENT_PKT)
        bluez.hci_filter_set_event(flt, bluez.EVT_CMD_COMPLETE);
        bluez.hci_filter_set_opcode(flt, opcode)
        self.sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, flt)

        # first read the current inquiry mode.
        bluez.hci_send_cmd(self.sock, bluez.OGF_HOST_CTL,
                bluez.OCF_READ_INQUIRY_MODE)

        pkt = self.sock.recv(255)

        status,mode = struct.unpack("xxxxxxBB", pkt)
        if status != 0: mode = -1

        # restore old filter
        self.sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, old_filter)
        return mode

    def _write_inquiry_mode(self, mode):
        """
        Returns 0 on success, -1 on failure.
        """
        # save current filter
        old_filter = self.sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 14)

        # Setup socket filter to receive only events related to the
        # write_inquiry_mode command
        flt = bluez.hci_filter_new()
        opcode = bluez.cmd_opcode_pack(bluez.OGF_HOST_CTL,
                bluez.OCF_WRITE_INQUIRY_MODE)
        bluez.hci_filter_set_ptype(flt, bluez.HCI_EVENT_PKT)
        bluez.hci_filter_set_event(flt, bluez.EVT_CMD_COMPLETE);
        bluez.hci_filter_set_opcode(flt, opcode)
        self.sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, flt)

        # send the command!
        bluez.hci_send_cmd(self.sock, bluez.OGF_HOST_CTL,
                bluez.OCF_WRITE_INQUIRY_MODE, struct.pack("B", mode))

        pkt = self.sock.recv(255)

        status = struct.unpack("xxxxxxB", pkt)[0]

        # restore old filter
        self.sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, old_filter)
        if status != 0: return -1
        return 0

    def _device_inquiry_with_with_rssi(self):
        """
        Perform a Bluetooth inquiry with RSSI reception.
        """
        # save current filter
        old_filter = self.sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 14)

        flt = bluez.hci_filter_new()
        bluez.hci_filter_all_events(flt)
        bluez.hci_filter_set_ptype(flt, bluez.HCI_EVENT_PKT)
        self.sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, flt)

        max_responses = 255
        cmd_pkt = struct.pack("BBBBB", 0x33, 0x8b, 0x9e, self.buffer_size,
            max_responses)

        self.logger_inquiry.write(time.time(), self.buffer_size*1.28)
        self.mgr.debug("%s: New inquiry" % self.mac)

        bluez.hci_send_cmd(self.sock, bluez.OGF_LINK_CTL, bluez.OCF_INQUIRY,
            cmd_pkt)

        done = False
        while not done:
            try:
                pkt = self.sock.recv(255)
            except bluetooth._bluetooth.error, e:
                if e[0] == 32:
                    self.logger.stop()
                    done = True
                    self.done = True
                    self.scanner.stopped_scanning(self, "adapter lost")
                    return
            ptype, event, plen = struct.unpack("BBB", pkt[:3])
            if event == bluez.EVT_INQUIRY_RESULT_WITH_RSSI:
                pkt = pkt[3:]
                nrsp = struct.unpack("B", pkt[0])[0]
                for i in range(nrsp):
                    addr = bluez.ba2str(pkt[1+6*i:1+6*i+6])
                    rssi = struct.unpack("b", pkt[1+13*nrsp+i])[0]
                    devclass_raw = pkt[1+8*nrsp+3*i:1+8*nrsp+3*i+3]
                    devclass = struct.unpack ("I", "%s\0" % devclass_raw)[0]
                    self.device_discovered(addr, devclass, rssi)
            elif event == bluez.EVT_INQUIRY_RESULT:
                pkt = pkt[3:]
                nrsp = struct.unpack("B", pkt[0])[0]
                for i in range(nrsp):
                    addr = bluez.ba2str(pkt[1+6*i:1+6*i+6])
                    devclass_raw = struct.unpack("BBB",
                            pkt[1+9*nrsp+3*i:1+9*nrsp+3*i+3])
                    devclass = (devclass_raw[2] << 16) | \
                            (devclass_raw[1] << 8) | \
                            devclass_raw[0]
                    self.device_discovered(addr, devclass, None)
            elif event == bluez.EVT_INQUIRY_COMPLETE:
                done = True
            elif event == bluez.EVT_CMD_STATUS:
                status, ncmd, opcode = struct.unpack("BBH", pkt[3:7])
                if status != 0:
                    self.mgr.debug('Non-zero Bluetooth status packet received')
                    done = True
            else:
                self.mgr.debug('Unrecognized Bluetooth packet type received')

        # restore old filter
        self.sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, old_filter)

    def find(self):
        """
        Start scanning.
        """
        while not self.done and not self.mgr.main.stopping:
            try:
                end = self._device_inquiry_with_with_rssi()
            except Exception, e:
                end = e.message
                self.done = True
            if self.mgr.main.stopping:
                end = "Shutting down"

        return " (%s)" % end

    def device_discovered(self, address, device_class, rssi):
        """
        Called when discovered a device. Get a UNIX timestamp and call the
        update method of Logger to update the timestamp, the address and
        the device_class of the device in the pool.

        @param  address        Hardware address of the Bluetooth device.
        @param  device_class   Device class of the Bluetooth device.
        @param  rssi           The RSSI (RX power level) value of the
                                discovery. None when none recorded.
        """
        if (rssi == None or \
            not (self.minimum_rssi != None and rssi < self.minimum_rssi)) \
            and (True not in (address.upper().startswith(
                black_mac) for black_mac in self.mgr.blacklist)):

            try:
                device_class = int(device_class)
            except ValueError:
                device_class = -1

            hwid = self.mgr.privacy_process(address)
            hwid = hwid.replace(':', '')

            timestamp = time.time()

            if self.mgr.debug_mode:
                import tools.deviceclass
                import tools.macvendor

                device = ', '.join([str(tools.deviceclass.get_major_class(
                    device_class)), str(tools.deviceclass.get_minor_class(
                    device_class))])
                rssi_s = ' with RSSI %d' % rssi if rssi != None else ''

                d = {'hwid': hwid, 'dc': device, 'time': str(timestamp),
                     'rssi': rssi_s, 'sc': self.mac}

                self.mgr.debug(
                    "%(sc)s: Found device %(hwid)s [%(dc)s]" % d + \
                    "%(rssi)s" % d, force=True)

            self.logger.update_device(timestamp, hwid, device_class)

            if rssi != None:
                self.logger_rssi.write(timestamp, hwid, device_class,
                    rssi)
