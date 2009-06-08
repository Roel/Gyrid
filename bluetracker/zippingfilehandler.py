#-*- coding: utf-8 -*-
#
# This file belongs to Bluetracker.
#
# Bluetracker is a Bluetooth device scanner daemon.
# Copyright (C) 2009  Roel Huybrechts
#
# Heavily based on code by Angel Freire
#   (http://code.activestate.com/recipes/502265/)
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

import bz2
import os
import re
import time
import logging
import logging.handlers

class TimedCompressedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    Subclassing TimedRotatingFileHandler to add bzipping on rollover.
    """
    def __init__(self, main, filename):
        """
        Initialisation. 
        
        @param  main        Main instance.
        @param  filename    Filename to write to.
        """
        self.main = main
        logging.handlers.BaseRotatingHandler.__init__(self, filename, 'a')
        self.backupCount = 0
        currentTime = int(time.time())

        self.interval = 60 * 60 # one hour
        self.suffix = "%Y-%m-%d_%H"
        self.extMatch = r"^\d{4}-\d{2}-\d{2}_\d{2}$"

        self.extMatch = re.compile(self.extMatch)
        self.rolloverAt = currentTime + self.interval

        t = time.localtime(currentTime)
        currentHour = t[3]
        currentMinute = t[4]
        currentSecond = t[5]
        # r is the number of seconds left between now and the next hour
        r = self.interval - ((currentMinute * 60) + currentSecond)
        self.rolloverAt = currentTime + r
    
    def doRollover (self):
        """
        Do the rollover, this includes processing and bzipping.
        """
        self.stream.close()
        # get the time that this sequence started at and make it a TimeTuple
        t = self.rolloverAt - self.interval
        timeTuple = time.localtime(t)
        dfn = self.baseFilename + "." + time.strftime(self.suffix, timeTuple)
        if os.path.exists(dfn):
            os.remove(dfn)
        os.rename(self.baseFilename, dfn)
        output = bz2.BZ2File(dfn + '.bz2', 'w')
        input = open(dfn, 'r')
        output.write(self._process_passing_movement(input))
        output.close()
        input.close()
        os.remove(dfn)
        self.main.debug("Rotated scanlog, created %s.bz2" % dfn)
        
        self.mode = 'w'
        if self.encoding:
            self.stream = codecs.open(self.baseFilename, 'w', self.encoding)
        else:
            self.stream = open(self.baseFilename, 'w')
        newRolloverAt = self.rolloverAt + self.interval
        currentTime = int(time.time())
        while newRolloverAt <= currentTime:
            newRolloverAt = newRolloverAt + self.interval
        self.rolloverAt = newRolloverAt
        
    def _process_passing_movement(self, file):
        """
        Return an updated file where all 'pass' movements are shown as such.
        """
        stringlist = []
        macs = {}
        for line in file.readlines():
            linelist = line.split(',')
            if len(linelist) > 2:
                time = line.split(',')[0]
                mac = line.split(',')[1]
                dc = line.split(',')[2]
                if (mac in macs) and (macs[mac] == time):
                    stringlist.append(','.join([time, mac, dc, 'pass']))
                    del(macs[mac])
                elif mac in macs:
                    stringlist.append(','.join([macs[mac], mac, dc, 'in']))
                    stringlist.append(','.join([time, mac, dc, 'out']))
                    del(macs[mac])
                else:
                    macs[mac] = time
            else:
                stringlist.append(line.strip('\n'))
        return '\n'.join(stringlist)
