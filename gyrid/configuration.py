#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2007-2011  Roel Huybrechts
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
    def __init__(self, mgr, configfile):
        """
        Initialisation. Construct an empty list of options, and fill it
        with all the Options.

        @param  configfile   URL of the configfile to write to.
        """
        self.mgr = mgr
        self.options = []
        self.configfile = configfile
        self._define_options()
        self.configparser = _ConfigurationParser(self)

    def _define_options(self):
        """
        Create all options and add them to the list.
        """
        buffer_size = _Option(name = 'buffer_size',
            description = 'The buffer length in seconds. This is the amount ' +
                'of time a device may disappear and appear again without it ' +
                'being noticed. This option also influences the inquiry ' +
                'time, which is defined as ceil(buffer_size/1.28).',
            type = 'float("%s")',
            values = {10.24: 'Buffer size to match the inquiry time of ' +
                '8*1.28s.'},
            default = 10.24)

        alix_led_support = _Option(name = 'alix_led_support',
            description = 'Support for flashing LEDs on ALIX boards.',
            type = '"%s".lower().strip() in ["true", "yes", "y", "1"]',
            values = {True: 'Enable support.', False: 'Disable support.'},
            default = True)

        time_format = _Option(name = 'time_format',
            description = 'The time format to use in the logfile. This ' +
                'string is passed to the time.strftime() function. Hint: ' +
                'don\'t use %z, it doesn\'t work.',
            values = {'%Y%m%d-%H%M%S-%Z': 'Use the YYYYMMDD-HHMMSS-TZ format.'},
            default = '%Y%m%d-%H%M%S-%Z')

        enable_inquiry_log = _Option(name = 'enable_inquiry_log',
            description = 'Enable logging of Bluetooth inquiries. This ' +
                'includes the starttime of each inquiry and enables to ' +
                'determine when each sensor was active scanning.',
            type = '"%s".lower().strip() in ["true", "yes", "y", "1"]',
            values = {True: 'Enable inquiry logging.', False: \
                'Disable inquiry logging.'},
            default = True)

        enable_rssi_log = _Option(name = 'enable_rssi_log',
            description = 'Enable logging of received RSSI data.',
            type = '"%s".lower().strip() in ["true", "yes", "y", "1"]',
            values = {True: 'Enable RSSI logging.', False: \
                'Disable RSSI logging.'},
            default = True)

        minimum_rssi = _Option(name = 'minimum_rssi',
            description = 'The minimum RSSI value for a detection to be ' +
                'recorded. None to record all detections. This is a ' +
                'potentially dangerous option as it can greatly reduce ' +
                'the amount of data recorded. Use with care.',
            type = 'self._parse_int(%s)',
            values = {},
            default = None)

        excluded_devices = _Option(name = 'excluded_devices',
            description = 'A list of HCI device-ID\'s to exclude from ' +
                'scanning. For example: 0 to exclude hci0, None to enable ' +
                'all devices.',
            type = '[j for j in [self._parse_int(i) ' +
                'for i in "%s".split(",")] if j != None]',
            values = {},
            default = None)

        blacklist_file = _Option(name = 'blacklist_file',
            description = 'Path to the blacklist file containing Bluetooth ' +
                'MAC-addresses excluded from registration.',
            values = {},
            default = '/etc/gyrid/blacklist.conf')

        enable_hashing = _Option(name = 'enable_hashing',
            description = 'Enable hashing of privacy sensitive data.',
            type = '"%s".lower().strip() in ["true", "yes", "y", "1"]',
            values = {True: 'Enable hashing.', False: \
                'Disable hashing.'},
            default = True)

        hash_salt = _Option(name = 'hash_salt',
            description = 'Salt to use when hashing. This is parsed by strftime ' +
                'to enable time-based salting.',
            values = {},
            default = "")

        arduino_conffile = _Option(name = 'arduino_conffile',
            description = 'Path to the Arduino rotating platform ' +
                'configuration file. This should be in CSV format, ' +
                'containing the following fields: MAC-address of the ' +
                'scanning device, filename of the device node of the ' +
                'corresponding Arduino (without /dev/), turning resolution ' +
                '(i.e. in how many parts the 180 degree arc is divided).',
            values = {},
            default = '/etc/gyrid/arduino.conf')

        network_server_host = _Option(name = 'network_server_host',
            description = 'The network host of the server to talk to. ' +
                'This can be an IP-address or a domain name. Disable ' +
                'networking support when None.',
            type = '[i for i in "%s".split(",") if i != "None"]',
            values = {},
            default = None)

        network_server_port = _Option(name = 'network_server_port',
            description = 'The TCP port to be used on the server.',
            type = 'self._parse_int(%s)',
            values = {},
            default = 2583)

        network_ssl_client_crt = _Option(name = 'network_ssl_client_crt',
            description = 'Path to the SSL client certificate. None to ' + \
                'disable SSL.',
            values = {},
            default = '/usr/share/gyrid/ssl/client.crt')

        network_ssl_client_key = _Option(name = 'network_ssl_client_key',
            description = 'Path to the SSL client key. None to ' + \
                'disable SSL.',
            values = {},
            default = '/usr/share/gyrid/ssl/client.key')

        network_cache_limit = _Option('network_cache_limit',
            description = 'Maximum size of the network cache file ' +
                'in megabytes (MB). Defaults to 250 MB. When this maximum ' +
                'size is reached, caching is suspended.',
            values = {},
            default = 250)

        self.options.extend([buffer_size, alix_led_support, time_format,
            enable_rssi_log, enable_inquiry_log, minimum_rssi, excluded_devices,
            blacklist_file, network_server_host, network_server_port,
            network_ssl_client_crt, network_ssl_client_key, network_cache_limit,
            arduino_conffile, enable_hashing, hash_salt])

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
            value = self.configparser.get_value(option)
            if value != None:
                config = eval(optionObj.type % value)
            else:
                if not optionObj.hidden:
                    raise ValueError("No valid value.")
                else:
                    config = None
        except:
            self.mgr.main.log_error('Warning',
                "Issue concerning option '%s' : " % option + \
                str(sys.exc_info()[1]) + \
                " [Using default value: %s]" % optionObj.default)
            config = None

        if config != None and optionObj.values_has_key(config):
            return config
        elif config != None:
            self.mgr.main.log_error('Warning',
                "Wrong value for option %(option)s: '%(value)s'." % \
                {'option': optionObj.name, 'value': config} + \
                "[Using default value: %s]" % optionObj.default)

        if optionObj.default == None and optionObj.type == 'str("%s")':
            return None
        else:
            return eval(optionObj.type % optionObj.default)

    def _parse_int(self, integer):
        """
        Parse the argument as an integer. Return the integer value on success,
        None on ValueError.
        """
        try:
            return int(integer)
        except (ValueError, TypeError):
            return None

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
        try:
            ConfigParser.ConfigParser.read(self, self.config_file_location)
        except ConfigParser.ParsingError:
            self.update_config_file(force=True)
            ConfigParser.ConfigParser.read(self, self.config_file_location)

    def update_config_file(self, force=False):
        """
        If no configuration file exists, copy a new default one.

        @param  force   Force writing of default configuration, even if the
                          file already exists. Defaults to False.
        """
        if force and os.path.isfile(self.config_file_location):
            os.rename(self.config_file_location,
                self.config_file_location + '.bad')

        if force or not os.path.isfile(self.config_file_location):
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
        default = '# Gyrid configuration file\n[Gyrid]\n\n'
        for option in self.configuration.options:
            if not option.hidden:
                default += "\n# ".join(textwrap.wrap(
                    "# %s" % option.description, 78))
                if option.values:
                    default += '\n#  Values:'
                    for key in option.values.items():
                        if key[0] == option.default:
                            defaultValue = '(default) '
                        else:
                            defaultValue = ''
                        default += '\n#  %s - %s%s' % \
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
            return ConfigParser.ConfigParser.get(self, 'Gyrid', option)
        except:
            return None

