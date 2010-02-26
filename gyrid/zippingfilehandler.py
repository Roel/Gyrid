#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a Bluetooth device scanner daemon.
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
import glob
import logging
import logging.handlers
import os
import re
import time

class CompressingRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    Subclassing TimedRotatingFileHandler to add bzipping on rollover.
    """
    def __init__(self, mgr, filename):
        """
        Initialisation. 
        
        @param  filename    Filename to write to.
        """
        self.mgr = mgr
        logging.handlers.BaseRotatingHandler.__init__(self, filename, 'a')
        self.backupCount = 0
        currentTime = int(time.time())

        self.interval = 60 * 60 # one hour
        self.suffix = "%Y%m%d-%H-%Z"
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
        dfn = '%s.%s' % (self.baseFilename, time.strftime(self.suffix, timeTuple))
        dfn_bz2 = '%s.bz2' % dfn
        if os.path.exists(dfn_bz2):
            newest = sorted(glob.glob('%s*' % dfn_bz2), reverse=True)[0]
            if newest != '%s.bz2' % dfn:
                nr = int(newest[newest.rfind('.')+1:])
            else:
                nr = 0
            nr += 1
            os.rename(dfn_bz2, '%s.%i' % (dfn_bz2, nr))
        os.rename(self.baseFilename, dfn)
        output = bz2.BZ2File(dfn_bz2, 'w')
        input = open(dfn, 'r')
        self._process_passing_movement(input, output)
        output.close()
        input.close()
        os.remove(dfn)
        self.mgr.debug("Rotated scanlog, created %s.bz2" % dfn)
        
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

    def _process_passing_movement(self, input_file, output_file):
        """
        Create an updated file where all 'pass' movements are shown as such.
        """
        macs = {}
        for line in input_file:
            linelist = line.split(',')
            if len(linelist) == 4:
                tijd = linelist[0].strip()
                mac = linelist[1].strip()
                dc = linelist[2].strip()
                move = linelist[3].strip()

                if not mac in macs:
                    macs[mac] = [tijd, dc, move]
                elif macs[mac][0] == tijd and \
                        macs[mac][2] == 'in' and \
                        move == 'out' and \
                        macs[mac][1] == dc:
                    output_file.write(','.join([str(i) for i in [tijd, mac, dc, 'pass']]) + '\n')
                    del(macs[mac])
                else:
                    output_file.write(','.join([str(i) for i in [macs[mac][0],
                        mac, macs[mac][1], macs[mac][2]]]) + '\n')
                    output_file.write(','.join([str(i) for i in [tijd, mac, dc, move]]) + '\n')
                    del(macs[mac])

            else:
                output_file.write(line.strip() + '\n')

        for mac in macs:
            output_file.write(','.join([str(i) for i in [macs[mac][0],
                mac, macs[mac][1], macs[mac][2]]]) + '\n')
