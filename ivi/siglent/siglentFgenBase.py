"""

Python Interchangeable Virtual Instrument Library

Copyright (c) 2016 Ilya Elenskiy
Copyright (c) 2012-2014 Alex Forencich

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

"""

import time
import struct

import re
from numpy import *

from .. import ivi
from .. import fgen

StandardWaveformMapping = {
    'sine': 'SINE',
    'square': 'SQUARE',
    'triangle': 'RAMP',
    'dc': 'DC'
    # Missing: ramp up, ramp down
}


# TODO: more groups? ModulateAM, ModulateFM
class siglentFgenBase(ivi.Driver, fgen.Base, fgen.StdFunc, fgen.ArbWfm,
                      fgen.SoftwareTrigger, fgen.Burst,
                      fgen.ArbChannelWfm):
    """ Siglent SDG2042X function/arbitrary waveform generator driver """

# region Init

    def __init__(self, *args, **kwargs):
        self.__dict__.setdefault('_instrument_id', '')

        super(siglentFgenBase, self).__init__(*args, **kwargs)

        self._output_count = 2
        # TODO: set all this stuff when updating the usages
        self._arbitrary_sample_rate = 0
        self._arbitrary_waveform_number_waveforms_max = 0
        self._arbitrary_waveform_size_max = 256 * 1024
        self._arbitrary_waveform_size_min = 64
        self._arbitrary_waveform_quantum = 8

        self._catalog_names = list()

        self._arbitrary_waveform_n = 0

        self._identity_description = "Siglent SDG2000X function/arbitrary waveform generator driver"
        self._identity_identifier = ""
        self._identity_revision = ""
        self._identity_vendor = ""
        self._identity_instrument_manufacturer = "Siglent"
        self._identity_instrument_model = ""
        self._identity_instrument_firmware_revision = ""
        self._identity_specification_major_version = 5
        self._identity_specification_minor_version = 0
        self._identity_supported_instrument_models = ['SDG2042X', 'SDG2082X', 'SDG2122X']

        self._init_outputs()

    def _initialize(self, resource=None, id_query=False, reset=False, **keywargs):
        """ Opens an I/O session to the instrument."""

        super(siglentFgenBase, self)._initialize(resource, id_query, reset, **keywargs)

        # interface clear
        if not self._driver_operation_simulate:
            self._clear()

        # check ID
        if id_query and not self._driver_operation_simulate:
            inst_id = self.identity.instrument_model
            inst_id_check = self._instrument_id
            inst_id_short = inst_id[:len(inst_id_check)]
            if inst_id_short != inst_id_check:
                raise Exception("Instrument ID mismatch, expecting %s, got %s", inst_id_check, inst_id_short)

        # reset
        if reset:
            self.utility_reset()

    def _load_id_string(self):
        if self._driver_operation_simulate:
            self._identity_instrument_manufacturer = "Not available while simulating"
            self._identity_instrument_model = "Not available while simulating"
            self._identity_instrument_firmware_revision = "Not available while simulating"
        else:
            lst = self._ask("*IDN?").split(",")
            self._identity_instrument_manufacturer = lst[0]
            self._identity_instrument_model = lst[1]
            self._identity_instrument_firmware_revision = lst[3]
            self._set_cache_valid(True, 'identity_instrument_manufacturer')
            self._set_cache_valid(True, 'identity_instrument_model')
            self._set_cache_valid(True, 'identity_instrument_firmware_revision')

    def _get_identity_instrument_manufacturer(self):
        if self._get_cache_valid():
            return self._identity_instrument_manufacturer
        self._load_id_string()
        return self._identity_instrument_manufacturer

    def _get_identity_instrument_model(self):
        if self._get_cache_valid():
            return self._identity_instrument_model
        self._load_id_string()
        return self._identity_instrument_model

    def _get_identity_instrument_firmware_revision(self):
        if self._get_cache_valid():
            return self._identity_instrument_firmware_revision
        self._load_id_string()
        return self._identity_instrument_firmware_revision