class _Option(object):
    """
    Class for an option.
    """
    def __init__(self, name, description, default, values, type='str("%s")',
            hidden=False):
        """
        Initialisation.

        Mandatory:
        @param  name          (str)   The name of the option.
        @param  description   (str)   A descriptive documentation string.
        @param  values        (dict)  Which values are accepted. The value as
                  key, a description as value. If there's only one key,
                  this value is treated as a default and all other values are
                  accepted too. If there are multiple keys, these values are
                  restrictive.

        Optional
        @param  type          (str)   The type of the value of the option.
                  F.ex. 'str("%s")' (default), 'int(str(%s))'.
        @param  hidden        (bool)  If this is a hidden option, one that is
                  not written out to the config file. Defaults to False.
        """
        #Mandatory
        self.name = name
        self.description = description
        self.default = default
        self.values = values

        #Optional
        self.type = type
        self.hidden = hidden

    def values_has_key(self, key):
        """
        Checks if the given key is in the values
        dictionary.

        @param key     (str)       The key to check.
        @return        (boolean)   True if the key is in the dict.
        """
        if len(self.values) <= 1:
            return True
        else:
            for item in self.values.keys():
                try:
                    if item.lower() == key.lower():
                        return True
                except:
                    if item == key:
                        return True
                    elif str(item) == str(key):
                        return True
            return False
