﻿"""The :mod:`input_to_node` contains InputToNode classes and derivatives."""

# Authors: Peter Steiner <peter.steiner@tu-dresden.de>
# License: BSD 3 clause

from __future__ import annotations

import sys
from scipy.sparse import csr_matrix
from scipy.sparse import issparse
import numpy as np
from sklearn.utils.validation import _deprecate_positional_args
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils import check_random_state, deprecated
from sklearn.utils.extmath import safe_sparse_dot
from sklearn.exceptions import NotFittedError
from sklearn.preprocessing import StandardScaler

from ...base import (ACTIVATIONS, ACTIVATIONS_INVERSE,
                     ACTIVATIONS_INVERSE_BOUNDS, _uniform_random_bias,
                     _uniform_random_input_weights)

from typing import Union, Literal, Optional


class InputToNode(BaseEstimator, TransformerMixin):
    """
    InputToNode class for reservoir computing modules.

    Parameters
    ----------
    hidden_layer_size : int, default=500
        Sets the number of nodes in hidden layer.
        Equals number of output features.
    sparsity : float, default = 1.
        Quotient of input weights per node (k_in)
        and number of input features (n_features)
    input_activation : Literal['tanh', 'identity', 'logistic', 'relu',
    'bounded_relu'], default = 'tanh'
        This element represents the activation function in the hidden layer.
            - 'identity', no-op activation, useful to implement linear
            bottleneck, returns f(x) = x
            - 'logistic', the logistic sigmoid function,
            returns f(x) = 1/(1+exp(-x)).
            - 'tanh', the hyperbolic tan function, returns f(x) = tanh(x).
            - 'relu', the rectified linear unit function,
            returns f(x) = max(0, x)
            - 'bounded_relu', the bounded rectified linear unit function,
            returns f(x) = min(max(x, 0),1)
    input_scaling :  float, default = 1.
        Scales the input weight matrix.
    input_shift :  float, default = 0.
        Shifts the input weight matrix.
    bias_scaling : float, default = 1.
        Scales the input bias of the activation.
    bias_shift : float, default = 0.
        Shifts the input bias of the activation.
    k_in : Union[int, np.integer, None], default = None.
        input weights per node. By default, it is None. If set, it overrides
        sparsity.
    random_state : Union[int, np.random.RandomState, None], default = 42
        Determines random number generation for centroid initialization.
        Use an int to make the randomness deterministic.
    predefined_input_weights : Optional[np.ndarray], default = None
        A set of predefined input weights.
    predefined_bias_weights : Optional[np.ndarray], default = None
        A set of predefined bias weights.
    """

    @_deprecate_positional_args
    def __init__(self, *,
                 hidden_layer_size: int = 500,
                 sparsity: float = 1.,
                 input_activation: Literal['tanh', 'identity', 'logistic',
                                           'relu', 'bounded_relu'] = 'tanh',
                 input_scaling: float = 1., input_shift: float = 0.,
                 bias_scaling: float = 1., bias_shift: float = 0.,
                 k_in: Union[int, None] = None,
                 random_state: Union[int, np.random.RandomState, None] = 42,
                 predefined_input_weights: Optional[np.ndarray] = None,
                 predefined_bias_weights: Optional[np.ndarray] = None) -> None:
        """Construct the InputToNode."""
        self.hidden_layer_size = hidden_layer_size
        self.sparsity = sparsity
        self.input_activation = input_activation
        self.input_scaling = input_scaling
        self.input_shift = input_shift
        self.bias_scaling = bias_scaling
        self.bias_shift = bias_shift
        self.random_state = random_state
        self.k_in = k_in

        self._input_weights: np.ndarray = np.ndarray([])
        self._bias_weights: np.ndarray = np.ndarray([])
        self._hidden_layer_state: np.ndarray = np.ndarray([])
        self.predefined_input_weights = predefined_input_weights
        self.predefined_bias_weights = predefined_bias_weights

    def fit(self, X: np.ndarray, y: None = None) -> InputToNode:
        """
        Fit the InputToNode. Initialize input weights and bias.

        Parameters
        ----------
        X : ndarray of shape (n_samples, n_features)
            The input data.
        y : None
            Not used, present here for API consistency by convention.

        Returns
        -------
        self : returns a fitted InputToNode.
        """
        self._validate_hyperparameters()
        self._validate_data(X, y)
        self._check_n_features(X, reset=True)
        if self.k_in is not None:
            self.sparsity = float(self.k_in) / float(X.shape[1])
        fan_in = int(np.rint(self.hidden_layer_size * self.sparsity))
        if self.predefined_input_weights is not None:
            assert self.predefined_input_weights.shape == (
                self.n_features_in_, self.hidden_layer_size)
            self._input_weights = self.predefined_input_weights
        else:
            self._input_weights = _uniform_random_input_weights(
                n_features_in=self.n_features_in_,
                hidden_layer_size=int(self.hidden_layer_size), fan_in=fan_in,
                random_state=self._random_state)
        if self.predefined_bias_weights is not None:
            assert self.predefined_bias_weights.shape == (
                self.hidden_layer_size, 1)
            self._bias_weights = self.predefined_bias_weights
        else:
            self._bias_weights = _uniform_random_bias(
                hidden_layer_size=int(self.hidden_layer_size),
                random_state=self._random_state)
        return self

    def transform(self, X: np.ndarray, y: None = None) -> np.ndarray:
        """
        Transform the input matrix X.

        Parameters
        ----------
        X : ndarray of shape (n_samples, n_features)
            The input data.
        y : None
            Not used, present here for API consistency by convention.

        Returns
        -------
        X_new : ndarray of size (n_samples, hidden_layer_size)
            X transformed in the new space.
        """
        if self._input_weights.shape == () or self._bias_weights.shape == ():
            raise NotFittedError(self)
        _hidden_layer_state = InputToNode._node_inputs(
            X, self._input_weights, self.input_scaling, self.input_shift,
            self._bias_weights, self.bias_scaling, self.bias_shift)
        ACTIVATIONS[self.input_activation](_hidden_layer_state)
        return _hidden_layer_state

    @staticmethod
    def _node_inputs(X: np.ndarray,
                     input_weights: Union[np.ndarray, csr_matrix],
                     input_scaling: float, input_shift: float,
                     bias: np.ndarray, bias_scaling: float, bias_shift: float)\
            -> np.ndarray:
        """
        Scale the node inputs with input_scaling, shift them with input_shift,
        multiply the scaled and shifted node inputs with theinput_weights and
        add a bias.

        Parameters
        ----------
        X : ndarray of shape (n_samples, n_features)
            The input data.
        input_weights : Union[np.ndarray, scipy.sparse.csr_matrix]
            The input weights.
        input_scaling : float
            The scaling factor for the node inputs.
        input_shift : float
            The shifting factor for the node inputs
        bias : ndarray of size (hidden_layer_size)
            The bias weight for each node.
        bias_scaling : float
            The scaling factor for the bias weights.
        bias_shift : float
            The shifting factor for the bias weights.

        Returns
        -------
        X_new : ndarray of size (n_samples, hidden_layer_size)
            The shifted and scaled inputs.
        """
        return (safe_sparse_dot(X, input_weights) * input_scaling + input_shift
                + np.ones(shape=(X.shape[0], 1)) * bias.T * bias_scaling
                + bias_shift)

    def _validate_hyperparameters(self) -> None:
        """Validate the hyperparameters."""
        self._random_state = check_random_state(self.random_state)

        if self.hidden_layer_size <= 0:
            raise ValueError("hidden_layer_size must be > 0, got {0}."
                             .format(self.hidden_layer_size))
        if self.sparsity <= 0. or self.sparsity > 1.:
            raise ValueError("sparsity must be between 0. and 1., got {0}."
                             .format(self.sparsity))
        if self.input_activation not in ACTIVATIONS:
            raise ValueError("The activation_function '{0}' is not supported."
                             "Supported activations are {1}."
                             .format(self.input_activation, ACTIVATIONS))
        if self.input_scaling <= 0.:
            raise ValueError("input_scaling must be > 0, got {0}."
                             .format(self.input_scaling))
        if self.bias_scaling < 0:
            raise ValueError("bias must be > 0, got {0}."
                             .format(self.bias_scaling))
        if self.k_in is not None and (self.k_in <= 0
                                      or self.k_in >= self.hidden_layer_size):
            raise ValueError("k_in must be > 0 and < self.hidden_layer_size"
                             " {0}, got {1}."
                             .format(self.hidden_layer_size, self.k_in))

    def __sizeof__(self) -> int:
        """
        Return the size of the object in bytes.

        Returns
        -------
        size : int
        Object memory in bytes.
        """
        if issparse(self._input_weights):
            return object.__sizeof__(self) + self._bias_weights.nbytes + \
                np.asarray(self._input_weights).nbytes + \
                sys.getsizeof(self._random_state)
        else:
            return object.__sizeof__(self) + self._bias_weights.nbytes + \
                self._input_weights.nbytes + sys.getsizeof(self._random_state)

    @property
    def input_weights(self) -> Union[np.ndarray, csr_matrix]:
        """
        Return the input weights.

        Returns
        -------
        input_weights : Union[np.ndarray, scipy.sparse.csr_matrix]
            of size (n_features, hidden_layer_size)
        """
        return self._input_weights

    @property
    def bias_weights(self) -> np.ndarray:
        """
        Return the bias.

        Returns
        -------
        bias : ndarray of size (hidden_layer_size)
        """
        return self._bias_weights


