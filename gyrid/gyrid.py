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

import gobject
import os
import re
import signal
import sys
import time
import threading
import traceback

import daemon
import scanmanager

class Main(daemon.Daemon):
    """
    Main class of the Bluetooth tracker; subclass of Daemon for easy
    daemonising.
    """
    def __init__(self, lockfile, configfile, errorlogfile):
        """
        Initialistation of the daemon, logging and DBus connection.

        @param  lockfile        URL of the lockfile.
        @param  configfile      URL of the configfile.
        @param  errorlogfile    URL of the errorlogfile.
        @param  debug_mode      Whether to start in debug mode.
        """
        self.lockfile = lockfile
        self.errorlogfile = errorlogfile
        self.errorlog = open(self.errorlogfile, 'a')

        self._install_thread_excepthook()
        sys.excepthook = self._handle_exception
        signal.signal(signal.SIGTERM, self._catch_sigterm)

        self.configfile = configfile
        self.mgr = scanmanager.DefaultScanManager(self)

        self.main_loop = gobject.MainLoop()

        daemon.Daemon.__init__(self, self.lockfile, stdout='/dev/stdout',
                               stderr='/dev/stderr')

        gobject.threads_init()

    def pass_args(self, *args):
        """
        Handle commandline arguments passed to Gyrid.

        @param  *args    sys.argv arguments.
        """
        def start_restart():
            """
            Start when not running, otherwise restart.
            """
            if os.path.isfile(self.lockfile):
                self.stop()
            self.run()

        argerr = False
        self.debug_mode = False
        if len(args) == 2:
            if args[1] == 'start':
                self.start()
            elif args[1] == 'stop':
                self.stop()
            elif args[1] in ('restart', 'force-reload'):
                self.restart()
            elif args[1] == 'debug':
                self.debug_mode = True
                self.mgr.set_debug_mode(True, False)
                start_restart()
            else:
                argerr = True
        elif len(args) == 3 and args[1] == 'debug' and args[2] == '--no-log':
                self.debug_mode = True
                self.mgr.set_debug_mode(True, True)
                start_restart()
        else:
            argerr = True

        if argerr:
            self.log_error('Error', 'Wrong set of arguments %s' % str(args))
            sys.stderr.write('Gyrid: Error: Wrong set of arguments.\n')
            sys.stderr.write('Gyrid: Usage: %s start|stop|' % args[0] + \
                'restart|force-reload|debug\n')
            sys.exit(2)

    def _handle_exception(self, etype, evalue, etraceback):
        """
        Handle the exception by writing information to the error log.
        """
        exc = ''.join(traceback.format_exception(etype, evalue, etraceback))
        self.log_error('Error', exc)
        sys.stderr.write("Error: unhandled exception: %s, %s\n\n" % \
            (etype.__name__, evalue))
        sys.stderr.write(' '.join(traceback.format_exception(etype, evalue,
            etraceback)))

    def _install_thread_excepthook(self):
        """
        Workaround for sys.excepthook thread bug
        (http://bugs.python.org/issue1230540)

        From
        http://spyced.blogspot.com/2007/06/workaround-for-sysexcepthook-bug.html
        """
        init_old = threading.Thread.__init__
        def init(self, *args, **kwargs):
            init_old(self, *args, **kwargs)
            run_old = self.run
            def run_with_except_hook(*args, **kw):
                try:
                    run_old(*args, **kw)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except:
                    sys.excepthook(*sys.exc_info())
            self.run = run_with_except_hook
        threading.Thread.__init__ = init

    def log_error(self, level, message):
        """
        Write the given message to the error log.

        @param  level    The level of the message, f. ex. Warning or Error
        @param  message  The message to write.
        """
        self.errorlog.write("%(tijd)s %(level)s: %(message)s\n" % \
            {'tijd': time.strftime('%Y%m%d-%H%M%S-%Z'),
             'level': level, 'message': message})
        self.errorlog.flush()

    def run(self, restart=False):
        """
        Called after the daemon gets the (re)start command.
        Connect the AdapterAdded signal (DBus/BlueZ) to its handler and
        start the Bluetooth discoverer.

        @param  restart  If this call is part of a restart operation.
        """
        if self.debug_mode:
            debugstr = " in debug mode"
        else:
            debugstr = ""
        if restart:
            self.mgr.log_info("Restarted" + debugstr)
            if not self.debug_mode:
                print("Restarting Gyrid" + debugstr + ".")
        else:
            self.mgr.log_info("Started" + debugstr)
            if not self.debug_mode:
                print("Starting Gyrid" + debugstr + ".")

        self.mgr.init()
        self.mgr.run()

        try:
            self.main_loop.run()
        except KeyboardInterrupt:
            self.stop(stop_daemon=False)

    def _catch_sigterm(self, signum, frame):
        """
        Called when a SIGTERM signal is received, ie. when the daemon is
        killed. Shutdown the manager and exit.
        """
        self.mgr.stop()
        sys.exit(0)

    def stop(self, restart=False, stop_daemon=True):
        """
        Called when the daemon gets the stop command. Stop the logger, cleanly
        close the logfile if restart=False and then stop the daemon.

        @param  restart   If this call is part of a restart operation.
        """
        if stop_daemon:
            if not restart:
                self.mgr.log_info("Stopped")
                if not self.debug_mode:
                    print("Stopping Gyrid.")
            daemon.Daemon.stop(self)
        else:
            self.mgr.log_info("Stopped")
            sys.exit(0)
