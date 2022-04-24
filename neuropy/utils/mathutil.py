import numpy as np
import math
import pandas as pd
from sklearn.decomposition import FastICA, PCA
from scipy import stats
from hmmlearn.hmm import GaussianHMM
from .ccg import correlograms
import scipy.signal as sg


def min_max_scaler(x, axis=-1):
    """Scales the values x to lie between 0 and 1 along the specfied axis

    Parameters
    ----------
    x : np.array
        numpy ndarray

    Returns
    -------
    np.array
        scaled array
    """
    return (x - np.min(x, axis=axis, keepdims=True)) / np.ptp(
        x, axis=axis, keepdims=True
    )


def cdf(x, bins):
    """Returns cummulative distribution for x at bins"""
    return np.cumsum(np.histogram(x, bins, density=True)[0])


def partialcorr(x, y, z):
    """
    correlation between x and y , with controlling for z
    """
    # convert them to pandas series
    x = pd.Series(x)
    y = pd.Series(y)
    z = pd.Series(z)
    # xyz = pd.DataFrame({"x-values": x, "y-values": y, "z-values": z})

    xy = x.corr(y)
    xz = x.corr(z)
    zy = z.corr(y)

    parcorr = (xy - xz * zy) / (np.sqrt(1 - xz**2) * np.sqrt(1 - zy**2))

    return parcorr


def parcorr_mult(x, y, z):
    """
    correlation between multidimensional x and y , with controlling for multidimensional z

    """

    parcorr = np.zeros((len(z), len(y), len(x)))
    for i, x_ in enumerate(x):
        for j, y_ in enumerate(y):
            for k, z_ in enumerate(z):
                parcorr[k, j, i] = partialcorr(x_, y_, z_)

    revcorr = np.zeros((len(z), len(y), len(x)))
    for i, x_ in enumerate(x):
        for j, y_ in enumerate(y):
            for k, z_ in enumerate(z):
                revcorr[k, j, i] = partialcorr(x_, z_, y_)

    return parcorr, revcorr


# TODO improve the partial correlation calucalation maybe use arrays instead of list
def parcorr_muglt(x, y, z):
    """
    correlation between multidimensional x and y , with controlling for multidimensional z

    """

    parcorr = np.zeros(z.shape[0], y.shape[0], x.shape[0])
    for i, x_ in enumerate(x):
        for j, y_ in enumerate(y):
            for k, z_ in enumerate(z):
                parcorr[k, j, i] = partialcorr(x_, y_, z_)

    revcorr = np.zeros((len(z), len(y), len(x)))
    for i, x_ in enumerate(x):
        for j, y_ in enumerate(y):
            for k, z_ in enumerate(z):
                revcorr[k, j, i] = partialcorr(x_, z_, y_)

    return parcorr, revcorr


def getICA_Assembly(x):
    """extracting statisticaly independent components from significant eigenvectors as detected using Marcenko-Pasteur distributionvinput = Matrix  (m x n) where 'm' are the number of cells and 'n' time bins ICA weights thus extracted have highiest weight positive (as done in Gido M. van de Ven et al. 2016) V = ICA weights for each neuron in the coactivation (weight having the highiest value is kept positive) M1 =  originally extracted neuron weights

    Arguments:
        x {[ndarray]} -- [an array of size n * m]

    Returns:
        [type] -- [Independent assemblies]
    """

    zsc_x = stats.zscore(x, axis=1)

    corrmat = (zsc_x @ zsc_x.T) / x.shape[1]

    lambda_max = (1 + np.sqrt(1 / (x.shape[1] / x.shape[0]))) ** 2
    eig_val, eig_mat = np.linalg.eigh(corrmat)
    get_sigeigval = np.where(eig_val > lambda_max)[0]
    n_sigComp = len(get_sigeigval)
    pca_fit = PCA(n_components=n_sigComp, whiten=False).fit_transform(x)

    ica_decomp = FastICA(n_components=None, whiten=False).fit(pca_fit)
    W = ica_decomp.components_
    V = eig_mat[:, get_sigeigval] @ W.T

    return V


