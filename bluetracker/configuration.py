#-*- coding: utf-8 -*-
#
# This file belongs to Bluetracker.
#
# Bluetracker is a Bluetooth device scanner daemon.
# Copyright (C) 2007-2009  Roel Huybrechts
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
Module that provides all options of the program and the handling of the
configuration file.

Classes:
    Configuration: The main class, stores all Options and can get the value.
    _ConfigurationParser: The configuration file parser.
    _Option: Class for all Options.
"""

import ConfigParser
import os
import sys
import textwrap

class Configuration(object):
    """
    Store all the configuration options and retrieve the value of
    a certain option with the ConfigurationParser.
    """
    def __init__(self, main):
        """
        Initialisation. Construct an empty list of options, and fill it
        with all the Options.

        @param  main         Reference to Main instance.
        @param  configfile   URL of the configfile to write to.
        """
        self.main = main
        self.options = []
        self.configfile = self.main.configfile
        self._define_options()
        self.configparser = _ConfigurationParser(self)

    def _define_options(self):
        """
        Create all options and add them to the list.
        """
        buffer_length = _Option(name = 'buffer_size',
            type = 'float("%s")',
            default = 10.24,
            description = 'The buffer length in seconds. This is the amount of ' +
                'time a device may disappear and appear again without it being ' +
                'noticed.')

        alix_led_support = _Option(name = 'alix_led_support',
            type = '"%s".lower().strip() in ["true", "yes", "y", "1"]',
            default = False,
            description = 'Support for flashing LEDs on ALIX boards.',
            domain = {True: 'Enable support.', False: 'Disable support.'})

        self.options.extend([buffer_length, alix_led_support])

    def _get_option_by_name(self, name):
        """
        Get the Option object of the option with the given name.

        @param  name   (str)       The name of the object.
        @return        (Option)    The Option object with the given name,
                                   None if such object does not exist.
        """
        for option in self.options:
            if option.name == name:
                return option
        return None

    def get_value(self, option):
        """
        Retrieve the value of the option.

        @param  option   (str)       The option to retrieve the value from.
        @return          (unicode)   The value of the option.
        """

        optionObj = self._get_option_by_name(option)

        try:
            config = eval(optionObj.type % self.configparser.get_value(option))
        except:
            self.main.errorlogger.error("Error in '%s' option: " % option + str(sys.exc_info()[1]) + \
                " [Using default value: %s]" % optionObj.default)
            config = None
        
        if config != None and optionObj.domain_has_key(config):
            return config
        elif config != None:
            self.main.errorlogger.error("Wrong value for option %(option)s: '%(value)s'." % \
                {'option': optionObj.name, 'value': config})

        return optionObj.default


class _ConfigurationParser(ConfigParser.ConfigParser, object):
    """
    Handles interaction with the configuration file.
    """
    def __init__(self, configuration):
        """
        Initialisation.

        @param  configuration  (Configuration)    Configuration instance.
        """
        ConfigParser.ConfigParser.__init__(self)
        self.configuration = configuration
        self.config_file_location = self.configuration.configfile
        self.update_config_file()
        ConfigParser.ConfigParser.read(self, self.config_file_location)

    def update_config_file(self):
        """
        If no configuration file exists, copy a new default one.
        """

        if not os.path.isfile(self.config_file_location):
            file = open(self.config_file_location, "w")
            file.write(self._generate_default())
            file.close()
        else:
            #FIXME: update when necessary
            pass

    def _generate_default(self):
        """
        Generates a default configuration file.

        @return  (str)    A default configuration file, based on the
                          configuration options.
        """
        default = '#Bluetracker configuration file\n[Bluetracker]\n\n'
        for option in self.configuration.options:
            default += "\n#".join(textwrap.wrap("#%s" % option.description, 80))
            if option.domain:
                default += '\n#Options:'
                for key in option.domain.items():
                    if key[0] == option.default:
                        defaultValue = '(default) '
                    else:
                        defaultValue = ''
                    default += '\n#%s - %s%s' % \
                        (key[0], defaultValue, key[1])
            default += '\n%s = %s\n\n' % (option.name, option.default)
        return default.rstrip('\n')

    def get_value(self, option):
        """
        Get the value of the given option in the configuration file.

        @return   (str)    The value of the option in the configuration file.
                           None in case of an error, e.g. there is no such
                           option.
        """
        try:
            return ConfigParser.ConfigParser.get(self, 'Bluetracker', option)
        except:
            return None

class _Option(object):
    """
    Class for an option.
    """
    def __init__(self, name, description, default=None, domain=None, type='str("%s")'):
        """
        Initialisation.

        Mandatory:
        @param  name          (str)   The name of the option.
        @param  default       (str)   The default value of the option.
        @param  description   (str)   A descriptive documentation string.

        #Optional
        @param  domain        (dict)  Which values are accepted. The value as
                                      key, a description as value.
        @param  type          (str)   The type of the value of the option.
                                      F.ex. 'str(%s)' (default), 'int(str(%s))'.
        """
        #Mandatory
        self.name = name
        self.default = default
        self.description = description

        #Optional
        self.domain = domain
        self.type = type

    def domain_has_key(self, key):
        """
        Checks if the given key is in the domain.

        @param key     (str)       The key to check.
        @return        (boolean)   True if the key is in the domain.
        """
        if self.domain:
            for item in self.domain.keys():
                try:
                    if item.lower() == key.lower():
                        return True
                except:
                    if item == key:
                        return True
                    elif str(item) == str(key):
                        return True
            return False
        else:
            return True
