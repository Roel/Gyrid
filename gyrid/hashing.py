#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2013  Roel Huybrechts
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
Module that handles hashing various data.
"""

import hashlib
import os
import time

class Hashing(object):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, mgr):
        """
        Initialisation.

        @param   mgr   Reference to ScanManager instance.
        """
        self.mgr = mgr
        self.hasher = hashlib.sha256
        self.salt = self.mgr.config.get_value("hash_salt")

    def hash(self, data):
        salt = time.strftime(self.salt)
        return self.hasher(salt + data).hexdigest()