def threshPeriods(arr, lowthresh=1, highthresh=2, minDistance=30, minDuration=50):

    ThreshSignal = np.diff(np.where(arr > lowthresh, 1, 0))
    start = np.where(ThreshSignal == 1)[0]
    stop = np.where(ThreshSignal == -1)[0]

    if start[0] > stop[0]:
        stop = stop[1:]
    if start[-1] > stop[-1]:
        start = start[:-1]

    firstPass = np.vstack((start, stop)).T

    # ===== merging close events
    secondPass = []
    event = firstPass[0]
    for i in range(1, len(firstPass)):
        if firstPass[i, 0] - event[1] < minDistance:
            # Merging states
            event = [event[0], firstPass[i, 1]]
        else:
            secondPass.append(event)
            event = firstPass[i]

    secondPass.append(event)
    secondPass = np.asarray(secondPass)
    event_duration = np.diff(secondPass, axis=1).squeeze()

    # delete very short events
    shortevents = np.where(event_duration < minDuration)[0]
    thirdPass = np.delete(secondPass, shortevents, 0)
    event_duration = np.delete(event_duration, shortevents)

    # keep only events with peak above highthresh
    fourthPass = []
    # peakNormalizedPower, peaktime = [], []
    for i in range(len(thirdPass)):
        maxValue = max(arr[thirdPass[i, 0] : thirdPass[i, 1]])
        if maxValue >= highthresh:
            fourthPass.append(thirdPass[i])
            # peakNormalizedPower.append(maxValue)
            # peaktime.append(
            #     [
            #         secondPass[i, 0]
            #         + np.argmax(zscsignal[secondPass[i, 0] : secondPass[i, 1]])
            #     ]
            # )

    return np.asarray(fourthPass)


def _unpack_args(values, fs=1):
    """Parsing argument for thresh_epochs"""
    try:
        val_min, val_max = values
    except (TypeError, ValueError):
        val_min, val_max = (values, None)

    val_min = val_min * fs
    val_max = val_max * fs if val_max is not None else None

    return val_min, val_max


def thresh_epochs(arr: np.ndarray, thresh, length, sep=0, boundary=0, fs=1):

    hmin, hmax = _unpack_args(thresh)  # does not need fs
    lmin, lmax = _unpack_args(length, fs=fs)
    sep = sep * fs + 1e-6

    assert hmin >= boundary, "boundary must be smaller than min thresh"

    arr_thresh = np.where(arr >= boundary, arr, 0)
    peaks, props = sg.find_peaks(arr_thresh, height=[hmin, hmax], prominence=0)

    starts, stops = props["left_bases"], props["right_bases"]
    peaks_values = arr_thresh[peaks]

    # ----- merge overlapping epochs ------
    n_epochs = len(starts)
    ind_delete = []
    for i in range(n_epochs - 1):
        if (starts[i + 1] - stops[i]) < sep:

            # stretch the second epoch to cover the range of both epochs
            starts[i + 1] = min(starts[i], starts[i + 1])
            stops[i + 1] = max(stops[i], stops[i + 1])

            peaks_values[i + 1] = max(peaks_values[i], peaks_values[i + 1])
            peaks[i + 1] = [peaks[i], peaks[i + 1]][
                np.argmax([peaks_values[i], peaks_values[i + 1]])
            ]
            ind_delete.append(i)

    epochs_arr = np.vstack((starts, stops, peaks, peaks_values)).T
    epochs_arr = np.delete(epochs_arr, ind_delete, axis=0)

    # ----- duration thresholds ------
    epochs_length = epochs_arr[:, 1] - epochs_arr[:, 0]
    if lmax is None:
        lmax = epochs_length.max()
    ind_keep = (epochs_length >= lmin) & (epochs_length <= lmax)

    starts, stops, peaks, peaks_values = epochs_arr[ind_keep, :].T

    return starts / fs, stops / fs, peaks / fs, peaks_values


def contiguous_regions(condition):
    """Finds contiguous True regions of the boolean array "condition". Returns
    a 2D array where the first column is the start index of the region and the
    second column is the end index. Taken directly from stackoverflow:
    https://stackoverflow.com/questions/4494404/find-large-number-of-
    consecutive-values-fulfilling-condition-in-a-numpy-array"""

    # Find the indices of changes in "condition"
    d = np.diff(condition)
    (idx,) = d.nonzero()

    # We need to start things after the change in "condition". Therefore,
    # we'll shift the index by 1 to the right.
    idx += 1

    if condition[0]:
        # If the start of condition is True prepend a 0
        idx = np.r_[0, idx]

    if condition[-1]:
        # If the end of condition is True, append the length of the array
        idx = np.r_[idx, condition.size]  # Edit

    # Reshape the result into two columns
    idx.shape = (-1, 2)
    return idx


