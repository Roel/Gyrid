#!/usr/bin/python
#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2009-2012  Roel Huybrechts
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

from distutils.core import setup, Extension
from distutils.command.install_data import install_data
from distutils.command.build_py import build_py
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
        /usr/share/doc/gyrid.
        """

        self._gzip('ChangeLog', 'share/doc/gyrid')
        self._gzip('gyrid/tools/oui_data.txt', 'share/gyrid')
        self._gzip('doc/gyrid.1', 'share/man/man1')
        install_data.run (self)

    def _gzip(self, file, dest):
        """
        Zip the given file with gzip.

        @param  file  The URL of the file to zip.
        @param  dest  The URL of the folder to install the zipped file into.
        @return  A list ready to extend to data_files.
        """
        buildDir = '/'.join(('build/%s' % file).split('/')[:-1])
        filename = file if not '/' in file else file.split('/')[-1]
        if not os.path.exists(buildDir):
            info('creating %s directory' % buildDir)
            os.makedirs(buildDir)

        str = {'build': buildDir, 'file': file, 'fileLower': filename.lower()}
        cmd = 'gzip -c --best %(file)s > %(build)s/%(fileLower)s.gz' % str
        info('gzip %s' % file)
        if os.system(cmd) != 0:
            raise SystemExit('Error while gzipping %(file)s' % str)
        self.data_files.append((dest, ['%(build)s/%(fileLower)s.gz' % str]))

os.system('protoc --python_out=. gyrid/protocol/gyrid.proto')
if os.path.exists('gyrid/protocol/gyrid_pb2.py'):
    os.rename('gyrid/protocol/gyrid_pb2.py', 'gyrid/protocol/network.py')

wigy = Extension("wigy",
            sources = ["gyrid/wigy/wigy.c"],
            libraries = ["iw"])

setup(name = "gyrid",
      version = "0.8.4",
      description = "Mobile device scanner.",
      author = "Roel Huybrechts",
      author_email = "roel.huybrechts@ugent.be",
      license = "GPLv3",
      packages = ["gyrid", "gyrid/protocol", "gyrid/scanners", "gyrid/tools"],
      data_files = [("/etc/init.d", ['init/gyrid']),
                    ("/usr/share/gyrid", ['network_middleware.py', 'bin/gyrid-start']),
                    ("/usr/share/doc/gyrid", ['README.net-api'])],
      cmdclass = {'install_data': InstallData},
      ext_modules = [wigy])
