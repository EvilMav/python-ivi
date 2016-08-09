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
class siglentSDG2000X(ivi.Driver, fgen.Base, fgen.StdFunc, fgen.ArbWfm,
                      fgen.SoftwareTrigger, fgen.Burst,
                      fgen.ArbChannelWfm):
    """ Siglent SDG2042X function/arbitrary waveform generator driver """

    @staticmethod
    def _parse_response_to_dict(resp):
        header, data = tuple(resp.split(' ', 2))

        channel_str, command = tuple(header.split(':'))
        channel_id = 2 if channel_str == 'C2' else 1
        result = dict(_chan=channel_id, _cmd=command)

        parts = data.split(',')
        if len(parts) % 2 > 0:  # in case of uneven length, treat the first entry as a direct response to command
            parts.insert(0, command)

        pairs = zip(parts[::2], parts[1::2])
        for pair in pairs:
            result[pair[0]] = pair[1]

        return result

    def __init__(self, *args, **kwargs):
        self.__dict__.setdefault('_instrument_id', '')

        super(siglentSDG2000X, self).__init__(*args, **kwargs)

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

        super(siglentSDG2000X, self)._initialize(resource, id_query, reset, **keywargs)

        # interface clear
        if not self._driver_operation_simulate:
            self._clear()

        # check ID
        if id_query and not self._driver_operation_simulate:
            inst_id = self.identity.instrument_model
            inst_id_check = self._instrument_id
            inst_id_short = inst_id[:len(inst_id_check)]
            if inst_id_short != inst_id_check:
                raise Exception("Instrument ID mismatch, expecting %s, got %s", id_check, id_short)

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

    def _init_outputs(self):
        try:
            super(siglentSDG2000X, self)._init_outputs()
        except AttributeError:
            pass

        self._output_enabled = list()
        for i in range(self._output_count):
            self._output_enabled.append(False)

    def _load_catalog(self):  # TODO
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
        if value not in fgen.OperationMode:
            raise ivi.ValueNotSupportedException()
        self._output_operation_mode[index] = value

    def _get_output_enabled(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = siglentSDG2000X._parse_response_to_dict(self._ask("C%d:OUTP?" % (index + 1)))
            if not 'OUTP' in resp.keys():
                raise ivi.UnexpectedResponseException()

            resp_outp = resp['OUTP']
            if resp_outp == 'ON':
                self._output_enabled[index] = True
            elif resp_outp == 'OFF':
                self._output_enabled[index] = False
            else:


            self._set_cache_valid(index=index)
        return self._output_enabled[index]

    def _set_output_enabled(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = bool(value)
        if not self._driver_operation_simulate:
            self._write("C{}:OUTP {}".format(index + 1, 'ON' if value else 'OFF'))
        self._output_enabled[index] = value
        self._set_cache_valid(index=index)

    def _get_output_impedance(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = siglentSDG2000X._parse_response_to_dict(self._ask("C{}:OUTP?".format(index + 1)))
            if not ('LOAD' in resp.keys()):
                raise ivi.UnexpectedResponseException()

            resp_load = resp['LOAD']
            self._output_impedance[index] = 0 if resp_load == 'HZ' else int(resp_load)
        self._set_cache_valid(index=index)
        return self._output_impedance[index]

    def _set_output_impedance(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = int(value)
        if not self._driver_operation_simulate:
            self._write("C{}:OUTP LOAD, {}".format(index + 1, value if value > 0 else 'HZ'))

        self._output_impedance[index] = value
        self._set_cache_valid(index=index)

    def _get_output_mode(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = siglentSDG2000X._parse_response_to_dict(self._ask("C{}:BSWV?".format(index)))
            if not 'WVTP' in resp.keys():
                raise ivi.UnexpectedResponseException()

            self._output_mode[index] = 'arbitrary' if (resp['WVTP'] == 'ARB') else 'function'
            self._set_cache_valid(index=index)
        return self._output_mode[index]

    def _set_output_mode(self, index, value):
        index = ivi.get_index(self._output_name, index)
        if value not in fgen.OutputMode:
            raise ivi.ValueNotSupportedException()
        if not self._driver_operation_simulate:
            if value == 'function':
                self._write("C{}:fg:state 1")
            elif value == 'arbitrary':
                self._write(":fg:state 0")
        self._output_mode[index] = value
        for k in range(self._output_count):
            self._set_cache_valid(valid=False, index=k)
        self._set_cache_valid(index=index)

    # TODO: ----------
    def _get_output_reference_clock_source(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":clock:source?").split(' ', 1)[1]
            value = resp.lower()
            self._output_reference_clock_source[index] = value
            self._set_cache_valid(index=index)
        return self._output_reference_clock_source[index]

    def _set_output_reference_clock_source(self, index, value):
        index = ivi.get_index(self._output_name, index)
        if value not in fgen.SampleClockSource:
            raise ivi.ValueNotSupportedException()
        if not self._driver_operation_simulate:
            self._write(":clock:source %s" % value)
        self._output_reference_clock_source[index] = value
        for k in range(self._output_count):
            self._set_cache_valid(valid=False, index=k)
        self._set_cache_valid(index=index)

    def abort_generation(self):
        pass

    def initiate_generation(self):
        pass

    def _get_output_standard_waveform_amplitude(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":fg:ch%d:amplitude?" % (index + 1)).split(' ', 1)[1]
            self._output_standard_waveform_amplitude[index] = float(resp)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_amplitude[index]

    def _set_output_standard_waveform_amplitude(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate:
            self._write(":fg:ch%d:amplitude %e" % (index + 1, value))
        self._output_standard_waveform_amplitude[index] = value
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_dc_offset(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":fg:ch%d:offset?" % (index + 1)).split(' ', 1)[1]
            self._output_standard_waveform_dc_offset[index] = float(resp)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_dc_offset[index]

    def _set_output_standard_waveform_dc_offset(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate:
            self._write(":fg:ch%d:offset %e" % (index + 1, value))
        self._output_standard_waveform_dc_offset[index] = value
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_duty_cycle_high(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_standard_waveform_duty_cycle_high[index]

    def _set_output_standard_waveform_duty_cycle_high(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        self._output_standard_waveform_duty_cycle_high[index] = value

    def _get_output_standard_waveform_start_phase(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_standard_waveform_start_phase[index]

    def _set_output_standard_waveform_start_phase(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        self._output_standard_waveform_start_phase[index] = value

    def _get_output_standard_waveform_frequency(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":fg:frequency?").split(' ', 1)[1]
            self._output_standard_waveform_frequency[index] = float(resp)
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_frequency[index]

    def _set_output_standard_waveform_frequency(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate:
            self._write(":fg:frequency %e" % value)
        self._output_standard_waveform_frequency[index] = value
        for k in range(self._output_count):
            self._set_cache_valid(valid=False, index=k)
        self._set_cache_valid(index=index)

    def _get_output_standard_waveform_waveform(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":fg:ch%d:shape?" % (index + 1)).split(' ', 1)[1]
            value = resp.lower()
            value = [k for k, v in StandardWaveformMapping.items() if v == value][0]
            self._output_standard_waveform_waveform[index] = value
            self._set_cache_valid(index=index)
        return self._output_standard_waveform_waveform[index]

    def _set_output_standard_waveform_waveform(self, index, value):
        index = ivi.get_index(self._output_name, index)
        if value not in StandardWaveformMapping:
            raise ivi.ValueNotSupportedException()
        if not self._driver_operation_simulate:
            self._write(":fg:ch%d:shape %s" % (index + 1, StandardWaveformMapping[value]))
        self._output_standard_waveform_waveform[index] = value
        self._set_cache_valid(index=index)

    def _get_output_arbitrary_gain(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":ch%d:amplitude?" % (index + 1)).split(' ', 1)[1]
            self._output_arbitrary_gain[index] = float(resp)
            self._set_cache_valid(index=index)
        return self._output_arbitrary_gain[index]

    def _set_output_arbitrary_gain(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate:
            self._write(":ch%d:amplitude %e" % (index + 1, value))
        self._output_arbitrary_gain[index] = value
        self._set_cache_valid(index=index)

    def _get_output_arbitrary_offset(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":ch%d:offset?" % (index + 1)).split(' ', 1)[1]
            self._output_arbitrary_offset[index] = float(resp)
            self._set_cache_valid(index=index)
        return self._output_arbitrary_offset[index]

    def _set_output_arbitrary_offset(self, index, value):
        index = ivi.get_index(self._output_name, index)
        value = float(value)
        if not self._driver_operation_simulate:
            self._write(":ch%d:offset %e" % (index + 1, value))
        self._output_arbitrary_offset[index] = value
        self._set_cache_valid(index=index)

    def _get_output_arbitrary_waveform(self, index):
        index = ivi.get_index(self._output_name, index)
        if not self._driver_operation_simulate and not self._get_cache_valid(index=index):
            resp = self._ask(":ch%d:waveform?" % (index + 1)).split(' ', 1)[1]
            self._output_arbitrary_waveform[index] = resp.strip('"').lower()
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
