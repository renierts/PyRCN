import os
import glob
import numpy as np
from tqdm import tqdm
import time
import librosa

from joblib import dump, load

from sklearn.base import clone
from sklearn.preprocessing import StandardScaler
from sklearn.utils import shuffle
from sklearn.utils.fixes import loguniform
from scipy.stats import uniform
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.model_selection import train_test_split, ParameterGrid, GridSearchCV, RandomizedSearchCV, cross_validate
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import make_scorer, zero_one_loss
from pyrcn.metrics import mean_squared_error
from pyrcn.model_selection import SequentialSearchCV
from pyrcn.util import FeatureExtractor
from pyrcn.datasets import fetch_ptdb_tug_dataset
from pyrcn.echo_state_network import SeqToSeqESNRegressor
from pyrcn.base import InputToNode, PredefinedWeightsInputToNode, NodeToNode
import matplotlib.pyplot as plt


def create_feature_extraction_pipeline(sr=16000):
    audio_loading = Pipeline([("load_audio", FeatureExtractor(func=librosa.load, kw_args={"sr": sr, "mono": True})),
                              ("normalize", FeatureExtractor(func=librosa.util.normalize, kw_args={"norm": np.inf}))])
    
    feature_extractor = Pipeline([("mel_spectrogram", FeatureExtractor(func=librosa.feature.melspectrogram, 
                                                                       kw_args={"sr": sr, "n_fft": 1024, "hop_length": 160, 
                                                                                "window": 'hann', "center": False, 
                                                                                "power": 2.0, "n_mels": 80, "fmin": 40, 
                                                                                "fmax": 4000, "htk": True})),
                                            ("power_to_db", FeatureExtractor(func=librosa.power_to_db, kw_args={"ref": 1}))])

    feature_extraction_pipeline = Pipeline([("audio_loading", audio_loading),
                                            ("feature_extractor", feature_extractor)])
    return feature_extraction_pipeline


# Load and preprocess the dataset
feature_extraction_pipeline = create_feature_extraction_pipeline()

X_train, X_test, y_train, y_test = fetch_ptdb_tug_dataset(data_origin="Z:/Projekt-Pitch-Datenbank/SPEECH_DATA", 
                                                          data_home=None, preprocessor=feature_extraction_pipeline, 
                                                          force_preprocessing=False, augment=0)
X_train, y_train = shuffle(X_train, y_train, random_state=0)

scaler = StandardScaler().fit(np.concatenate(X_train))
for k, X in enumerate(X_train):
    X_train[k] = scaler.transform(X=X)
for k, X in enumerate(X_test):
    X_test[k] = scaler.transform(X=X)
# Define several error functions for $f_{0}$ extraction

def gpe(y_true, y_pred):
    """
    Gross pitch error:
    
    All frames that are considered voiced by both pitch tracker and ground truth, 
    for which the relative pitch error is higher than a certain threshold (\SI{20}{\percent}).
    
    """
    idx = np.nonzero(y_true*y_pred)[0]
    return np.sum(np.abs(y_true[idx] - y_pred[idx]) > 0.2 * y_true[idx]) / len(np.nonzero(y_true)[0])


def new_gpe(y_true, y_pred):
    """
    Gross pitch error:
    
    All frames that are considered voiced by both pitch tracker and ground truth, 
    for which the relative pitch error is higher than a certain threshold (\SI{20}{\percent}).
    
    """
    idx = np.nonzero(y_true*y_pred)[0]
    return np.sum(np.abs(1/y_true[idx] - 1/y_pred[idx]) > 1.5e-3) / len(np.nonzero(y_true)[0])


def vde(y_true, y_pred):
    """
    Voicing Decision Error:
    
    Proportion of frames for which an incorrect voiced/unvoiced decision is made.
    
    """
    return zero_one_loss(y_true, y_pred)


def fpe(y_true, y_pred):
    """
    Fine Pitch Error:
    
    Standard deviation of the distribution of relative error values (in cents) from the frames
    that do not have gross pitch errors
    """
    idx_voiced = np.nonzero(y_true * y_pred)[0]
    idx_correct = np.argwhere(np.abs(y_true - y_pred) <= 0.2 * y_true).ravel()
    idx = np.intersect1d(idx_voiced, idx_correct)
    if idx.size == 0:
        return 0
    else:
        return 100 * np.std(np.log2(y_pred[idx] / y_true[idx]))


