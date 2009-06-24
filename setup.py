#!/usr/bin/python
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

import os

from distutils.core import setup
from distutils.command.install_data import install_data
from distutils.dep_util import newer
from distutils.log import info

class InstallData(install_data):
    """
    Subclassing install_data to gzip ChangeLog and install it in the correct
    location.
    """
    def run (self):
        """
        Call _gzip to zip the ChangeLog and install it to
        /usr/share/doc/bluetracker.
        """
        self.data_files.extend (self._gzip ('ChangeLog', os.path.join('share',
                                            'doc', 'bluetracker')))
        install_data.run (self)

    def _gzip(self, file, dest):
        """
        Zip the given file with gzip.

        @param  file  The URL of the file to zip.
        @param  dest  The URL of the folder to install the zipped file into.
        @return  A list ready to extend to data_files.
        """
        data_files = []
        buildDir = 'build'
        if not os.path.exists(buildDir):
            info('creating %s directory' % buildDir)
            os.makedirs(buildDir)

        str = {'build': buildDir, 'file': file, 'fileLower': file.lower()}
        cmd = 'gzip -c --best %(file)s > %(build)s/%(fileLower)s.gz' % str
        info('gzipping %s' % file)
        if os.system(cmd) != 0:
            raise SystemExit('Error while gzipping %(file)s' % str)
        data_files.append((dest, ['%(build)s/%(fileLower)s.gz' % str]))

        return data_files

setup(name = "bluetracker",
      version = "0.0.11",
      description = "Bluetooth device scanner daemon.",
      author = "Roel Huybrechts",
      author_email = "roel.huybrechts@ugent.be",
      license = "GPLv3",
      packages = ["bluetracker", "bluetracker/tools"],
      data_files = [("/etc/init.d", ['init/bluetracker']),
                    ("/usr/share/bluetracker", ['bluetracker/tools/oui.txt.bz2'])],
      cmdclass = {'install_data': InstallData})