@deprecated("Predefined weights can now directly be passed to InputToNode.")
class PredefinedWeightsInputToNode(InputToNode):
    """
    PredefinedWeightsInputToNode class for reservoir computing modules.

    Parameters
    ----------
    predefined_input_weights : np.ndarray,shape=(n_features,
    hidden_layer_size)
        A set of predefined input weights.
    input_activation : Literal['tanh', 'identity', 'logistic', 'relu',
    'bounded_relu'], default = 'tanh'
        This element represents the activation function in the hidden layer.
            - 'identity', no-op activation, useful to implement linear
            bottleneck, returns f(x) = x
            - 'logistic', the logistic sigmoid function,
            returns f(x) = 1/(1+exp(-x)).
            - 'tanh', the hyperbolic tan function, returns f(x) = tanh(x).
            - 'relu', the rectified linear unit function,
            returns f(x) = max(0, x)
            - 'bounded_relu', the bounded rectified linear unit function,
            returns f(x) = min(max(x, 0),1)
    input_scaling :  float, default = 1.
        Scales the input weight matrix.
    input_shift :  float, default = 0.
        Shifts the input weight matrix.
    bias_scaling : float, default = 1.
        Scales the input bias of the activation.
    bias_shift : float, default = 0.
        Shifts the input bias of the activation.
    random_state : Union[int, np.random.RandomState, None], default = 42
    """

    @_deprecate_positional_args
    def __init__(self,
                 predefined_input_weights: np.ndarray, *,
                 input_activation: Literal['tanh', 'identity', 'logistic',
                                           'relu', 'bounded_relu'] = 'tanh',
                 input_scaling: float = 1., input_shift: float = 0.,
                 predefined_bias_weights: Optional[np.ndarray] = None,
                 bias_scaling: float = 0., bias_shift: float = 0.,
                 random_state: Union[int, np.random.RandomState, None] = 42)\
            -> None:
        """Construct the PredefinedWeightsInputToNode."""
        if predefined_input_weights.ndim != 2:
            raise ValueError('predefined_input_weights has not the expected'
                             'ndim 2, given {0}.'
                             .format(predefined_input_weights.shape))
        super().__init__(hidden_layer_size=predefined_input_weights.shape[1],
                         input_activation=input_activation,
                         input_scaling=input_scaling, input_shift=input_shift,
                         bias_scaling=bias_scaling, bias_shift=bias_shift,
                         random_state=random_state,
                         predefined_input_weights=predefined_input_weights,
                         predefined_bias_weights=predefined_bias_weights)

    def fit(self, X: np.ndarray, y: None = None) -> InputToNode:
        """
        Fit the PredefinedWeightsInputToNode.
        Set input weights and initialize bias.

        Parameters
        ----------
        X : ndarray of shape (n_samples, n_features)
        y : ignored

        Returns
        -------
        self : returns a trained PredefinedWeightsInputToNode.
        """
        super().fit(X, y)
        return self