def hmmfit1d(Data, n_comp=2, n_iter=50):
    # hmm states on 1d data and returns labels with highest mean = highest label
    flag = None
    if np.isnan(Data).any():
        nan_indices = np.where(np.isnan(Data) == 1)[0]
        non_nan_indices = np.where(np.isnan(Data) == 0)[0]
        Data_og = Data
        Data = np.delete(Data, nan_indices)
        hmmlabels = np.nan * np.ones(len(Data_og))
        flag = 1

    Data = (np.asarray(Data)).reshape(-1, 1)
    model = GaussianHMM(n_components=n_comp, n_iter=n_iter).fit(Data)
    hidden_states = model.predict(Data)
    mus = np.squeeze(model.means_)
    sigmas = np.squeeze(np.sqrt(model.covars_))
    transmat = np.array(model.transmat_)

    idx = np.argsort(mus)
    mus = mus[idx]
    sigmas = sigmas[idx]
    transmat = transmat[idx, :][:, idx]

    state_dict = {}
    states = [i for i in range(5)]
    for i in idx:
        state_dict[idx[i]] = states[i]

    relabeled_states = np.asarray([state_dict[h] for h in hidden_states])
    relabeled_states[:2] = [0, 0]
    relabeled_states[-2:] = [0, 0]

    hmmlabels = None
    if flag:

        hmmlabels[non_nan_indices] = relabeled_states

    else:
        hmmlabels = relabeled_states

    return hmmlabels


def eventpsth(ref, event, fs, quantparam=None, binsize=0.01, window=1, nQuantiles=1):
    """psth of 'event' with respect to 'ref'

    Parameters
    ----------
    ref (array):
        1-D array of timings of reference event in seconds
    event (1D array):
        timings of events whose psth will be calculated
    fs:
        sampling rate
    quantparam (1D array):
        values used to divide 'ref' into quantiles
    binsize (float, optional):
        [description]. Defaults to 0.01.
    window (int, optional):
        [description]. Defaults to 1.
    nQuantiles (int, optional):
        [description]. Defaults to 10.

    Returns
    -------
        [type]: [description]
    """

    ref = np.asarray(ref)
    event = np.asarray(event)

    if quantparam is not None:
        assert len(event) == len(quantparam), print(
            "length of quantparam must be same as ref events"
        )
        quantiles = pd.qcut(quantparam, nQuantiles, labels=False)

        quants, eventid = [], []
        for category in range(nQuantiles):
            indx = np.where(quantiles == category)[0]
            quants.append(ref[indx])
            eventid.append(category * np.ones(len(indx)).astype(int))

        quants.append(event)
        eventid.append(((nQuantiles + 1) * np.ones(len(event))).astype(int))

        quants = np.concatenate(quants)
        eventid = np.concatenate(eventid)
    else:
        quants = np.concatenate((ref, event))
        eventid = np.concatenate([np.ones(len(ref)), 2 * np.ones(len(event))]).astype(
            int
        )

    sort_ind = np.argsort(quants)

    ccg = correlograms(
        quants[sort_ind],
        eventid[sort_ind],
        sample_rate=fs,
        bin_size=binsize,
        window_size=window,
    )

    return ccg[:-1, -1, :]


def gini(arr, eps=1e-8):
    """
    Calculate the Gini coefficient of a numpy array.

    Source: PyGini
    https://github.com/mckib2/pygini/blob/master/pygini/gini.py

    -----
    Based on bottom eq on [2]_.
    References
    ----------
    .. [2]_ http://www.statsdirect.com/help/
            default.htm#nonparametric_methods/gini.htm
    """

    # All values are treated equally, arrays must be 1d and > 0:
    arr = np.abs(arr).flatten() + eps

    # Values must be sorted:
    arr = np.sort(arr)

    # Index per array element:
    index = np.arange(1, arr.shape[0] + 1)

    # Number of array elements:
    N = arr.shape[0]

    # Gini coefficient:
    return (np.sum((2 * index - N - 1) * arr)) / (N * np.sum(arr))
