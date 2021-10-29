import sys
if sys.version_info >= (3, 8):
    from typing import Union, Literal, Callable, Dict
else:
    from typing_extensions import Literal
    from typing import Union, Callable, Dict

import numpy as np
from sklearn.preprocessing import FunctionTransformer


class FeatureExtractor(FunctionTransformer):
    """
    Constructs a transformer from an arbitrary callable.

    A FunctionTransformer forwards its X (and optionally y) arguments to a user-defined function or function object and returns the result of this function. 
    This is useful for stateless transformations such as taking the log of frequencies, doing custom scaling, etc.

    Compared to sklearn.preprocessing.FunctionTransformer, it is possible to pass a filename as X and process the underlying file.

    Note: If a lambda is used as the function, then the resulting transformer will not be pickleable.

    Parameters
    ----------
    func : Union[Callable, None]
        The callable to use for the transformation. 
        This will be passed the same arguments as transform, with args and kwargs forwarded. 
        If func is None, then func will be the identity function.
    kw_args : Union[Dict, None], default=None.
        Dictionary of additional keyword arguments to pass to func.

    """
    def __init__(self, func: Union[Callable, None], kw_args: Union[Dict, None] = None):
        super().__init__(func=func, inverse_func=None, validate=False, accept_sparse=False, check_inverse=False, kw_args=kw_args, inv_kw_args=None)

    def fit(self, X: Union[str, np.ndarray], y: Union[np.ndarray, None], 
            **fit_params: Union[Dict, None]) -> FunctionTransformer:
        """
        Fit transformer by checking X.

        Parameters
        ----------
        X : Union[str, np.ndarray]
            Input that can either be a feature matrix or a filename.
        y : Union[np.ndarray, None], default=None
            Target values (None for unsupervised transformations).

        fit_params : Union[Dict, None]
            Additional fit parameters.
        """
        return super().fit(X=X, y=y, **fit_params)

    def transform(self, X: Union[str, np.ndarray]) -> np.ndarray:
        """
        Transform X using the forward function.

        Parameters
        ----------
        X : Union[str, np.ndarray]
            Input that can either be a feature matrix or a filename.

        Returns
        -------
        X_out : array-like, shape (n_samples, n_features)
            Transformed input.

        """
        X_out = self._transform(X=X, func=self.func, kw_args=self.kw_args)
        if type(X_out) is tuple:
            X_out = X_out[0]
        return X_out
