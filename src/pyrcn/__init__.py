"""The :mod:`pyrcn` module includes various reservoir computing algorithms."""

# Authors: Peter Steiner <peter.steiner@tu-dresden.de>,
# License: BSD 3 clause
from ._version import __version__

from . import (base, echo_state_network, extreme_learning_machine,
               linear_model, model_selection, nn, postprocessing,
               preprocessing, projection, util)


__all__ = ('__version__',
           'base',
           'echo_state_network',
           'extreme_learning_machine',
           'linear_model',
           'model_selection',
           'nn',
           'postprocessing',
           'preprocessing',
           'projection',
           'util')