# endregion

# region Common methods

    @staticmethod
    def _parse_scpi_response_to_dict(resp):
        """ Parses a siglent style dictionary-like SCPI response into a python dictionary
        Example:
            resp='C1:CMD VALUE0, KEY1, VALUE1, KEY2'
            _parse_response_to_dict(resp) =
                {'_CMD': 'CMD', '_CHANNEL': '1', 'CMD': 'VALUE0', 'KEY1': 'VALUE1', 'KEY2': 'VALUE2'} """
        header, data = tuple(resp.split(' ', 2))

        # extract command and channel ID
        if ':' in header:      # if the command name is prefixed with channel ID, split it out
            channel_str, command = tuple(header.split(':'))
            if channel_str == 'C1':
                channel_id = 1
            elif channel_str == 'C2':
                channel_id = 2
            else:
                raise ivi.UnexpectedResponseException('')

            result = {'_CHAN': channel_id, '_CMD': command}
        else:
            command = header
            result = {'_CMD': command}

        # extract options dictionary
        parts = data.split(',')
        if len(parts) % 2 > 0:  # in case of uneven length, treat the first entry as a response to command name
            parts.insert(0, command)

        for pair in zip(parts[::2], parts[1::2]):
            result[pair[0]] = pair[1]

        return result

    @staticmethod
    def _strip_units(string_with_units):
        """ Removes non-numeric chracters to strip units from a numeric string """
        return re.su.sub("[^a-zA-Z ]", '', string_with_units)

    @staticmethod
    def _prepend_command_with_channel(command, index):
        """ If channel is not None, prepends command with "Cn:" where n is the index """
        if index is None:
            return command

        return "C{}:{}".format(index + 1, command)

    def _get_property_value_by_tag(self, tag, index=None):
        """ Gets a property on the class according to tag. Property is the tag name prefixed with an underscore """
        value = self.__dict__['_' + tag]
        return value if index is None else value[index]

    def _set_property_value_by_tag(self, tag, value, index=None):
        """ Sets a property on the class according to tag. Property is the tag name prefixed with an underscore """
        if index is None:
            self.__dict__['_' + tag] = value
        else:
            self.__dict__['_' + tag][index] = value

    def _get_scpi_option_cached(self, command, option=None, channel=None, tag=None, cast_cache=None):
        """ Returns the cached value for the option or requests it from the device if non cached

            command - request command, without question mark, e.g. "OUTP" for request "C1:OUTP?"
            option  - option key returned for the command, e.g. "AMP" for amplitude in "C1:BTWV DLAY, 1, AMP,1V"
            channel - channel name for channel-bonded commands
            tag     - tag provided to the cache dictionary. The cached value will be read and written to self._<tag>.
                      Tag will be inferred from caller name if not provided, e.g. a call from _get_bla() will result
                      in the tag "bla"
            cast_cache - casting function to convert the value string from SCPI to the result value
        """

        tag = self._get_cache_tag(tag, skip=2)
        index = ivi.get_index(self._output_name, channel) if channel is not None else None

        if not self._driver_operation_simulate and not self._get_cache_valid(tag=tag, index=index):
            command_with_channel = self._prepend_command_with_channel(command, index)
            option = command if option is None else option  # if option not set - set to equal command by default

            resp = siglentFgenBase._parse_scpi_response_to_dict(self._ask(command_with_channel + '?'))
            if not (option in resp.keys()):
                raise ivi.UnexpectedResponseException()

            value = resp[option] if cast_cache is None else cast_cache(resp[option])
            self._set_property_value_by_tag(tag, value, index)
            self._set_cache_valid(tag=tag, index=index)
            return value
        else:
            return self._get_property_value_by_tag(tag, index)

    def _set_scpi_option_cached(self, value, command, option=None, channel=None, tag=None, cast_option=None):
        """ Sets the given option and updates the cache

            value   - value to set to
            command - request command, without question mark, e.g. "OUTP" for request "C1:OUTP ON"
            option  - option key returned for the command, e.g. "AMP" for amplitude in "C1:BTWV AMP,1V"
            channel - channel name for channel-bonded commands
            tag     - tag provided to the cache dictionary. The cached value will be read and written to self._<tag>.
                      Tag will be inferred from caller name if not provided, e.g. a call from _get_bla() will result
                      in the tag "bla"
            cast_option  - function to convert from cached value representation to the device's option format
        """

        tag = self._get_cache_tag(tag, skip=2)
        index = ivi.get_index(self._output_name, channel) if channel is not None else None
        command_with_channel = self._prepend_command_with_channel(command, index)
        command_with_option = "{} {}".format(command_with_channel, value) if option is None else \
                              "{} {}, {}".format(command_with_channel, option, value)
        self._write(command_with_option)
        self._set_property_value_by_tag(tag, value, index)
        self._set_cache_valid(tag=tag, index=index)

