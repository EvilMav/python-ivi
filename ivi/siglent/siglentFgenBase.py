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

import re
from abc import abstractmethod
from warnings import warn

import itertools
from numpy import *

from .. import ivi
from .. import fgen

StandardWaveformMapping = {
    'sine': 'SINE',
    'square': 'PULSE',
    'triangle': 'RAMP',
    'dc': 'DC'
    # Missing: ramp up, ramp down
}


# TODO: Implement frequency counter, AM/FM modulation
class siglentFgenBase(ivi.Driver, fgen.Base, fgen.StdFunc, fgen.ArbWfm,
                      fgen.ArbFrequency,
                      fgen.InternalTrigger, fgen.Trigger, fgen.Burst,
                      fgen.SoftwareTrigger,
                      fgen.ArbChannelWfm):
    """ Siglent function/arbitrary waveform generator driver """

    # region Init

    def __init__(self, *args, **kwargs):
        self.__dict__.setdefault('_instrument_id', '')

        super(siglentFgenBase, self).__init__(*args, **kwargs)

        self._identity_description = \
            "Siglent function/arbitrary waveform generator driver"
        self._identity_identifier = ""
        self._identity_revision = ""
        self._identity_vendor = ""
        self._identity_instrument_manufacturer = ""
        self._identity_instrument_model = ""
        self._identity_instrument_firmware_revision = ""
        self._identity_specification_major_version = 5
        self._identity_specification_minor_version = 0

        # Not currently supported on SDG2000X and SDG1000X
        self._supports_cmr_query = False

        self._init_outputs()

    def _initialize(self, resource=None, id_query=False, reset=False,
                    **keywargs):
        """ Opens an I/O session to the instrument."""

        super(siglentFgenBase, self)._initialize(resource,
                                                 id_query,
                                                 reset,
                                                 **keywargs)

        # interface clear
        if not self._driver_operation_simulate:
            self._clear()

        # check ID
        if id_query and not self._driver_operation_simulate:
            inst_id = self.identity.instrument_model
            inst_id_check = self._instrument_id
            inst_id_short = inst_id[:len(inst_id_check)]
            if inst_id_short != inst_id_check:
                raise Exception("Instrument ID mismatch, expecting %s, got %s",
                                inst_id_check, inst_id_short)

        # reset
        if reset:
            self.utility_reset()

    def _load_id_string(self):
        if self._driver_operation_simulate:
            msg_simulating = "Not available while simulating"

            self._identity_instrument_manufacturer = msg_simulating
            self._identity_instrument_model = msg_simulating
            self._identity_instrument_firmware_revision = msg_simulating
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
        """ Parses a siglent style SCPI response into a dictionary

        Example:
            resp='C1:CMD VALUE0, KEY1, VALUE1, KEY2'
            _parse_response_to_dict(resp) =
                {'_CMD': 'CMD',
                 '_CHANNEL': '1',
                 'CMD': 'VALUE0',
                 'KEY1': 'VALUE1',
                 'KEY2': 'VALUE2'}
        """

        header, data = tuple(resp.split(' ', 2))

        # extract command and channel ID
        if ':' in header:  # split if the command name is prefixed with channel
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

        # in case of uneven length, treat the first entry as a response to
        # the command's name
        if len(parts) % 2 > 0:
            parts.insert(0, command)

        for pair in zip(parts[::2], parts[1::2]):
            result[pair[0]] = pair[1]

        return result

    @staticmethod
    def _convert_waveform_data(data):
        def convert_sample(sample):
            return round(sample * 32767.5 - 0.5) \
                .to_bytes(2, 'little', signed=True)

        bytes_iter = itertools.chain.from_iterable(map(convert_sample, data))
        return len(data) * 2, list(bytes_iter)

    @staticmethod
    def _strip_units(string_with_units):
        """ Removes non-numeric chracters to strip units from a numeric str """
        return re.sub("[a-zA-Z ]", '', string_with_units)

    @staticmethod
    def _prepend_command_with_channel(command, index):
        """ Prepends command with "Cn:" where n is the number of a channel

            command -- Command string to prepend
            index   -- 0-Based channel index (will be incremented) or None to
                        keep the command as it is
        """
        if index is None or index < 0:
            return command

        return "C{}:{}".format(index + 1, command)

    def _get_property_value_by_tag(self, tag, index=None):
        """ Gets a property on the class according to tag.

        Property is the tag name prefixed with an underscore
        """
        value = self.__dict__['_' + tag]
        return value if index is None else value[index]

    def _set_property_value_by_tag(self, tag, value, index=None):
        """ Sets a property on the class according to tag.

        Property is the tag name prefixed with an underscore
        """
        if index is None:
            self.__dict__['_' + tag] = value
        else:
            self.__dict__['_' + tag][index] = value

    def _get_scpi_option_cached(self, command, option=None, channel=None,
                                tag=None, cast_cache=lambda v: v):
        """ Returns the cached option value or requests it from the device

            command -- request command, without question mark,
                        e.g. "OUTP" for request "C1:OUTP?"
            option  -- option key returned for the command,
                        e.g. "AMP" for amplitude in "C1:BTWV DLAY, 1, AMP,1V"
            channel -- channel name for channel-bonded commands
            tag     -- tag provided to the cache dictionary. The cached value
                       will be read and written to self._<tag>. Tag will be
                       inferred from caller name if not provided, e.g. a call
                       from _get_bla() will result in the tag "bla"
            cast_cache -- casting function to convert the value string from SCPI
                          to the cached and returned value
        """

        tag = self._get_cache_tag(tag, skip=2)
        index = ivi.get_index(self._output_name,
                              channel) if channel is not None else -1

        if not self._driver_operation_simulate \
                and not self._get_cache_valid(tag=tag, index=index):
            command_with_channel = self\
                                ._prepend_command_with_channel(command, index)
            # if option not set - set to equal command by default
            option = command if option is None else option
            resp = self._ask(command_with_channel + '?')
            resp = siglentFgenBase._parse_scpi_response_to_dict(resp)
            if not (option in resp.keys()):
                raise ivi.UnexpectedResponseException()

            value = cast_cache(resp[option])
            self._set_property_value_by_tag(tag, value, index)
            self._set_cache_valid(tag=tag, index=index)
            return value
        else:
            return self._get_property_value_by_tag(tag, index)

    def _set_scpi_option_cached(self, value, command, option=None, channel=None,
                                tag=None, cast_option=lambda v: v):
        """ Sets the given option and updates the cache

            value   -- value to set to
            command -- request command, without question mark,
                        e.g. "OUTP" for request "C1:OUTP ON"
            option  -- option key returned for the command,
                        e.g. "AMP" for amplitude in "C1:BTWV AMP,1V"
            channel -- channel name for channel-bonded commands
            tag     -- tag provided to the cache dictionary. The cached value
                        will be read and written to self._<tag>. Tag will be
                        inferred from caller name if not provided, e.g. a call
                        from _get_bla() will result in the tag "bla"
            cast_option  -- function to convert from cached value representation
                            to the device's option format
        """

        tag = self._get_cache_tag(tag, skip=2)
        index = ivi.get_index(self._output_name, channel) \
            if channel is not None else -1
        command_with_channel = self\
            ._prepend_command_with_channel(command, index)

        command_with_option = \
            "{} {}".format(command_with_channel, cast_option(value)) \
            if option is None else \
            "{} {}, {}".format(command_with_channel, option, cast_option(value))

        self._write(command_with_option)
        self._set_property_value_by_tag(tag, value, index)
        self._set_cache_valid(tag=tag, index=index)

    # endregion

    # region Utility

    def _utility_disable(self):
        for i in range(0, self._output_count):
            self._set_output_enabled(i, False)

    def _utility_error_query(self):
        if not self._supports_cmr_query:
            return 0, 'Not supported'

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
            self._write("*RST")  # does NOT work in the original SDG firmware
            self.driver_operation.invalidate_all_attributes()

    def _utility_reset_with_defaults(self):
        self._utility_reset()

    def _utility_self_test(self):
        code = 0
        message = "Self test passed"
        if not self._driver_operation_simulate:
            self._write("*TST?")  # dies NOT work in the original SDG firmware
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

        # initialize channel-indexed lists: values will be updated by the
        # getters on demand
        self._output_enabled = list()
        self._output_operation_mode = list()
        self._output_impedance = list()

        self._output_standard_waveform_waveform = list()
        self._output_standard_waveform_amplitude = list()
        self._output_standard_waveform_dc_offset = list()
        self._output_standard_waveform_start_phase = list()
        self._output_standard_waveform_frequency = list()
        self._output_standard_waveform_duty_cycle_high = list()

        self._output_arbitrary_gain = list()
        self._output_arbitrary_frequency = list()
        self._output_arbitrary_offset = list()
        self._output_arbitrary_waveform = list()
        self._output_arbitrary_sample_rate = list()
        # specifies whether the arbitrary frequency or sample_rate was set last
        self._output_arbitrary_frequency_mode = list()

        for i in range(self._output_count):
            self._output_enabled.append(False)
            self._output_operation_mode.append('continuous')
            self._output_impedance.append(0)

            self._output_standard_waveform_waveform.append('sine')
            self._output_standard_waveform_amplitude.append(2.0)
            self._output_standard_waveform_dc_offset.append(0.0)
            self._output_standard_waveform_start_phase.append(0.0)
            self._output_standard_waveform_frequency.append(1000)
            self._output_standard_waveform_duty_cycle_high.append(50)

            self._output_arbitrary_gain.append(2.0)
            self._output_arbitrary_frequency.append(1000)
            self._output_arbitrary_offset.append(0.0)
            self._output_arbitrary_waveform.append(None)
            self._output_arbitrary_sample_rate.append(1000000)
            self._output_arbitrary_frequency_mode.append('frequency')

            self._output_trigger_source[i] = 'internal'

    def _get_output_operation_mode(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_operation_mode[index]

    def _set_output_operation_mode(self, index, value):
        if value not in fgen.OperationMode:
            raise ivi.ValueNotSupportedException()

        index = ivi.get_index(self._output_name, index)
        self._output_operation_mode[index] = value
        self._update_burst_config(index)

    def _get_output_enabled(self, index):
        return self._get_scpi_option_cached(
            'OUTP',
            channel=index,
            cast_cache=lambda resp: True if resp == 'ON' else False)

    def _set_output_enabled(self, index, value):
        try:
            value = bool(value)
        except:
            raise ivi.InvalidOptionValueException('Value must be a boolean')

        self._set_scpi_option_cached(
            value,
            'OUTP',
            channel=index,
            cast_option=lambda on: 'ON' if on else 'OFF')

    def _get_output_impedance(self, index):
        return self._get_scpi_option_cached(
            'OUTP', option='LOAD',
            channel=index,
            cast_cache=lambda l: 0 if l == 'HZ' else int(l))

    def _set_output_impedance(self, index, value):
        try:
            value = int(value)
        except:
            raise ivi.InvalidOptionValueException('Value must be an int')

        self._set_scpi_option_cached(
            int(value),
            'OUTP', option='LOAD',
            channel=index,
            cast_option=lambda l: 'HZ' if l == 0 else l)

    def _get_output_mode(self, index):
        return self._get_scpi_option_cached(
            'BSWV', option='WVTP',
            channel=index,
            cast_cache=lambda t: 'arbitrary' if (t == 'ARB') else 'function')

    def _set_output_mode(self, index, value):
        old_value = self._get_output_operation_mode(index)

        if value not in ['function', 'arbitrary']:
            raise ivi.ValueNotSupportedException()

        # cache current mode values to allow them to be restored when switching
        # back to the previous mode
        if old_value == 'function':
            self._ensure_function_mode_parameters_cached(index)
        else:
            self._ensure_arbitrary_mode_parameters_cached(index)

        std_wave = StandardWaveformMapping[
            self._output_standard_waveform_waveform[index]]

        self._set_scpi_option_cached(
            value,
            'BSWV', option='WVTP',
            channel=index,
            cast_option=lambda t: 'ARB' if t == 'arbitrary' else std_wave)

        # restore the last set parameters for the current mode
        if value == 'function':
            self._restore_function_mode_parameters_from_cache(index)
        else:
            self._restore_arbitrary_mode_parameters_from_cache(index)

    def _get_output_reference_clock_source(self, index):
        return self._get_scpi_option_cached(
            'ROSC',
            cast_cache=lambda t: 'internal' if (t == 'INT') else 'external')

    def _set_output_reference_clock_source(self, index, value):
        if value not in fgen.SampleClockSource:
            raise ivi.ValueNotSupportedException()

        warn("Per-channel clock source selection is not supported by the "
             "generator. Both channels will be switched.")

        self._set_scpi_option_cached(
            value,
            'ROSC',
            cast_option=lambda t: 'INT' if t == 'internal' else 'EXT')

    def abort_generation(self):
        pass

    def initiate_generation(self):
        pass

    # endregion

    # region Common methods for both wave modes

    def _get_output_common_waveform_amplitude(self, index):
        tag = self._get_cache_tag(skip=2)
        return self._get_scpi_option_cached(
            'BSWV', option='AMP',
            channel=index,
            cast_cache=lambda amp: float(siglentFgenBase._strip_units(amp)),
            tag=tag)

    def _set_output_common_waveform_amplitude(self, index, value):
        tag = self._get_cache_tag(skip=2)
        try:
            value = float(value)
            if value <= 0.0:
                raise Exception()
        except:
            raise ivi.InvalidOptionValueException(
                'Value must be a float bigger then 0')

        self._set_scpi_option_cached(value,
                                     'BSWV', option='AMP',
                                     channel=index,
                                     tag=tag)

    def _get_output_common_waveform_dc_offset(self, index):
        tag = self._get_cache_tag(skip=2)
        return self._get_scpi_option_cached(
            'BSWV', option='OFST',
            channel=index,
            cast_cache=lambda ofst: float(siglentFgenBase._strip_units(ofst)),
            tag=tag)

    def _set_output_common_waveform_dc_offset(self, index, value):
        try:
            value = float(value)
        except:
            raise ivi.InvalidOptionValueException('Value must be a float')

        tag = self._get_cache_tag(skip=2)
        self._set_scpi_option_cached(value,
                                     'BSWV', option='OFST',
                                     channel=index,
                                     tag=tag)

    def _get_output_common_waveform_start_phase(self, index):
        tag = self._get_cache_tag(skip=2)
        return self._get_scpi_option_cached(
            'BSWV', option='PHSE',
            channel=index,
            cast_cache=lambda ph: float(siglentFgenBase._strip_units(ph)),
            tag=tag)

    def _set_output_common_waveform_start_phase(self, index, value):
        try:
            value = float(value)
            if value < 0.0 or value > 360.0:
                raise Exception()
        except:
            raise ivi.InvalidOptionValueException(
                'Value must be a float between 0 and 360')

        tag = self._get_cache_tag(skip=2)
        self._set_scpi_option_cached(value,
                                     'BSWV', option='PHSE',
                                     channel=index,
                                     tag=tag)

    def _get_output_common_waveform_frequency(self, index):
        tag = self._get_cache_tag(skip=2)

        return self._get_scpi_option_cached(
            'BSWV', option='FRQ',
            channel=index,
            cast_cache=lambda ph: float(siglentFgenBase._strip_units(ph)),
            tag=tag)

    def _set_output_common_waveform_frequency(self, index, value):
        try:
            value = float(value)
            if value <= 0.0:
                raise Exception()
        except:
            raise ivi.InvalidOptionValueException(
                'Value must be a float higher then 0')

        tag = self._get_cache_tag(skip=2)
        self._set_scpi_option_cached(value,
                                     'BSWV', option='FRQ',
                                     channel=index,
                                     tag=tag)

    # endregion

    # region Standard waveform mode

    def _is_in_function_mode(self, index):
        return self._get_output_mode(index) == 'function'

    def _ensure_function_mode_parameters_cached(self, index):
        """ Loads all waveform parameters into cache fields so they can be
        restored when switching back from the arbitrary mode """

        if not self._is_in_function_mode(index):
            return

        self._get_output_standard_waveform_amplitude(index)
        self._get_output_standard_waveform_dc_offset(index)
        self._get_output_standard_waveform_duty_cycle_high(index)
        self._get_output_standard_waveform_frequency(index)
        self._get_output_standard_waveform_start_phase(index)
        self._get_output_standard_waveform_waveform(index)

    def _restore_function_mode_parameters_from_cache(self, index):
        index = ivi.get_index(self._output_name, index)

        self._set_output_standard_waveform_waveform(
            index,
            self._output_standard_waveform_waveform[index])
        self._set_output_standard_waveform_amplitude(
            index,
            self._output_standard_waveform_amplitude[index])
        self._set_output_standard_waveform_frequency(
            index,
            self._output_standard_waveform_frequency[index])
        self._set_output_standard_waveform_dc_offset(
            index,
            self._output_standard_waveform_dc_offset[index])
        self._set_output_standard_waveform_start_phase(
            index,
            self._output_standard_waveform_start_phase[index])
        self._set_output_standard_waveform_duty_cycle_high(
            index,
            self._output_standard_waveform_duty_cycle_high[index])

    def _get_output_standard_waveform_amplitude(self, index):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_standard_waveform_amplitude[index]

        return self._get_output_common_waveform_amplitude(index)

    def _set_output_standard_waveform_amplitude(self, index, value):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_standard_waveform_amplitude[index] = value
        else:
            self._set_output_common_waveform_amplitude(index, value)

    def _get_output_standard_waveform_dc_offset(self, index):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_standard_waveform_dc_offset[index]

        return self._get_output_common_waveform_dc_offset(index)

    def _set_output_standard_waveform_dc_offset(self, index, value):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_common_waveform_dc_offset[index] = value
        else:
            self._set_output_common_waveform_dc_offset(index, value)

    def _get_output_standard_waveform_duty_cycle_high(self, index):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_standard_waveform_duty_cycle_high[index]

        return self._get_scpi_option_cached(
            'BSWV', option='DUTY',
            channel=index,
            cast_cache=lambda ph: float(siglentFgenBase._strip_units(ph)))

    def _set_output_standard_waveform_duty_cycle_high(self, index, value):
        if value < 0 or value > 100:
            raise ivi.ValueNotSupportedException()

        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_standard_waveform_duty_cycle_high[index] = value
        else:
            self._set_scpi_option_cached(value, 'BSWV', option='DUTY',
                                         channel=index)

    def _get_output_standard_waveform_start_phase(self, index):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_standard_waveform_start_phase[index]

        return self._get_output_common_waveform_start_phase(index)

    def _set_output_standard_waveform_start_phase(self, index, value):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_standard_waveform_start_phase[index] = value
        else:
            self._set_output_common_waveform_start_phase(index, value)

    def _get_output_standard_waveform_frequency(self, index):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_standard_waveform_frequency[index]

        return self._get_output_common_waveform_frequency(index)

    def _set_output_standard_waveform_frequency(self, index, value):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_standard_waveform_frequency[index] = value
        else:
            self._set_output_common_waveform_frequency(index, value)

    def _get_output_standard_waveform_waveform(self, index):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_standard_waveform_waveform[index]

        return self._get_scpi_option_cached(
            'BSWV', option='WVTP',
            channel=index,
            cast_cache=lambda wf:
            [k for k, v in StandardWaveformMapping.items() if v == wf][0])

    def _set_output_standard_waveform_waveform(self, index, value):
        if not self._is_in_function_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_standard_waveform_waveform[index] = value
        else:
            self._set_scpi_option_cached(
                value,
                'BSWV', option='WVTP',
                channel=index,
                cast_option=lambda v: StandardWaveformMapping[v])

        # endregion

        # region Arbitrary waveform mode

    def _is_in_arbitrary_mode(self, index):
        return self._get_output_mode(index) == 'arbitrary'

    def _ensure_arbitrary_mode_parameters_cached(self, index):
        """ Loads all waveform parameters into cache fields so they can be
        restored when switching back from the function mode """

        if not self._is_in_arbitrary_mode(index):
            return

        self._get_output_arbitrary_gain(index)
        self._get_output_arbitrary_offset(index)
        self._get_output_arbitrary_waveform(index)
        self._get_output_arbitrary_frequency(index)

    def _restore_arbitrary_mode_parameters_from_cache(self, index):
        index = ivi.get_index(self._output_name, index)

        self._set_output_arbitrary_gain(index,
                                        self._output_arbitrary_gain[index])
        self._set_output_arbitrary_offset(index,
                                          self._output_arbitrary_offset[index])

        if self._output_arbitrary_frequency_mode[index] == 'frequency':
            self._set_output_arbitrary_frequency(
                index,
                self._output_arbitrary_frequency[index])
        else:
            self._set_output_arbitrary_sample_rate(
                index,
                self._output_arbitrary_sample_rate[index])

    def _get_output_arbitrary_gain(self, index):
        if not self._is_in_arbitrary_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_arbitrary_gain[index]

        return self._get_output_common_waveform_amplitude(index)

    def _set_output_arbitrary_gain(self, index, value):
        if not self._is_in_arbitrary_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_arbitrary_gain[index] = value
        else:
            self._set_output_common_waveform_amplitude(index, value)

    def _get_output_arbitrary_offset(self, index):
        if not self._is_in_arbitrary_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_arbitrary_offset[index]

        return self._get_output_common_waveform_dc_offset(index)

    def _set_output_arbitrary_offset(self, index, value):
        if not self._is_in_arbitrary_mode(index):
            index = ivi.get_index(self._output_name, index)
            self._output_arbitrary_offset[index] = value
        else:
            self._set_output_common_waveform_dc_offset(index, value)

    def _get_output_arbitrary_frequency(self, index):
        if not self._is_in_arbitrary_mode(index):
            index = ivi.get_index(self._output_name, index)
            return self._output_arbitrary_waveform_frequency[index]
        return self._get_output_common_waveform_frequency(index)

    def _set_output_arbitrary_frequency(self, channel, value):
        index = ivi.get_index(self._output_name, channel)

        if not self._is_in_arbitrary_mode(index):
            self._output_arbitrary_waveform_frequency[index] = value
        else:
            self._set_output_common_waveform_frequency(channel, value)

        self._output_arbitrary_frequency_mode[index] = 'frequency'

        self._set_cache_valid(valid=False,
                              tag='_output_arbitrary_sample_rate',
                              index=index)
        self._set_cache_valid(valid=False,
                              tag='_arbitrary_sample_rate',
                              index=index)

    @abstractmethod
    def _get_output_arbitrary_waveform(self, index):
        pass

    @abstractmethod
    def _set_output_arbitrary_waveform(self, index, value):
        pass

    @abstractmethod
    def _get_arbitrary_sample_rate(self):
        pass

    @abstractmethod
    def _set_arbitrary_sample_rate(self, value):
        pass

    def _arbitrary_waveform_clear(self, handle):
        pass

    @abstractmethod
    def _arbitrary_waveform_create(self, data):
        pass

    def _arbitrary_clear_memory(self):
        pass

    def _arbitrary_waveform_create_channel_waveform(self, index, data):
        handle = self._arbitrary_waveform_create(data)
        self._set_output_arbitrary_waveform(index, handle)
        return handle

    # endregion

    # region Trigger and Burst

    def _update_burst_config(self, index):
        index = ivi.get_index(self._output_name, index)
        if self._output_operation_mode[index] in ['continuous', '']:
            cmd = self._prepend_command_with_channel('BTWV STATE, OFF', index)
            self._write(cmd)
        elif self._output_operation_mode[index] == 'burst':

            cmd = 'BTWV STATE, ON, GATE_NCYC, NCYC, TIME, {}' \
                .format(self._output_burst_count[index])
            cmd = self._prepend_command_with_channel(cmd, index)
            self._write(cmd)

            # Trigger change is not accepted in the same command for some
            # reason: issue multiple commands instead
            trigger_cmds = ''
            if self._output_trigger_source[index] == 'external':
                trigger_cmds = ['BTWV TRSR,EXT']
            elif self._output_trigger_source[index] == 'internal':
                periods = 1.0 if self._internal_trigger_rate == 0 \
                    else 1.0 / self._internal_trigger_rate
                trigger_cmds = ['BTWV TRSR,INT', 'BTWV PRD,{}S'.format(periods)]
            elif self._output_trigger_source[index] == 'software':
                trigger_cmds = ['BTWV TRSR,MAN']

            for trigger_cmd in trigger_cmds:
                cmd = self._prepend_command_with_channel(trigger_cmd, index)
                self._write(cmd)
        else:
            raise ivi.ValueNotSupportedException()

    def _get_internal_trigger_rate(self):
        return self._internal_trigger_rate

    def _set_internal_trigger_rate(self, value):
        value = float(value)
        self._internal_trigger_rate = value

        # Internal trigger is currently used in the burst mode only - ensure
        # burst configs are updated
        self._update_burst_config(0)
        self._update_burst_config(1)

    def _get_output_burst_count(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_burst_count[index]

    def _set_output_burst_count(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = int(value)
        self._output_burst_count[index] = value
        self._update_burst_config(index)

    def _get_output_trigger_source(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_trigger_source[index]

    def _set_output_trigger_source(self, index, value):
        if value not in ['internal', 'external', 'software']:
            raise ivi.ValueNotSupportedException()
        index = ivi.get_index(self._output_name, index)
        self._output_trigger_source[index] = value
        self._update_burst_config(index)

    def _send_software_trigger(self):
        for i in range(self._output_count):
            if self._get_output_operation_mode(i) == 'burst' \
                    and self._get_output_trigger_source(i) == 'software':
                self._write(self._prepend_command_with_channel('BTWV MTRIG', i))

# endregion
