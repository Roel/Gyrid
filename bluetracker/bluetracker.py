#-*- coding: utf-8 -*-
#
# This file belongs to Bluetracker.
#
# Bluetracker is a Bluetooth device scanner daemon.
# Copyright (C) 2009  Roel Huybrechts
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

import gobject
import sys
import time
import traceback

import daemon
import scanmanager

class Main(daemon.Daemon):
    """
    Main class of the Bluetooth tracker; subclass of Daemon for easy
    daemonising.
    """
    def __init__(self, lockfile, configfile, errorlogfile,
                 debug_mode):
        """
        Initialistation of the daemon, logging and DBus connection.

        @param  lockfile        URL of the lockfile.
        @param  configfile      URL of the configfile.
        @param  errorlogfile    URL of the errorlogfile.
        @param  debug_mode      Whether to start in debug mode.
        """
        sys.excepthook = self._handle_exception
        
        self.configfile = configfile
        self.errorlogfile = errorlogfile
        self.debug_mode = debug_mode
        self.mgr = scanmanager.SerialScanManager(self, self.debug_mode)

        self.main_loop = gobject.MainLoop()

        daemon.Daemon.__init__(self, lockfile, stdout='/dev/stdout',
                               stderr='/dev/stderr')
                              
        gobject.threads_init()

    def _handle_exception(self, etype, evalue, etraceback):
        """
        Handle the exception by writing information to the error log.
        """
        exc = ' '.join(traceback.format_exception(etype, evalue, etraceback)).replace('\n', '')
        self.log_error('Error', exc)
        sys.stderr.write("Error: unhandled exception: %s, %s\n\n" % \
            (etype.__name__, evalue))
        sys.stderr.write(' '.join(traceback.format_exception(etype, evalue, etraceback)))

    def log_error(self, level, message):
        self.errorlog = open(self.errorlogfile, 'a')
        self.errorlog.write("%(tijd)s %(level)s: %(message)s\n" % \
            {'tijd': time.strftime('%Y%m%d-%H%M%S'),
             'level': level, 'message': message})
        self.errorlog.flush()

    def run(self, restart=False):
        """
        Called after the daemon gets the (re)start command.
        Connect the AdapterAdded signal (DBus/BlueZ) to its handler and
        start the Bluetooth discoverer.

        @param  restart  If this call is part of a restart operation.
        """
        debugstr = " in debug mode" if self.debug_mode else ""
        if restart:
            self.mgr.log_info("I: Restarted" + debugstr)
            self.mgr.debug("Restarted")
            if not self.debug_mode:
                print("Restarting bluetracker" + debugstr + ".")
        else:
            self.mgr.log_info("I: Started" + debugstr)
            self.mgr.debug("Started")
            if not self.debug_mode:
                print("Starting bluetracker" + debugstr + ".")

        try:
            self.mgr.run()
        finally:
            self.main_loop.run()

    def stop(self, restart=False):
        """
        Called when the daemon gets the stop command. Stop the logger, cleanly
        close the logfile if restart=False and then stop the daemon.
        
        @param  restart   If this call is part of a restart operation.
        """
        if not restart:
            self.mgr.log_info("I: Stopped")
            self.mgr.debug("Stopped")
            if not self.debug_mode:
                print("Stopping bluetracker.")
        self.mgr.stop()
        daemon.Daemon.stop(self)
