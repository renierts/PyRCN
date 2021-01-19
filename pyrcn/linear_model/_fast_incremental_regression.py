"""
Incremental regression
"""

# Authors: Peter Steiner <peter.steiner@tu-dresden.de>, Azarakhsh Jalalvand <azarakhsh.jalalvand@ugent.be>
# License: BSD 3 clause

import numpy as np
import scipy
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.utils.extmath import safe_sparse_dot
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import NotFittedError


class FastIncrementalRegression(BaseEstimator, RegressorMixin):
    """Fast Linear regression.
    This linear regression algorithm is able to perform a linear regression
    with the L2 regularization and iterative fit. [1]_
    .. [1] https://ieeexplore.ieee.org/document/4012031
    References
    ----------
    N. Liang, G. Huang, P. Saratchandran and N. Sundararajan,
    "A Fast and Accurate Online Sequential Learning Algorithm for Feedforward Networks,"
    in IEEE Transactions on Neural Networks, vol. 17, no. 6, pp. 1411-1423, Nov. 2006, doi: 10.1109/TNN.2006.880583.
    Parameters
    ----------
    alpha : float, default=1.0
        L2 regularization parameter
    fit_intercept : bool, default=True
        Fits a constant offset if True. Use this if input values are not average free.
    normalize : bool, default=False
        Performs a preprocessing normalization if True.
    Attributes
    ----------
    coef_ : array, shape (n_features,) or (n_targets, n_features)
        Weight vector(s).
    intercept_ : float | array, shape = (n_targets,)
        Independent term in decision function. Set to 0.0 if
        ``fit_intercept = False``.
    """
    def __init__(self, alpha=1.0, fit_intercept=True, normalize=False):
        self.alpha = alpha
        self.fit_intercept = fit_intercept
        self.normalize = normalize
        self.scaler = StandardScaler(copy=False)

        self._xTx = None
        self._xTy = None
        self._output_weights = None

    def partial_fit(self, X, y, partial_normalize=True, validate=True, update_output_weights=True, finalize=False):
        """Fits the regressor partially.
        Parameters
        ----------
        X : {ndarray, sparse matrix} of shape (n_samples, n_features)
        y : {ndarray, sparse matrix} of shape (n_samples,) or (n_samples, n_targets)
        partial_normalize : bool, default=True
            Partial fits the normalization transformer on this sample if True.
        validate: bool, default=True
            Validate input data if True.
        update_output_weights : bool, default=True
            Only update the output weights if required. This saves time
        finalize : bool, default=False
            Remove correlation matrices after the model has been fit with all data.
        Returns
        -------
        self
        """
        if validate:
            self._validate_data(X, y, multi_output=True)

        X_preprocessed = self._preprocessing(X, partial_normalize=partial_normalize)

        if self._xTx is None:
            self._xTx = safe_sparse_dot(X_preprocessed.T, X_preprocessed)
        else:
            self._xTx += safe_sparse_dot(X_preprocessed.T, X_preprocessed)

        if self._xTy is None:
            self._xTy = safe_sparse_dot(X_preprocessed.T, y)
        else:
            self._xTy += safe_sparse_dot(X_preprocessed.T, y)

        if update_output_weights and finalize:
            inv_xTx = np.linalg.inv(self._xTx + self.alpha * self._n_samples * np.eye(self._xTx.shape[0]))
            self._output_weights = safe_sparse_dot(inv_xTx, self._xTy)
            self._xTx = None
            self._xTy = None
        elif update_output_weights:
            inv_xTx = np.linalg.inv(self._xTx + self.alpha * self._n_samples * np.eye(self._xTx.shape[0]))
            self._output_weights = safe_sparse_dot(inv_xTx, self._xTy)

        return self

    def fit(self, X, y):
        """Fits the regressor.
        Parameters
        ----------
        X : {ndarray, sparse matrix} of shape (n_samples, n_features)
        y : {ndarray, sparse matrix} of shape (n_samples,) or (n_samples, n_targets)
        Returns
        -------
        self
        """
        self.partial_fit(X, y, partial_normalize=False, validate=True, update_output_weights=True, finalize=True)
        return self

    def predict(self, X):
        """Predicts output y according to input X.
        Parameters
        ----------
        X : {ndarray, sparse matrix} of shape (n_samples, n_features)
        Returns
        -------
        Y : ndarray of shape (n_samples,) or (n_samples, n_targets)
        """
        if self._output_weights is None:
            raise NotFittedError(self)

        return safe_sparse_dot(self._preprocessing(X, partial_normalize=False), self._output_weights)

    def _preprocessing(self, X, partial_normalize=True):
        """Applies preprocessing on the input data X.
        Parameters
        ----------
        X : {ndarray, sparse matrix} of shape (n_samples, n_features)
        partial_normalize : bool, default=True
            Partial fits the normalization transformer on this sample if True.
        Returns
        -------
        X_preprocessed : {ndarray, sparse matrix} of shape (n_samples, n_features) or (n_samples, n_features+1)
        """
        X_preprocessed = X

        if self.fit_intercept:
            X_preprocessed = np.hstack((X_preprocessed, np.ones(shape=(X.shape[0], 1))))

        if self.normalize:
            if partial_normalize:
                self.scaler.partial_fit(X_preprocessed).transform(X_preprocessed)
            else:
                self.scaler.fit_transform(X_preprocessed)

        return X_preprocessed

    @property
    def coef_(self):
        """Returns the output weights without intercept. Compatibility to sklearn.linear_model.Ridge.
        Returns
        -------
        coef_ : array, shape (n_features,) or (n_targets, n_features)
            Weight vector(s).
        """
        if self._output_weights is not None:
            if self.fit_intercept:
                if self._output_weights.ndim == 2:
                    return np.transpose(self._output_weights)[:, :-1]
                else:
                    return self._output_weights[:-1]
            else:
                return np.transpose(self._output_weights)

    @property
    def intercept_(self):
        """Returns the intercept of output output weights. Compatibility to sklearn.linear_model.Ridge.
        Returns
        -------
        intercept_ : float | array, shape = (n_targets,)
            Independent term in decision function.
        """
        if self._output_weights is not None and self.fit_intercept:
            return np.transpose(self._output_weights)[:, -1]