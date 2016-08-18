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


# TODO: f-counter, AM/FM and other modulations, harmonics, sync modes, waveform combining
class siglentSDG2000X(siglentFgenBase):
    """ Siglent SDG2000X function/arbitrary waveform generator driver """
    #TODO: srate, truearb/dds mode switches

    def __init__(self, *args, **kwargs):
        self.__dict__.setdefault('_instrument_id', '')

        self._output_count = 2
        # TODO: set all this stuff when updating the usages
        self._arbitrary_sample_rate = 0
        self._arbitrary_waveform_number_waveforms_max = 0
        self._arbitrary_waveform_size_max = 256 * 1024
        self._arbitrary_waveform_size_min = 64
        self._arbitrary_waveform_quantum = 8

        super(siglentSDG2000X, self).__init__(*args, **kwargs)

        self._catalog_names = list()

        self._arbitrary_waveform_n = 0

        self._identity_description = "Siglent function/arbitrary waveform generator driver"
        self._identity_instrument_model = "SDG2000X"
        self._identity_specification_major_version = 5
        self._identity_specification_minor_version = 0
        self._identity_supported_instrument_models = ['SDG2042X', 'SDG2082X', 'SDG2122X']

        self._init_outputs()

        self._add_property('arbitrary.sample_rate',
                           self._get_arbitrary_sample_rate,
                           self._set_arbitrary_sample_rate,
                           None,
                           """
                           Specifies the sample rate of the arbitrary waveforms the function
                           generator produces. The units are samples per second.
                           """)