def mu_fpe(y_true, y_pred):
    """
    Fine Pitch Error:
    
    Standard deviation of the distribution of relative error values (in cents) from the frames
    that do not have gross pitch errors
    """
    idx_voiced = np.nonzero(y_true * y_pred)[0]
    idx_correct = np.argwhere(np.abs(1/y_true - 1/y_pred) <= 1.5e-3).ravel()
    idx = np.intersect1d(idx_voiced, idx_correct)
    if idx.size == 0:
        return 0
    else:
        return np.mean(np.abs(y_pred[idx] - y_true[idx]))


def sigma_fpe(y_true, y_pred):
    """
    Fine Pitch Error:
    
    Standard deviation of the distribution of relative error values (in cents) from the frames
    that do not have gross pitch errors
    """
    idx_voiced = np.nonzero(y_true * y_pred)[0]
    idx_correct = np.argwhere(np.abs(1/y_true - 1/y_pred) <=1.5e-3).ravel()
    idx = np.intersect1d(idx_voiced, idx_correct)
    if idx.size == 0:
        return 0
    else:
        return np.std(np.abs(y_pred[idx] - y_true[idx]))


def ffe(y_true, y_pred):
    """
    $f_{0}$ Frame Error:
    
    Proportion of frames for which an error (either according to the GPE or the VDE criterion) is made.
    FFE can be seen as a single measure for assessing the overall performance of a pitch tracker.
    """
    idx_correct = np.argwhere(np.abs(y_true - y_pred) <= 0.2 * y_true).ravel()
    return 1 - len(idx_correct) / len(y_true)


