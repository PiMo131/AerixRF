"""AERIX RF dataset normalisation layer (Workstream D).

See ``docs/design/dataset-normalization.md`` for the pipeline stages (S0-S7),
the sidecar schema, label taxonomy and split policy this package implements.

This subpackage is independent of the live acquisition/classification/decode
code paths (``aerix_rf.sdr`` / ``aerix_rf.classify`` / ``aerix_rf.decode``):
it prepares offline training/eval corpora, it does not touch the runtime
receiver pipeline.
"""

from .adapters import (
    ADAPTERS,
    Adapter,
    RecordingMeta,
    RubDroneSecurityAdapter,
    ZenodoDroneRF2020Adapter,
)
from .prepare import PrepareStats, prepare_dataset
from .resample import (
    CANONICAL_RATE_HZ,
    USABLE_BW_HZ,
    apply_chain,
    chain_to_json,
    mix_and_slice,
    plan_chain,
    usable_bandwidth,
)
from .spec import SCHEMA_VERSION, WindowSidecar
from .tensor import (
    CANONICAL_FFT,
    CANONICAL_HOP,
    canonical_stft,
    detector_frames,
    ml_tensor,
    power_dbfs,
    usable_mask,
)
from .window import iter_windows, n_expected_windows

__all__ = [
    "ADAPTERS",
    "Adapter",
    "RecordingMeta",
    "RubDroneSecurityAdapter",
    "ZenodoDroneRF2020Adapter",
    "PrepareStats",
    "prepare_dataset",
    "SCHEMA_VERSION",
    "WindowSidecar",
    "CANONICAL_RATE_HZ",
    "USABLE_BW_HZ",
    "apply_chain",
    "chain_to_json",
    "mix_and_slice",
    "plan_chain",
    "usable_bandwidth",
    "CANONICAL_FFT",
    "CANONICAL_HOP",
    "canonical_stft",
    "detector_frames",
    "ml_tensor",
    "power_dbfs",
    "usable_mask",
    "iter_windows",
    "n_expected_windows",
]
