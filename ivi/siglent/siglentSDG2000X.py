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

        # TODO: set all this stuff when updating the usages
        self._arbitrary_sample_rate_max = 75000000
        self._arbitrary_waveform_number_waveforms_max = 0
        self._arbitrary_waveform_size_max = 256 * 1024
        self._arbitrary_waveform_size_min = 64
        self._arbitrary_waveform_quantum = 8
        self._arbitrary_waveform_n = 0

        self._arb_store_names = list()
        self._identity_supported_instrument_models = ['SDG2042X', 'SDG2082X', 'SDG2122X']

        self._init_outputs()

        self._add_property('outputs[].arbitrary.sample_rate',
                           self._get_output_arbitrary_sample_rate,
                           self._set_output_arbitrary_sample_rate,
                           None,
                           """
                           Supported only in TrueArb arbitrary mode, use arbitrary.arb_mode to set.
                           Gets or sets TrueArb sample rate.
                           """)

        self._add_property('outputs[].arbitrary.arb_mode',
                           self._get_output_arbitrary_arb_mode,
                           self._set_output_arbitrary_arb_mode,
                           None,
                           """
                           Selects between 'TrueArb' and 'DDS' modes. Note that a direct sample rate selection
                           is only supported in the former.
                           """)

# region ARB waveform store management

    def _get_arb_store_names(self):
        """ Returns the current list of arbitrary waveform """

        if not self._driver_operation_simulate:
            raw = self._ask("STM? USER").lower()
            raw = raw.split(',', 1)[1]

            l = raw.split(',')
            l = [s.strip('"') for s in l]
            self._catalog = [l[i:i + 3] for i in range(0, len(l), 3)]
            self._catalog_names = [l[0] for l in self._catalog]

# endregion


    def _get_arbitrary_sample_rate(self):
        raise ivi.OperationNotSupportedException('Sample rate must be set on a per-channel basis') # todo

    def _set_arbitrary_sample_rate(self, value):
        raise ivi.OperationNotSupportedException('Sample rate must be set on a per-channel basis')

    def _get_output_arbitrary_sample_rate(self, index):
        pass #TODO

    def _set_output_arbitrary_sample_rate(self, index, value):
        pass #TODO

    def _get_output_arbitrary_arb_mode(self, index):
        pass #TODO

    def _set_output_arbitrary_arb_mode(self, index, value):
        pass #TODO