# endregion

# region Utility

    def _utility_disable(self):
        pass

    def _utility_error_query(self):
        if not self._driver_operation_simulate:
            messages = {0: 'No error',
                        1: 'Unrecognized command/query header',
                        2: 'Invalid character',
                        3: 'Invalid separator',
                        4: 'Missing parameter',
                        5: 'Unrecognized keyword',
                        6: 'String error',
                        7: 'Parameter can’t allowed',
                        8: 'Command String Too Long',
                        9: 'Query cannot allowed',
                        10: 'Missing Query mask',
                        11: 'Invalid parameter',
                        12: 'Parameter syntax error',
                        13: 'Filename too long',
                        14: 'Directory not exist'
                        }
            error_code = int(self._ask("CMR?").split(' ')[1])
            return error_code, messages[error_code]
        return 0, 'No error'

    def _utility_lock_object(self):
        pass

    def _utility_reset(self):
        if not self._driver_operation_simulate:
            self._write("*RST")
            self.driver_operation.invalidate_all_attributes()

    def _utility_reset_with_defaults(self):
        self._utility_reset()

    def _utility_self_test(self):
        code = 0
        message = "Self test passed"
        if not self._driver_operation_simulate:
            self._write("*TST?")
            # wait for test to complete
            time.sleep(60)
            code = int(self._read())
            if code != 0:
                message = "Self test failed"
        return code, message

    def _utility_unlock_object(self):
        pass

# endregion