"""
class NonlinearVectorAutoregression(InputToNode):
    #
    # Non-linear vector autoregression (NVAR) class

    #

    @_deprecate_positional_args
    def __init__(self, *,
                 delay: int = 2, order: int = 2, stride: int = 1) -> None:
        super().__init__()
        self.delay = delay
        self.order = order
        self.stride = stride
        self._linear_dimension = 0
        self._non_linear_dimension = 0

    def fit(self, X: np.ndarray, y: None = None) -> InputToNode:
        self._validate_hyperparameters()
        self._validate_data(X, y)
        n_samples, n_features = X.shape
        self._linear_dimension = self.delay * n_features
        self._non_linear_dimension = comb(
            self._linear_dimension + self.order - 1, self.order)
        self.hidden_layer_size = self._linear_dimension + \
                                 self._non_linear_dimension
"""


class BatchIntrinsicPlasticity(InputToNode):
    """
    BatchIntrinsicPlasticity class for reservoir computing modules.

    Parameters
    ----------
    distribution : Literal['exponential', 'uniform', 'normal'],
    default = 'normal'
        This element represents the desired target distribution.
    algorithm : Literal['neumann', 'dresden'], default = 'dresden'
        This element represents the transformation algorithm to be used.
    input_activation : Literal['tanh', 'identity', 'logistic', 'relu',
    'bounded_relu'], default = 'tanh'
        This element represents the activation function in the hidden layer.
            - 'identity', no-op activation, useful to implement linear
            bottleneck, returns f(x) = x
            - 'logistic', the logistic sigmoid function,
            returns f(x) = 1/(1+exp(-x)).
            - 'tanh', the hyperbolic tan function, returns f(x) = tanh(x).
            - 'relu', the rectified linear unit function,
            returns f(x) = max(0, x)
            - 'bounded_relu', the bounded rectified linear unit function,
            returns f(x) = min(max(x, 0),1)
    hidden_layer_size : int, default=500
        Sets the number of nodes in hidden layer.
        Equals number of output features.
    sparsity : float, default = 1.
        Quotient of input weights per node (k_in)
        and number of input features (n_features)
    random_state : Union[int, np.random.RandomState, None], default = 42
    """

    @_deprecate_positional_args
    def __init__(self, *,
                 distribution: Literal['exponential', 'uniform',
                                       'normal'] = 'normal',
                 algorithm:  Literal['neumann', 'dresden'] = 'dresden',
                 input_activation: Literal['tanh', 'identity', 'logistic',
                                           'relu', 'bounded_relu'] = 'tanh',
                 hidden_layer_size: int = 500, sparsity: float = 1.,
                 random_state: Union[int, np.random.RandomState, None] = 42):
        """Construct the BatchIntrinsicPlasticity InputToNode."""
        super().__init__(input_activation=input_activation,
                         hidden_layer_size=hidden_layer_size,
                         sparsity=sparsity, random_state=random_state)
        self.distribution = distribution
        self.algorithm = algorithm
        self._scaler = StandardScaler()
        self._m = 1
        self._c = 0

    IN_DISTRIBUTION_PARAMS = {'exponential': (-.5, -.5),
                              'uniform': (.7, .0),
                              'normal': (.3, .0)}

    OUT_DISTRIBUTION = {
        'exponential': lambda size: np.random.poisson(lam=1., size=size),
        'uniform': lambda size: np.random.uniform(low=-1., high=1., size=size),
        'normal': lambda size: np.random.normal(loc=0., scale=1., size=size)
        }

    def fit(self, X: np.ndarray, y: None = None) -> InputToNode:
        """
        Fit the BatchIntrinsicPlasticity.

        Parameters
        ----------
        X : ndarray of shape (n_samples, n_features)
        y : ignored

        Returns
        -------
        self : returns a trained BatchIntrinsicPlasticity.
        """
        self._validate_hyperparameters()

        if self.algorithm == 'neumann':
            self._fit_neumann(X, y=None)

        if self.algorithm == 'dresden':
            self._fit_dresden(X, y=None)
        return self

    def transform(self, X: np.ndarray, y: None = None) -> np.ndarray:
        """
        Transform the input matrix X.

        Parameters
        ----------
        X : ndarray of shape (n_samples, n_features)
            The input data.
        y : None
            Not used, present here for API consistency by convention.

        Returns
        -------
        Y: ndarray of size (n_samples, hidden_layer_size)
        """
        if self.algorithm == 'neumann':
            return super().transform(X)

        if self.algorithm == 'dresden':
            s = BatchIntrinsicPlasticity._node_inputs(
                X, self._input_weights, self.input_scaling, self.input_shift,
                self._bias_weights, self.bias_scaling, self.bias_shift)
            np.add(np.multiply(
                self._scaler.transform(s), self._m), self._c, out=s)
            ACTIVATIONS[self.input_activation](s)
            return s

    def _fit_neumann(self, X: np.ndarray, y: None = None) -> InputToNode:
        """
        Fit according to the Neumann paper.

        Parameters
        ----------
        X : ndarray of size (n_samples, n_features)

        Returns
        -------
        self : returns a trained BatchIntrinsicPlasticity.
        """
        super().fit(X, y=y)

        s = np.sort(BatchIntrinsicPlasticity._node_inputs(
            X, self._input_weights, self.input_scaling, self.input_shift,
            self._bias_weights, self.bias_scaling, self.bias_shift), axis=0)

        phi = np.transpose(np.stack((s, np.ones(s.shape)), axis=2),
                           axes=(1, 0, 2))

        if callable(BatchIntrinsicPlasticity.OUT_DISTRIBUTION[
                        self.distribution]):
            t = BatchIntrinsicPlasticity.OUT_DISTRIBUTION[self.distribution](
                size=X.shape[0])
            t_min, t_max = np.min(t), np.max(t)

            if (self.distribution in {'uniform'} and self.input_activation
                    in {'tanh', 'logistic'}):
                bound_low = ACTIVATIONS_INVERSE_BOUNDS[
                                self.input_activation][0] * .5
                bound_high = ACTIVATIONS_INVERSE_BOUNDS[
                                 self.input_activation][1] * .5
            else:
                bound_low = ACTIVATIONS_INVERSE_BOUNDS[
                    self.input_activation][0]
                bound_high = ACTIVATIONS_INVERSE_BOUNDS[
                    self.input_activation][1]

            if bound_low == np.inf:
                bound_low = t_min

            if bound_high == np.inf:
                bound_high = t_max

            t = (t - t_min)*(bound_high - bound_low)\
                / (t_max - t_min) + bound_low

            t.sort()
            ACTIVATIONS_INVERSE[self.input_activation](t)
        else:
            raise ValueError('Not a valid activation inverse, got {0}'
                             .format(self.distribution))

        v = safe_sparse_dot(np.linalg.pinv(phi), t)

        np.multiply(self._input_weights, v[:, 0], out=self._input_weights)
        self._bias_weights += v[:, 1]
        return self

    def _fit_dresden(self, X: np.ndarray, y: None = None) -> InputToNode:
        """
        Fit with a slightly different method.

        Parameters
        ----------
        X : ndarray of size (n_samples, n_features)

        Returns
        -------
        self : returns a trained BatchIntrinsicPlasticity.
        """
        if self.input_activation != 'tanh':
            raise ValueError('This algorithm is working with tanh-activation'
                             'only, got {0}'.format(self.input_activation))
        super().fit(X, y=y)

        s = BatchIntrinsicPlasticity._node_inputs(
            X, self._input_weights, self.input_scaling, self.input_shift,
            self._bias_weights, self.bias_scaling, self.bias_shift)
        self._scaler.fit(s)

        if self.distribution:
            self._m, self._c = BatchIntrinsicPlasticity.IN_DISTRIBUTION_PARAMS[
                self.distribution]
        return self

    def _validate_hyperparameters(self) -> None:
        super()._validate_hyperparameters()

        if self.algorithm not in {'neumann', 'dresden'}:
            raise ValueError('The selected algorithm is unknown, got {0}'
                             .format(self.algorithm))
        if self.distribution not in {'exponential', 'uniform', 'normal'}:
            raise ValueError('The selected distribution is unknown, got {0}'
                             .format(self.distribution))
