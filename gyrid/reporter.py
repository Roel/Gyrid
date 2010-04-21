#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
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

"""
Module that handles the generation of statistics, reports and
the ability of sending those reports to Bluetooth devices.
"""

import dbus
import math
import os
import signal
import socket
import subprocess
import time

class Reporter(object):
    """
    Class that can send a report to a Bluetooth device.
    """
    def __init__(self, mgr, report_generator=None):
        """
        Initialisation. Starts a D-Bus session bus so we can use
        org.openobex to send files.

        @param  mgr               Reference to a ScanManager.
        @param  report_generator  Reference to a ReportGenerator. When 'None'
                                   a new ReportGenerator will be created.
        """
        self.mgr = mgr
        if report_generator:
            self.report_generator = report_generator
        else:
            self.report_generator = ReportGenerator(self)
        self.connectionlog = {}
        self.busy = []

        self._start_dbus_session_bus()
        self._dbus_sessionbus = dbus.SessionBus()

        self._dbus_sessionbus.add_signal_receiver(self._send_file,
            bus_name = "org.openobex",
            signal_name = "SessionConnected")

        self._dbus_sessionbus.add_signal_receiver(self._disconnect,
            bus_name = "org.openobex",
            signal_name = "TransferCompleted")

    def _start_dbus_session_bus(self):
        """
        Call dbus-launch to start a D-Bus session bus.
        """
        p = subprocess.Popen('dbus-launch', shell=True,
            stdout = subprocess.PIPE, stderr = subprocess.PIPE)
        for item in p.stdout:
            split = item.split('=', 1)
            os.environ[split[0]] = split[1][:-1]

    def stop(self):
        """
        Kill the D-Bus session bus we created on initialisation.
        """
        if 'DBUS_SESSION_BUS_PID' in os.environ:
            os.kill(int(os.environ['DBUS_SESSION_BUS_PID']), signal.SIGTERM)

    def needs_report(self, mac):
        """
        Determine if the given MAC-address needs a report at this time.
        Each device can receive a report at most once each hour of the day.

        @param  mac  The MAC-address to check.
        @return      True if the given MAC needs a report.
        """
        if mac not in self.connectionlog:
            return True
        elif time.strftime("%Y%m%d-%H", time.localtime()) == \
             time.strftime("%Y%m%d-%H", time.localtime(
                self.connectionlog[mac])):
            return False
        else:
            return True

    def is_busy(self, mac):
        """
        Return if the given MAC-address is currently being connected to.

        @return  True if we are currently connecting to the given MAC.
        """
        return mac in self.busy

    def connect(self, mac):
        """
        If the given MAC-address needs a report, set up a Bluetooth connection
        to send the report.

        @param  mac  The MAC to connect to.
        @return      True if we created a Bluetooth connection.
        """
        self.currmac = mac

        manager_obj = self._dbus_sessionbus.get_object('org.openobex',
            '/org/openobex')
        self.manager = dbus.Interface(manager_obj, 'org.openobex.Manager')

        if self.needs_report(mac):
            self.manager.CreateBluetoothSession(mac, "00:00:00:00:00:00",
                "opp")
            self.busy.append(mac)
            return True
        else:
            return False

    def _send_file(self, session_path):
        """
        Send a report (generated by the ReportGenerator) to the given
        Bluetooth session. This is called automatically when a Bluetooth
        session is connected.

        @param   session_path   The Bluetooth session to use.
        """
        self.mgr.log_info("Report sent to %s" % self.currmac)
        self.session = dbus.Interface(self._dbus_sessionbus.get_object(
            'org.openobex', session_path), 'org.openobex.Session')
        self.session.SendFile(self.report_generator.generate_report())

    def _disconnect(self):
        """
        Disconnect and close the Bluetooth session. This is called
        automatically when a report has been transferred.
        """
        self.session.Disconnect()
        self.session.Close()
        self.busy.remove(self.currmac)
        self.connectionlog[self.currmac] = int(time.time())
        del(self.session)

