"""

Python Interchangeable Virtual Instrument Library

Copyright (c) 2016 Ilya Elenskiy

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

from .siglentFgenBase import *

ArbitraryModes = ['DDS', 'TrueArb']


class siglentSDG2000X(siglentFgenBase):
    """ Siglent SDG2000X function/arbitrary waveform generator driver """

    def __init__(self, *args, **kwargs):
        super(siglentSDG2000X, self).__init__(*args, **kwargs)

        self._output_count = 2

        self._arbitrary_sample_rate_max = 75000000
        self._arbitrary_waveform_number_waveforms_max = 0
        self._arbitrary_waveform_size_max = 4000000
        self._arbitrary_waveform_size_min = 4
        self._arbitrary_waveform_quantum = 4
        self._arbitrary_waveform_n = 0

        self._arb_store_names = list()
        self._identity_supported_instrument_models = ['SDG2042X', 'SDG2082X', 'SDG2122X']

        self._add_property('outputs[].arbitrary.sample_rate',
                           self._get_output_arbitrary_sample_rate,
                           self._set_output_arbitrary_sample_rate,
                           None,
                           """
                           Gets or sets TrueArb sample rate.

                           Supported only in TrueArb arbitrary mode, use outputs[].arbitrary.arb_mode to set.
                           """)

        self._add_property('outputs[].arbitrary.arb_mode',
                           self._get_output_arbitrary_arb_mode,
                           self._set_output_arbitrary_arb_mode,
                           None,
                           """
                           Selects between 'TrueArb' and 'DDS' modes. Note that a direct sample rate selection
                           is only supported in the former.
                           """)

        self._init_outputs()

    def _init_outputs(self):
        try:
            super(siglentSDG2000X, self)._init_outputs()
        except AttributeError:
            pass

        self._output_arbitrary_arb_mode = list()
        self._output_arbitrary_sample_rate = list()

        for i in range(self._output_count):
            self._output_arbitrary_arb_mode.append('DDS')
            self._output_arbitrary_sample_rate.append(0)

    # region ARB waveform store management

    def _get_user_arb_store_names(self):
        """ Returns the current list of arbitrary waveform """

        if not self._driver_operation_simulate:
            raw = self._ask("STL? USER")
            names = raw.split(',')
            if names[0] != 'STL WVNM':
                raise ivi.UnexpectedResponseException()

            self._arb_store_names = names[1:]
        return self._arb_store_names

    # endregion

    # region Sample rate selection

    def _raise_if_bad_sample_rate(self, srate):
        if srate <= 0 or srate > self._arbitrary_sample_rate_max:
            raise ivi.InvalidOptionValueException('Sample rate exceeds supported TrueArb range')

    def _get_arbitrary_sample_rate(self):
        srates = [self._get_output_arbitrary_sample_rate(i) for i in range(self._output_count)]
        if not all(srate == srates[0] for srate in srates):
            raise ivi.OperationNotSupportedException(
                'Sample rates differ between channels: use a per-channel frequency info')

        return srates[0]

    def _set_arbitrary_sample_rate(self, value):
        self._raise_if_bad_sample_rate(value)
        for i in range(self._output_count):
            self._set_output_arbitrary_arb_mode(i, value)

    def _get_output_arbitrary_sample_rate(self, index):
        return self._get_scpi_option_cached('SRATE', option='VALUE',
                                            channel=index,
                                            cast_cache=lambda x: super(siglentSDG2000X)._strip_units(x))

    def _set_output_arbitrary_sample_rate(self, channel, value):
        self._raise_if_bad_sample_rate(value)

        if self._get_output_arbitrary_arb_mode(channel) != 'TrueArb':
            warn('Sample rate selection is only supported in TrueArb mode. Switching to TrueArb. \n' +
                 'To stay in DDS mode set frequency instead')
            self._set_output_arbitrary_arb_mode(channel, 'TrueArb')

        self._set_scpi_option_cached(value, 'SRATE', option='VALUE', channel=channel)

        index = ivi.get_index(self._output_name, channel)
        self._set_cache_valid(valid=False, tag='_output_arbitrary_waveform_frequency', index=index)
        self._set_cache_valid(valid=False, tag='_arbitrary_sample_rate', index=index)

    def _get_output_arbitrary_arb_mode(self, index):
        return self._get_scpi_option_cached('SRATE', option='MODE',
                                            channel=index,
                                            cast_cache=lambda am: 'DDS' if am == 'DDS' else 'TrueArb')

    def _set_output_arbitrary_arb_mode(self, index, value):
        if value not in ArbitraryModes:
            raise ivi.InvalidOptionValueException('Unknown mode')

        self._set_scpi_option_cached(value, 'SRATE', option='MODE',
                                     channel=index,
                                     cast_option=lambda am: 'DDS' if am == 'DDS' else 'TARB')

        self._set_cache_valid(valid=False, tag='_output_arbitrary_waveform_frequency', index=index)
        self._set_cache_valid(valid=False, tag='_output_arbitrary_sample_rate', index=index)
        self._set_cache_valid(valid=False, tag='_arbitrary_sample_rate', index=index)

    # endregion

    # region Arbirtary waveform catalog management

    def _arbitrary_waveform_clear(self, handle):
        # if handle in self._arb_store_names:
        #    self._arb_store_names.remove(handle)

        # TODO: Siglent's current programming manual is not providing any way to remove a waveform by name!
        pass

    def _arbitrary_waveform_create(self, data):
        arb_handles = self._get_user_arb_store_names()

        # find a free handle
        new_handle = ''
        for i in itertools.count():
            new_handle = 'pivi'+str(i)
            if new_handle not in arb_handles:
                break

        length, data_encoded = super(siglentSDG2000X, siglentSDG2000X)._convert_waveform_data(data)
        data_encoded = bytes(data_encoded) # to binary string rather then list

        # C1: or C2: doesn't seem to matter for the common memory, but needs to be there for the command to be accepted
        cmd = bytes('C1:WVDT WVNM,{0},LENGTH,{1},WAVEDATA,'.format(new_handle, length), 'utf-8') + data_encoded + b'\n'
        self._write_raw(cmd)
        self._arb_store_names.append(new_handle)

        return new_handle

    def _arbitrary_clear_memory(self):
        arb_handles = self._get_user_arb_store_names()
        for handle in arb_handles:
            self._arbitrary_waveform_clear(handle)

    @abstractmethod
    def _get_output_arbitrary_waveform(self, index):
        return self._get_scpi_option_cached('ARWV', option='NAME',
                                            channel=index,
                                            cast_cache=lambda s: s[:-4] if s[-4:] == '.bin' else s)  # strip extension

    @abstractmethod
    def _set_output_arbitrary_waveform(self, index, value):
        if value not in self._get_user_arb_store_names():
            raise ivi.InvalidOptionValueException()

        self._set_scpi_option_cached(value, 'ARWV', option='NAME', channel=index)

    # endregion


    # region Burst TrueArb guard

    def _get_output_operation_mode(self, index):
        index = ivi.get_index(self._output_name, index)
        return self._output_operation_mode[index]

    def _set_output_operation_mode(self, index, value):
        index = ivi.get_index(self._output_name, index)
        if value not in fgen.OperationMode:
            raise ivi.ValueNotSupportedException()

        self._output_operation_mode[index] = value

    # endregion
