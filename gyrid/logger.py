#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2009-2011  Roel Huybrechts
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

import logging
import logging.handlers
import os
import threading
import time

import zippingfilehandler

class InfoLogger(object):
    """
    The InfoLogger class handles writing informational messages to a logfile.
    """
    def __init__(self, mgr, log_location):
        """
        Initialisation of the logfile.

        @param  mgr   Reference to a ScanManager instance.
        @param  log_location  The location of the logfile.
        """
        self.mgr = mgr
        self.log_location = log_location

        self.logger = self._get_logger()
        self.logger.setLevel(logging.INFO)

        self.time_format = self.mgr.config.get_value('time_format')

    def _get_log_id(self):
        return self.log_location

    def _get_logger(self):
        logger = logging.getLogger(self._get_log_id())
        handler = logging.FileHandler(self.log_location)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        return logger

    def write_info(self, info):
        """
        Append a timestamp and the information to the logfile on a new line
        and flush the file. Try sending the info over the network.

        @param  info   The information to write.
        """
        if not (self.mgr.debug_mode and self.mgr.debug_silent):
            self.logger.info(",".join([time.strftime(
                self.time_format,
                time.localtime()), info]))
        self.mgr.net_send_line(",".join(['INFO',
                "%0.3f" % time.time(),
                info]))