# region Output settings

    def _init_outputs(self):
        try:
            super(siglentFgenBase, self)._init_outputs()
        except AttributeError:
            pass

        self._output_enabled = list()
        for i in range(self._output_count):
            self._output_enabled.append(False)  # TODO: sync to device

    def _load_catalog(self):  # TODO !!!!!!
        self._catalog = list()
        self._catalog_names = list()
        if not self._driver_operation_simulate:
            raw = self._ask(":memory:catalog:all?").lower()
            raw = raw.split(' ', 1)[1]

            l = raw.split(',')
            l = [s.strip('"') for s in l]
            self._catalog = [l[i:i + 3] for i in range(0, len(l), 3)]
            self._catalog_names = [l[0] for l in self._catalog]

    def _get_output_operation_mode(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_operation_mode[index]

    def _set_output_operation_mode(self, index, value):
        index = ivi.get_index(self._output_name, index)
        if value not in fgen.OperationMode:      # TODO
            raise ivi.ValueNotSupportedException()
        self._output_operation_mode[index] = value

    def _get_output_enabled(self, index):
        return self._get_scpi_option_cached('OUTP',
                                            channel=index,
                                            cast_cache=lambda resp: True if resp == 'ON' else False)

    def _set_output_enabled(self, index, value):
        self._set_scpi_option_cached(value,
                                     'OUTP',
                                     channel=index,
                                     cast_option=lambda on: 'ON' if on else 'OFF')

    def _get_output_impedance(self, index):
        return self._get_scpi_option_cached('OUTP', option='LOAD',
                                            channel=index,
                                            cast_cache=lambda l: 0 if load == 'HZ' else int(l))

    def _set_output_impedance(self, index, value):
        self._set_scpi_option_cached(int(value),
                                     'OUTP', option='LOAD',
                                     channel=index,
                                     cast_option=lambda l: 'HZ' if l == 0 else l)

    def _get_output_mode(self, index):
        return self._get_scpi_option_cached('BSWV', option='WVTP',
                                            channel=index,
                                            cast_cache=lambda t: 'arbitrary' if (t == 'ARB') else 'function')

    def _set_output_mode(self, index, value):
        if value not in ['function', 'arbitrary']:
            raise ivi.ValueNotSupportedException()

        self._set_scpi_option_cached(value,
                                     'BSWV', option='WVTP',
                                     channel=index,
                                     cast_option=lambda t: 'ARB' if t == 'arbitrary' else
                                                    StandardWaveformMapping[self._output_standard_waveform_waveform])

    def _get_output_reference_clock_source(self, index):
        return self._get_scpi_option_cached('ROSC',
                                            cast_cache=lambda t: 'internal' if (t == 'INT') else 'external')

    def _set_output_reference_clock_source(self, index, value):
        if value not in fgen.SampleClockSource:
            raise ivi.ValueNotSupportedException()

        self._set_scpi_option_cached(int(value),
                                     'ROSC',
                                     cast_option=lambda t: 'INT' if t == 'internal' else 'EXT')

    def abort_generation(self):
        pass

    def initiate_generation(self):
        pass

# endregion

# region Standard waveform mode

    def _refresh_standard_waveform_mode(self, index):
        """ Sets the last known standard waveform mode parameters """
        # TODO (set at least the mode)

    def _get_output_standard_waveform_amplitude(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and self._get_output_mode(
                index) == 'function' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'AMP' not in resp.keys():
                raise ivi.UnexpectedResponseException()
            amp = siglentFgenBase._strip_units(resp['AMP'])
            self._output_standard_waveform_amplitude[index] = float(amp)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_amplitude[index]

    def _set_output_standard_waveform_amplitude(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'function':
            self._write("C{}:BSWV AMP, {: f}".format(index + 1, value))
        self._output_standard_waveform_amplitude[index] = value
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_dc_offset(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and self._get_output_mode(
                index) == 'function' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'OFST' not in resp.keys():
                raise ivi.UnexpectedResponseException()
            ofst = siglentFgenBase._strip_units(resp['OFST'])

            self._output_standard_waveform_dc_offset[index] = float(ofst)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_dc_offset[index]

    def _set_output_standard_waveform_dc_offset(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'function':
            self._write("C{}:BSWV OFST, {: f}".format(index + 1, value))
        self._output_standard_waveform_dc_offset[index] = value
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_duty_cycle_high(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and \
                        self._get_output_mode(index) == 'function' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'DUTY' not in resp.keys():
                raise ivi.OperationNotSupportedException()  # likely not supported with the current waveform
            duty = siglentFgenBase._strip_units(resp['DUTY'])
            self._output_standard_waveform_duty_cycle_high[index] = float(duty)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_duty_cycle_high[index]

    def _set_output_standard_waveform_duty_cycle_high(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'function':
            self._write("C{}:BSWV DUTY, {: f}".format(index + 1, value))
        self._output_standard_waveform_duty_cycle_high[index] = value
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_start_phase(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and self._get_output_mode(
                index) == 'function' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'PHSE' not in resp.keys():
                raise ivi.OperationNotSupportedException()  # likely not supported with the current waveform
            phse = siglentFgenBase._strip_units(resp['PHSE'])
            self._output_standard_waveform_start_phase[index] = float(phse)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_start_phase[index]

    def _set_output_standard_waveform_start_phase(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'function':
            self._write("C{}:BSWV PHSE, {: f}".format(index + 1, value))
        self._output_standard_waveform_start_phase[index] = value
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_frequency(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and self._get_output_mode(
                index) == 'function' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'FRQ' not in resp.keys():
                raise ivi.OperationNotSupportedException()  # likely not supported with the current waveform
            frq = siglentFgenBase._strip_units(resp['FRQ'])
            self._output_standard_waveform_frequency[index] = float(frq)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_frequency[index]

    def _set_output_standard_waveform_frequency(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'function':
            self._write("C{}:BSWV FRQ, {: f}".format(index + 1, value))
        self._output_standard_waveform_frequency[index] = value
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_waveform(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and self._get_output_mode(
                index) == 'function' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'WVTP' not in resp.keys():
                raise ivi.OperationNotSupportedException()  # likely not supported with the current waveform
            wvtp = siglentFgenBase._strip_units(resp['WVTP'])
            value = [k for k, v in StandardWaveformMapping.items() if v == wvtp][0]
            self._output_standard_waveform_waveform[index] = value
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_waveform[index]

    def _set_output_standard_waveform_waveform(self, index, value):
        index = ivi.get_index(self._output_name, index)
        if value not in StandardWaveformMapping:
            raise ivi.ValueNotSupportedException()
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'function':
            self._write("C{}:BSWV WVTP, {}".format(index + 1, StandardWaveformMapping[value]))
        self._output_standard_waveform_waveform[index] = value
        self._set_cache_valid(index=index)

# endregion

# region Arbitrary waveform mode

    def _refresh_arbitrary_waveform_mode(self, index):
        pass  # TODO

    def _get_output_arbitrary_gain(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and self._get_output_mode(
                index) == 'arbitrary' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'AMP' not in resp.keys():
                raise ivi.UnexpectedResponseException()
            amp = siglentFgenBase._strip_units(resp['AMP'])
            self._output_arbitrary_gain[index] = float(amp)
            self._set_cache_valid(index=index)
        return self._output_arbitrary_gain[index]

    def _set_output_arbitrary_gain(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'arbitrary':
            self._write("C{}:BSWV AMP, {: f}".format(index + 1, value))
        self._output_arbitrary_gain[index] = value
        self._set_cache_valid(index=index)

    def _get_output_arbitrary_offset(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and self._get_output_mode(
                index) == 'arbitrary' and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if 'OFST' not in resp.keys():
                raise ivi.UnexpectedResponseException()
            ofst = siglentFgenBase._strip_units(resp['OFST'])

            self._output_arbitrary_offset[index] = float(ofst)
            self._set_cache_valid(index=index)
        return self._output_arbitrary_offset[index]

    def _set_output_arbitrary_offset(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate and self._get_output_mode(index) == 'arbitrary':
            self._write("C{}:BSWV OFST, {: f}".format(index + 1, value))
        self._output_arbitrary_offset[index] = value
        self._set_cache_valid(index=index)

    def _get_output_arbitrary_waveform(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = siglentFgenBase._parse_response_to_dict(self._ask("C{}:ARWV?".format(index)))
            if 'INDEX' not in resp.keys():
                raise ivi.UnexpectedResponseException()
            idx = siglentFgenBase._strip_units(resp['INDEX'])
            self._output_arbitrary_waveform[index] = int(idx)
            self._set_cache_valid(index=index)
        return self._output_arbitrary_waveform[index]

    def _set_output_arbitrary_waveform(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = str(value).lower()
        # extension must be wfm
        ext = value.split('.').pop()
        if ext != 'wfm':
            raise ivi.ValueNotSupportedException()
        # waveform must exist on arb
        self._load_catalog()
        if value not in self._catalog_names:
            raise ivi.ValueNotSupportedException()
        if not self._driver_operation_simulate:
            self._write(":ch%d:waveform \"%s\"" % (index + 1, value))
        self._output_arbitrary_waveform[index] = value

    def _get_arbitrary_sample_rate(self):
        if not self._driver_operation_simulate and not self._get_cache_valid():
            resp = self._ask(":clock:frequency?").split(' ', 1)[1]
            self._arbitrary_sample_rate = float(resp)
            self._set_cache_valid()
        return self._arbitrary_sample_rate

    def _set_arbitrary_sample_rate(self, value):
        value = float(value)
        if not self._driver_operation_simulate:
            self._write(":clock:frequency %e" % value)
        self._arbitrary_sample_rate = value
        self._set_cache_valid()

    def _get_arbitrary_waveform_number_waveforms_max(self):
        return self._arbitrary_waveform_number_waveforms_max

    def _get_arbitrary_waveform_size_max(self):
        return self._arbitrary_waveform_size_max

    def _get_arbitrary_waveform_size_min(self):
        return self._arbitrary_waveform_size_min

    def _get_arbitrary_waveform_quantum(self):
        return self._arbitrary_waveform_quantum

    def _arbitrary_waveform_clear(self, handle):
        pass

    def _arbitrary_waveform_create(self, data):
        y = None
        x = None
        if type(data) == list and type(data[0]) == float:
            # list
            y = array(data)
        elif type(data) == ndarray and len(data.shape) == 1:
            # 1D array
            y = data
        elif type(data) == ndarray and len(data.shape) == 2 and data.shape[0] == 1:
            # 2D array, hieght 1
            y = data[0]
        elif type(data) == ndarray and len(data.shape) == 2 and data.shape[1] == 1:
            # 2D array, width 1
            y = data[:, 0]
        else:
            x, y = ivi.get_sig(data)

        if x is None:
            x = arange(0, len(y)) / 10e6

        if len(y) % self._arbitrary_waveform_quantum != 0:
            raise ivi.ValueNotSupportedException()

        xincr = ivi.rms(diff(x))

        # get unused handle
        self._load_catalog()
        have_handle = False
        while not have_handle:
            self._arbitrary_waveform_n += 1
            handle = "w%04d.wfm" % self._arbitrary_waveform_n
            have_handle = handle not in self._catalog_names
        self._write(":data:destination \"%s\"" % handle)
        self._write(":wfmpre:bit_nr 12")
        self._write(":wfmpre:bn_fmt rp")
        self._write(":wfmpre:byt_nr 2")
        self._write(":wfmpre:byt_or msb")
        self._write(":wfmpre:encdg bin")
        self._write(":wfmpre:pt_fmt y")
        self._write(":wfmpre:yzero 0")
        self._write(":wfmpre:ymult %e" % (2 / (1 << 12)))
        self._write(":wfmpre:xincr %e" % xincr)

        raw_data = b''

        for f in y:
            # clip at -1 and 1
            if f > 1.0: f = 1.0
            if f < -1.0: f = -1.0

            f = (f + 1) / 2

            # scale to 12 bits
            i = int(f * ((1 << 12) - 2) + 0.5) & 0x000fffff

            # add to raw data, MSB first
            raw_data = raw_data + struct.pack('>H', i)

        self._write_ieee_block(raw_data, ':curve ')

        return handle

    def _arbitrary_clear_memory(self):
        pass

# endregion

# region Trigger and Burst

    def send_software_trigger(self):
        if not self._driver_operation_simulate:
            self._write("*TRG")

    def _get_output_burst_count(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_burst_count[index]

    def _set_output_burst_count(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = int(value)
        self._output_burst_count[index] = value

    def _arbitrary_waveform_create_channel_waveform(self, index, data):
        handle = self._arbitrary_waveform_create(data)
        self._set_output_arbitrary_waveform(index, handle)
        return handle

# endregion