class ReportGenerator(object):
    """
    Class that generates the reportfile that is sent by the Reporter.
    """
    def __init__(self, reporter, stats_generator=None):
        """
        Initialisation.

        @param  reporter          Reference to a Reporter instance.
        @param  stats_generator   Reference to a StatsGenerator. When 'None'
                                   a new StatsGenerator will be created.
        """
        self.reporter = reporter
        if stats_generator:
            self.stats_generator = stats_generator
        else:
            self.stats_generator = StatsGenerator(self)

    def generate_report(self):
        """
        Generate the report. Gets system and Gyrid uptime and reads the stats
        generated by the StatsGenerator and writes everything to a temporary
        report file ready to be sent.

        @return  The location of the reportfile.
        """
        now = time.strftime("%H%M-%d")
        hostname = socket.gethostname()
        temp_file = '/tmp/gyrid-report-%s-%s.txt' % (hostname, now)

        # Get system uptime
        f = open('/proc/uptime', 'r')
        system_uptime = self._parse_uptime(int(float(f.read().split()[0])))
        f.close()

        # Get Gyrid uptime
        gyrid_uptime = self._parse_uptime(int(time.time()) - \
            self.reporter.mgr.startup_time)

        # Get previous stats
        try:
            f = open(self.stats_generator.filepath, 'r')
            stats = f.read()
            f.close()
        except IOError:
            stats = ""

        # Write report to file
        f = open(temp_file, 'w')
        f.write("%s %s\n" % (hostname, now))
        f.write("SU: %s\n" % system_uptime)
        f.write("GU: %s\n" % gyrid_uptime)
        f.write(stats)
        f.close()

        return temp_file

    def _parse_uptime(self, secs):
        """
        Parse a time given in seconds to the corresponding notation in
        days, hours, minutes, seconds format.

        Based on code by Dave Smith.
        http://thesmithfam.org/blog/2005/11/19/python-uptime-script/

        @param  secs  The number of seconds.
        @return       The time in days, hours, minutes, seconds.
        """
        MINUTE = 60
        HOUR = MINUTE * 60
        DAY = HOUR * 24

        days = int(secs / DAY)
        hours = int((secs % DAY) / HOUR)
        minutes = int((secs % HOUR) / MINUTE)
        seconds = int(secs % MINUTE)
        return "%id %ih %im %is" % (days, hours, minutes, seconds)

class StatsGenerator(object):
    """
    Class that generates some statistics and writes them to a file.

    We record:
     * Number of unique MAC-addresses.
     * Number of lines in the logfile.
     * Average time a MAC-address in in the range of the scanner.
    """
    def __init__(self, report_generator):
        """
        Initialisation.

        @param  report_generator   Reference to a ReportGenerator.
        """
        self.report_generator = report_generator
        self.mgr = self.report_generator.reporter.mgr
        self.time_format = self.mgr.config.get_value('time_format')
        self.filepath = self.mgr.get_stats_location()

    def init(self):
        """
        Initialise a new calculation.
        """
        self.clear()

    def clear(self):
        """
        Clear a previous calculation.
        """
        self.time_now = int(time.time())
        self.unique_macs = {}
        self.loglines = 0
        self.time_total = 0
        self.time_count = 0

    def add_mac(self, mac):
        """
        Add a MAC-address to the dictionary of MAC's.

        @param  mac  The MAC-address to add.
        """
        self.unique_macs[mac] = True

    def add_time(self, time):
        """
        Add a time (in seconds) to the average time a device is in the
        range of the scanner.

        @param  time  The time to add (in seconds).
        """
        self.time_total += time
        self.time_count += 1

    def add_line(self, number=1):
        """
        Add a line to the number of lines in the logfile.

        @param  number  The number of lines to add (default=1).
        """
        self.loglines += number

    def log(self, time_tuple):
        """
        Calculate the statistics and write them to the stats file.

        @param  time_tuple   The time when the statistics were calculated.
        """
        self._log_stats(time_tuple,
            len(self.unique_macs),
            self.loglines,
            int(self.time_total / self.time_count))

    def _log_stats(self, stat_time, unique_macs, loglines, avg_time):
        """
        Write the statistics to the stats file.

        @param  stat_time    The time when the statistics were calculated.
        @param  unique_macs  The number of unique MAC-addresses.
        @param  loglines     The number of lines in the logfile.
        @param  avg_time     The average time a device was in the range of
                              the scanner.
        """
        f = open(self.filepath, 'a')
        f.write("\n" + time.strftime("%d:%H/", stat_time) + \
            str(loglines) + "|" + str(unique_macs) + "|" + \
            self._parse_time(avg_time))
        f.close()

    def _parse_time(self, secs):
        """
        Parse the given time (in seconds) to the format 'minutes,seconds'.

        @param  secs  The time to parse (in seconds).
        @return       The time in the format 'minutes,seconds'.
        """
        minutes = int(secs / 60)
        secs -= minutes * 60
        return "%i,%i" % (minutes, secs)