def custom_scorer(y_true, y_pred):
    gross_pitch_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        gross_pitch_error[k] = gpe(y_true=y_t[:, 0]*y_t[:, 1], y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(gross_pitch_error)


def custom_scorer(y_true, y_pred):
    gross_pitch_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        gross_pitch_error[k] = gpe(y_true=y_t[:, 0]*y_t[:, 1], y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(gross_pitch_error)

gpe_scorer = make_scorer(custom_scorer, greater_is_better=False)



# Set up a ESN
# To develop an ESN model for f0 estimation, we need to tune several hyper-parameters, e.g., input_scaling, spectral_radius, bias_scaling and leaky integration.
# We follow the way proposed in the paper for multipitch tracking and for acoustic modeling of piano music to optimize hyper-parameters sequentially.
# We define the search spaces for each step together with the type of search (a grid search in this context).
# At last, we initialize a SeqToSeqESNRegressor with the desired output strategy and with the initially fixed parameters.

initially_fixed_params = {'hidden_layer_size': 500,
                          'k_in': 10,
                          'input_scaling': 0.4,
                          'input_activation': 'identity',
                          'bias_scaling': 0.0,
                          'spectral_radius': 0.0,
                          'leakage':1.0,
                          'k_rec': 10,
                          'reservoir_activation': 'tanh',
                          'bi_directional': False,
                          'wash_out': 0,
                          'continuation': False,
                          'alpha': 1e-3,
                          'random_state': 42}

step1_esn_params = {'input_scaling': uniform(loc=1e-2, scale=1),
                    'spectral_radius': uniform(loc=0, scale=2)}

step2_esn_params = {'leakage': loguniform(1e-5, 1e0)}
step3_esn_params = {'bias_scaling': np.linspace(0.0, 1.0, 11)}
step4_esn_params = {'alpha': loguniform(1e-5, 1e1)}

kwargs_step1 = {'n_iter': 200, 'random_state': 42, 'verbose': 1, 'n_jobs': -1, 'scoring': gpe_scorer}
kwargs_step2 = {'n_iter': 50, 'random_state': 42, 'verbose': 1, 'n_jobs': -1, 'scoring': gpe_scorer}
kwargs_step3 = {'verbose': 1, 'n_jobs': -1, 'scoring': gpe_scorer}
kwargs_step4 = {'n_iter': 50, 'random_state': 42, 'verbose': 1, 'n_jobs': -1, 'scoring': gpe_scorer}

# The searches are defined similarly to the steps of a sklearn.pipeline.Pipeline:
searches = [('step1', RandomizedSearchCV, step1_esn_params, kwargs_step1),
            ('step2', RandomizedSearchCV, step2_esn_params, kwargs_step2),
            ('step3', GridSearchCV, step3_esn_params, kwargs_step3),
            ('step4', RandomizedSearchCV, step4_esn_params, kwargs_step4)]

base_esn = SeqToSeqESNRegressor(**initially_fixed_params)

try: 
    sequential_search = load("f0/sequential_search_f0_mel_km_50.joblib")
except FileNotFoundError:
    print(FileNotFoundError)
    sequential_search = SequentialSearchCV(base_esn, searches=searches).fit(X_train, y_train)
    dump(sequential_search, "f0/sequential_search_f0_mel_km_50.joblib")

print(sequential_search)


def gpe_scorer(y_true, y_pred):
    gross_pitch_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        gross_pitch_error[k] = gpe(y_true=y_t[:, 0]*(y_t[:, 1] > 0.5), y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(gross_pitch_error)

def new_gpe_scorer(y_true, y_pred):
    gross_pitch_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        gross_pitch_error[k] = new_gpe(y_true=y_t[:, 0]*(y_t[:, 1] > 0.5), y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(gross_pitch_error)

def fpe_scorer(y_true, y_pred):
    fine_pitch_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        fine_pitch_error[k] = fpe(y_true=y_t[:, 0]*(y_t[:, 1] > 0.5), y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(fine_pitch_error)

def mu_fpe_scorer(y_true, y_pred):
    fine_pitch_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        fine_pitch_error[k] = mu_fpe(y_true=y_t[:, 0]*(y_t[:, 1] > 0.5), y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(fine_pitch_error)

def sigma_fpe_scorer(y_true, y_pred):
    fine_pitch_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        fine_pitch_error[k] = sigma_fpe(y_true=y_t[:, 0]*(y_t[:, 1] > 0.5), y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(fine_pitch_error)

def vde_scorer(y_true, y_pred):
    voicing_decision_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        voicing_decision_error[k] = vde(y_true=(y_t[:, 1] > 0.5), y_pred=y_p[:, 1]>=.5)
    return np.mean(voicing_decision_error)


def ffe_scorer(y_true, y_pred):
    frame_fault_error = [None] * len(y_true)
    for k, (y_t, y_p) in enumerate(zip(y_true, y_pred)):
        frame_fault_error[k] = ffe(y_true=y_t[:, 0]*(y_t[:, 1] > 0.5), y_pred=y_p[:, 0]*(y_p[:, 1] >= .5))
    return np.mean(frame_fault_error)


y_pred = load("f0/km_esn_dense_2000_0_0.joblib").predict(X_test)
gpe_scorer(y_test, y_pred)
new_gpe_scorer(y_test, y_pred)
fpe_scorer(y_test, y_pred)
mu_fpe_scorer(y_test, y_pred)
sigma_fpe_scorer(y_test, y_pred)
vde_scorer(y_test, y_pred)
ffe_scorer(y_test, y_pred)

param_grid = {'hidden_layer_size': [6400]}
for params in ParameterGrid(param_grid):
    kmeans = load("f0/kmeans_6400.joblib")
    w_in = np.divide(kmeans.cluster_centers_, np.linalg.norm(kmeans.cluster_centers_, axis=1)[:, None])
    print(w_in.shape)
    base_input_to_node = PredefinedWeightsInputToNode(predefined_input_weights=w_in.T)
    all_params = sequential_search.best_estimator_.get_params()
    all_params["hidden_layer_size"] = params["hidden_layer_size"]
    esn = SeqToSeqESNRegressor(input_to_node=base_input_to_node, **all_params)
    print(esn._base_estimator)
    esn.fit(X_train, y_train, n_jobs=4)
    dump(esn, "f0/km_esn_dense_6400_4_0.joblib")

"""
try:
    gs = load("f0/sequential_search_f0_mel_km_50_final_2.joblib")
except:
    param_grid = {'hidden_layer_size': [6400],  # TODO
                  'random_state': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}
    gs = []
    for params in ParameterGrid(param_grid):
        try:
            print("Attempting to load KMeans from disk...")
            kmeans = load("f0/kmeans_" + str(params["hidden_layer_size"]) + ".joblib")
            print("Loaded.")
        except FileNotFoundError:
            print("Fitting kmeans with features from the training set...")
            t1 = time.time()
            kmeans = MiniBatchKMeans(n_clusters=params["hidden_layer_size"], n_init=200, reassignment_ratio=0, max_no_improvement=50, init='k-means++', verbose=0, random_state=0)
            kmeans.fit(X=np.concatenate(np.concatenate((X_train, X_test))))
            dump(kmeans, "f0/kmeans_" + str(params["hidden_layer_size"]) + ".joblib")
            print("done in {0}!".format(time.time() - t1))
        w_in = np.divide(kmeans.cluster_centers_, np.linalg.norm(kmeans.cluster_centers_, axis=1)[:, None])
        base_input_to_node = PredefinedWeightsInputToNode(predefined_input_weights=w_in.T)
        esn = SeqTo clone(sequential_search.best_estimator_)
        esn.input_to_node = base_input_to_node
        esn.set_params(**params)
        esn.fit(X_train, y=y_train, n_jobs=4)
    dump(gs, "f0/sequential_search_f0_mel_km_50_final_2.joblib")

"""