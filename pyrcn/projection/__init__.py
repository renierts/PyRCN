"""
The :mod:`pyrcn.projection` module implements different kinds of linear and nonlinear projections.
"""

# See https://github.com/TUD-STKS/PyRCN and for documentation.

from pyrcn.projection._value_projection import MatrixToValueProjection


__all__ = ['MatrixToValueProjection']
