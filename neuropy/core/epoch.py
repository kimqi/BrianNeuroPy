from enum import unique
import numpy as np
import pandas as pd
from .datawriter import DataWriter
from pathlib import Path


class Epoch(DataWriter):
    def __init__(self, epochs: pd.DataFrame or None, metadata=None, file=None) -> None:
        super().__init__(metadata=metadata)

        if epochs is None:
            assert (
                file is not None
            ), "Must specify file to load if no epochs dataframe entered"
            epochs = np.load(file, allow_pickle=True).item()["epochs"]

        epochs = self._check_epochs(epochs)
        epochs.loc[:, "label"] = epochs["label"].astype("str")
        self._epochs = epochs.sort_values(by=["start"]).reset_index(drop=True)

    @property
    def starts(self):
        return self._epochs.start.values

    @property
    def stops(self):
        return self._epochs.stop.values

    @property
    def durations(self):
        return self.stops - self.starts

    @property
    def n_epochs(self):
        return len(self.starts)

    @property
    def labels(self):
        return self._epochs.label.values

    def set_labels(self, labels):
        self._epochs["label"] = labels
        return Epoch(epochs=self._epochs)

    @property
    def has_labels(self):
        return np.all(self._epochs["label"] != "")

    def __add__(self, epochs):
        assert isinstance(epochs, Epoch), "Can only add two core.Epoch objects"
        df1 = self._epochs[["start", "stop", "label"]]
        df2 = epochs._epochs[["start", "stop", "label"]]
        df_new = pd.concat([df1, df2]).reset_index(drop=True)
        return Epoch(epochs=df_new)

    def shift(self, dt):
        epochs = self._epochs.copy()
        epochs[["start", "stop"]] += dt
        return Epoch(epochs=epochs, metadata=self.metadata)

    def get_unique_labels(self):
        return np.unique(self.labels)

    def is_labels_unique(self):
        return len(np.unique(self.labels)) == len(self)

    def to_dataframe(self):
        df = self._epochs.copy()
        df["duration"] = self.durations
        return df

    def add_column(self, name: str, arr: np.ndarray):
        data = self.to_dataframe()
        data[name] = arr
        return Epoch(epochs=data, metadata=self.metadata)

    def add_dataframe(self, df: pd.DataFrame):
        assert isinstance(df, pd.DataFrame), "df should be a pandas dataframe"
        data = self.to_dataframe()
        data_new = pd.concat([data, df], axis=1)
        return Epoch(epochs=data_new, metadata=self.metadata)

    def _check_epochs(self, epochs):
        assert isinstance(epochs, pd.DataFrame)
        assert (
            pd.Series(["start", "stop", "label"]).isin(epochs.columns).all()
        ), "Epoch dataframe should at least have columns with names: start, stop, label"
        return epochs.copy()

    def __repr__(self) -> str:
        return f"{len(self.starts)} epochs\nSnippet: \n {self._epochs.head(5)}"

    def __str__(self) -> str:
        pass

    def __getitem__(self, i):

        if isinstance(i, str):
            data = self._epochs[self._epochs["label"] == i].copy()
        elif isinstance(i, int):
            data = self._epochs.iloc[[i]].copy()
        else:
            data = self._epochs.iloc[i].copy()

        return Epoch(epochs=data.reset_index(drop=True))

    def __len__(self):
        return self.n_epochs

    def time_slice(self, t_start, t_stop):
        # TODO time_slice should also include partial epochs
        # falling in between the timepoints
        df = self.to_dataframe()
        df = df[(df["start"] > t_start) & (df["start"] < t_stop)].reset_index(drop=True)
        return Epoch(df)

    def duration_slice(self, min_dur=None, max_dur=None):
        """return epochs that have durations between given thresholds

        Parameters
        ----------
        min_dur : float, optional
            minimum duration in seconds, by default None
        max_dur : float, optional
            maximum duration in seconds, by default None,

        Returns
        -------
        epoch
            epochs with durations between min_dur and max_dur
        """
        durations = self.durations
        if min_dur is None:
            min_dur = np.min(durations)
        if max_dur is None:
            max_dur = np.max(durations)

        return self[(durations >= min_dur) & (durations <= max_dur)]

    def label_slice(self, label):
        assert isinstance(label, str), "label must be string"
        df = self._epochs[self._epochs["label"] == label].reset_index(drop=True)
        return Epoch(epochs=df)

    @staticmethod
    def from_array(starts, stops, labels=None):
        df = pd.DataFrame({"start": starts, "stop": stops, "label": labels})
        return Epoch(epochs=df)

    @staticmethod
    def from_logical_array(arr):
        pass

    @staticmethod
    def from_string_array(arr, dt: float = 1.0, t: np.array = None):
        """Convert a string array of type ['A','A','B','C','C'] to epochs
        Parameters
        ----------
        arr : np.array
            array of strings
        dt : float
            sampling time of arr, by default 1 second
        t : np.array
            time array of same length as arr giving corresponding time in seconds, if provided it overrides dt
        """
        unique_labels = np.unique(arr)
        pad = lambda x: np.pad(x, (1, 1), "constant", constant_values=(0, 0))

        starts, stops, labels = [], [], []
        for l in unique_labels:

            l_transition = np.diff(pad(np.where(arr == l, 1, 0)))
            l_start = np.where(l_transition == 1)[0]
            l_stop = np.where(l_transition == -1)[0]

            starts.append(l_start)
            stops.append(l_stop)
            labels.extend([l] * len(l_start))

        starts = np.concatenate(starts)
        stops = np.concatenate(stops)

        # padding correction
        stops[stops == len(arr)] = len(arr) - 1

        if t is not None:
            assert len(t) == len(arr), "time length should be same as input array"
            starts = t[starts]
            stops = t[stops]
        else:
            starts = starts * dt
            stops = stops * dt

        return Epoch.from_array(starts, stops, labels)

    @staticmethod
    def from_file(f):
        d = DataWriter.from_file(f)
        if d is not None:
            return Epoch.from_dict(d)
        else:
            return None

    @property
    def is_overlapping(self):
        starts = self.starts
        stops = self.stops

        return np.all((starts[1:] - stops[:-1]) < 0)

    def itertuples(self):
        return self.to_dataframe().itertuples()

    def fill_blank(self, method="from_left"):

        ep_starts = self.starts
        ep_stops = self.stops
        ep_durations = self.durations
        ep_labels = self.labels

        mask = (ep_starts[:-1] + ep_durations[:-1]) < ep_starts[1:]
        (inds,) = np.nonzero(mask)

        if method == "from_left":
            for ind in inds:
                ep_durations[ind] = ep_starts[ind + 1] - ep_starts[ind]

        elif method == "from_right":
            for ind in inds:
                gap = ep_starts[ind + 1] - (ep_starts[ind] + ep_durations[ind])
                ep_starts[ind + 1] -= gap
                ep_durations[ind + 1] += gap

        elif method == "from_nearest":
            for ind in inds:
                gap = ep_starts[ind + 1] - (ep_starts[ind] + ep_durations[ind])
                ep_durations[ind] += gap / 2.0
                ep_starts[ind + 1] -= gap / 2.0
                ep_durations[ind + 1] += gap / 2.0

        # self.epochs["start"] = ep_starts
        # self.epochs["stop"] = ep_starts + ep_durations
        # self.epochs["duration"] = ep_durations

        return self.from_array(
            starts=ep_starts, stops=ep_starts + ep_durations, labels=ep_labels
        )

    def delete_in_between(self, t1, t2):

        epochs_df = self.to_dataframe()[["start", "stop", "label"]]
        # delete epochs if they are within t1, t2
        epochs_df = epochs_df[~((epochs_df["start"] >= t1) & (epochs_df["stop"] <= t2))]

        # truncate stop if start is less than t1 but stop is within t1,t2
        epochs_df.loc[
            (epochs_df["start"] < t1)
            & (t1 < epochs_df["stop"])
            & (epochs_df["stop"] <= t2),
            "stop",
        ] = t1

        # truncate start if stop is greater than t2 but start is within t1,t2
        epochs_df.loc[
            (epochs_df["start"] > t1)
            & (epochs_df["start"] <= t2)
            & (epochs_df["stop"] > t2),
            "start",
        ] = t2

        # if epoch starts before and ends after range,
        flank_start = epochs_df[
            (epochs_df["start"] < t1) & (epochs_df["stop"] > t2)
        ].copy()
        flank_start["stop"] = t1
        flank_stop = epochs_df[
            (epochs_df["start"] < t1) & (epochs_df["stop"] > t2)
        ].copy()
        flank_stop["start"] = t2
        epochs_df = epochs_df[~((epochs_df["start"] < t1) & (epochs_df["stop"] > t2))]
        epochs_df = pd.concat([epochs_df, flank_start, flank_stop], ignore_index=True)
        return Epoch(epochs_df)

    def get_proportion_by_label(self, t_start=None, t_stop=None):

        if t_start is None:
            t_start = self.starts[0]
        if t_stop is None:
            t_stop = self.stops[-1]

        duration = t_stop - t_start

        ep = self._epochs.copy()
        ep = ep[(ep.stop > t_start) & (ep.start < t_stop)].reset_index(drop=True)

        if ep["start"].iloc[0] < t_start:
            ep.at[0, "start"] = t_start

        if ep["stop"].iloc[-1] > t_stop:
            ep.at[ep.index[-1], "stop"] = t_stop

        ep["duration"] = ep.stop - ep.start

        ep_group = ep.groupby("label").sum().duration / duration

        label_proportion = {}
        for label in self.get_unique_labels():
            label_proportion[label] = 0.0

        for state in ep_group.index.values:
            label_proportion[state] = ep_group[state]

        return label_proportion

    def count(self, t_start=None, t_stop=None, binsize=300):

        if t_start is None:
            t_start = 0

        if t_stop is None:
            t_stop = np.max(self.stops)

        mid_times = self.starts + self.durations / 2
        bins = np.arange(t_start, t_stop + binsize, binsize)
        return np.histogram(mid_times, bins=bins)[0]

    def as_array(self):
        """Returns starts and stops as 2d numpy array"""
        return self.to_dataframe()[["start", "stop"]].to_numpy()

    def flatten(self):
        """Returns 1d numpy array of alternating starts and stops
        NOTE: returned array is monotonically increasing only if epochs are non-overlapping
        """
        return self.as_array().flatten("C")
