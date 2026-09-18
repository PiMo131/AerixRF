"""Canonical STFT + derived tensors for dataset normalisation (Workstream D, T3).

Implements stages S5/S6 of ``docs/design/dataset-normalization.md`` and D7-D9
of ``docs/design/canonical-representation.md``:

    S5 canonical STFT   FFT 1024 / Hann / hop 512, coherent-gain normalised, dBFS
    S6 ML tensor        linear block-mean x30 -> [n_frames x 1024] float32 dBFS

Coherent-gain normalisation (D10, and the A3 memo section 4 "canonical fix"):
the raw FFT of a Hann-windowed full-scale complex tone landing exactly on a
bin centre sums to ``Sum(w)`` (the window's coherent gain), not 1.0. Dividing
the complex spectrum by ``Sum(w)`` before taking magnitude/dB is what makes a
full-scale tone read 0.0 dBFS. This is applied once, inside
:func:`canonical_stft`; everything downstream (:func:`power_dbfs`,
:func:`detector_frames`, :func:`ml_tensor`) consumes already-normalised
values and only reduces/logs them.

Known, deliberate discrepancy with the *live* detector path -- not
reconciled here (a later task's job): ``aerix_rf/dsp/spectrogram.py``
(``compute``) scales power by ``1/fft_size**2`` with an *unnormalised* Hann
window, so a full-scale tone there reads roughly -6 dBFS, not 0 dBFS, and its
output is not a calibrated PSD (see the A3 memo section 4). This module does
not share that scaling and must not be made to match it silently; the two
paths are independently correct/incorrect until a dedicated reconciliation
task ports the coherent-gain fix into the live path (A3 memo section 4,
"Canonical fix").

Edge convention (only place this module pads anything): a continuous hop-512
analysis of ``n`` samples yields at most ``n // hop`` full frames in the
usual "frame i needs samples [i*hop, i*hop+fft)" sense; the very last frame
of that count can need up to one ``hop`` (512 samples / 33.3 us) of samples
past the end of ``iq``. Since ``fft_size == 2*hop``, this is bounded and
small -- a standard trailing edge zero-pad for the last analysis frame of
data that *was actually captured*, not the forbidden S3 "pad a short window
to a nominal length" (which would fabricate whole extra milliseconds/seconds
of silence and is rejected in ``window.py``/the design memo). This is what
makes an exact 1.000 s window (15 360 000 samples) produce exactly 1000 ms
tensor frames and an exact 0.25 s window produce exactly 250: both are
degenerate cases of ``(n // hop) // frames_per_ms`` with the bounded tail pad
folded in, not a special case.

Memory footprint: a naive ``canonical_stft`` over a full 1.000 s canonical
window is 30000 frames x 1024 complex64 = ~246 MB, most of which
:func:`ml_tensor` never needs to keep -- it only needs the 1000 x 1024
float32 (4 MB) block-mean result. :func:`ml_tensor` therefore does not call
:func:`canonical_stft` on the whole window; it streams ``_CHUNK_MS``
milliseconds (``_CHUNK_MS * frames_per_ms`` STFT frames, ~24.6 MB of
complex64 at the default) at a time, block-means each chunk in linear power,
and discards the chunk's complex frames before moving on. :func:`canonical_stft`
itself is the small-window/reference implementation (used directly in tests
and for the detector path on modest inputs) and is *not* meant to be called
on a full 1 s window in a memory-constrained context.
"""

from __future__ import annotations

import numpy as np
import scipy.fft as sfft

CANONICAL_FFT = 1024
CANONICAL_HOP = 512

# dBFS floor to avoid log(0) on an exact-zero bin (e.g. the very first
# sample of an all-zero synthetic test array).
_EPS = 1e-12

# Streaming chunk size for ml_tensor: milliseconds of output processed per
# iteration. 40 ms * 30 frames/ms = 1200 STFT frames in flight at once
# (~9.8 MB complex64 for the frame view/window-multiply temporary). Measured
# (tracemalloc) peak for a full 1.000 s canonical window at this chunk size
# is ~70 MB -- comfortably under the ~120 MB budget, including scipy.fft's
# internal temporaries and the block-mean/output arrays. Chunk-size-vs-peak
# is close to linear (measured ~35 MB at 20 ms, ~166 MB at 100 ms), so this
# is a deliberate, tunable trade against per-chunk Python/FFT-call overhead.
_CHUNK_MS = 40

_WIN_CACHE: dict[int, np.ndarray] = {}


def _hann(fft_size: int) -> np.ndarray:
    win = _WIN_CACHE.get(fft_size)
    if win is None:
        win = np.hanning(fft_size).astype(np.float64)
        _WIN_CACHE[fft_size] = win
    return win


def _frame_slice(
    iq: np.ndarray,
    start_frame: int,
    n_frames: int,
    hop: int = CANONICAL_HOP,
    fft_size: int = CANONICAL_FFT,
) -> np.ndarray:
    """Extract ``n_frames`` consecutive hop-``hop`` analysis frames of
    ``iq`` starting at hop-index ``start_frame``, zero-padding only the
    bounded trailing edge described in the module docstring."""

    if n_frames <= 0:
        return np.zeros((0, fft_size), dtype=np.complex64)
    start_sample = start_frame * hop
    end_needed = start_sample + (n_frames - 1) * hop + fft_size
    avail = iq.shape[-1]
    if end_needed <= avail:
        seg = np.asarray(iq[..., start_sample:end_needed], dtype=np.complex64)
    else:
        pad = end_needed - avail
        head = np.asarray(iq[..., start_sample:avail], dtype=np.complex64)
        seg = np.concatenate([head, np.zeros(pad, dtype=np.complex64)])
    return np.lib.stride_tricks.sliding_window_view(seg, fft_size)[::hop]


def _n_stft_frames(n_samples: int, hop: int = CANONICAL_HOP) -> int:
    """Number of hop-aligned analysis frames obtainable from ``n_samples``
    under the bounded trailing-edge-pad convention (module docstring)."""

    return max(0, int(n_samples) // hop)


_HALF_FFT = CANONICAL_FFT // 2  # 512; CANONICAL_FFT is even, checked once here


def _fftshift_axis1(spec: np.ndarray) -> np.ndarray:
    """Equivalent to ``scipy.fft.fftshift(spec, axes=1)`` for the fixed
    even ``CANONICAL_FFT`` width used throughout this module: a plain
    two-half swap via slicing is bit-identical to (and, measured, faster
    than) ``sfft.fftshift``'s generic ``np.roll``-based implementation
    (F6 perf task) -- there is nothing to compute, only bytes to move."""

    return np.concatenate((spec[:, _HALF_FFT:], spec[:, :_HALF_FFT]), axis=1)


def canonical_stft(iq: np.ndarray, fs: float) -> np.ndarray:
    """FFT 1024 / Hann / hop 512, coherent-gain normalised, fftshifted.

    Returns complex64 ``[n_frames, CANONICAL_FFT]`` where
    ``n_frames == len(iq) // CANONICAL_HOP`` (module docstring edge
    convention). ``fs`` is accepted for API symmetry with the rest of this
    module (frequency axis helpers) but does not affect the STFT itself.
    """

    del fs  # unused: kept for API symmetry (frequency axis is fs-dependent elsewhere)
    n = np.asarray(iq).shape[-1]
    n_frames = _n_stft_frames(n)
    frames = _frame_slice(iq, 0, n_frames)
    if n_frames == 0:
        return frames.astype(np.complex64)
    win = _hann(CANONICAL_FFT)
    coherent_gain = win.sum()
    spec = sfft.fft(frames * win, axis=1, workers=-1)
    spec = sfft.fftshift(spec, axes=1)
    spec = spec / coherent_gain
    return spec.astype(np.complex64)


def power_dbfs(stft: np.ndarray) -> np.ndarray:
    """Absolute dBFS (float32) from a coherent-gain-normalised complex STFT
    (as returned by :func:`canonical_stft`): ``20*log10(|X|)``, referenced to
    a full-scale tone reading 0.0 dBFS."""

    mag = np.abs(np.asarray(stft, dtype=np.complex64))
    return (20.0 * np.log10(np.maximum(mag, _EPS))).astype(np.float32)


def detector_frames(power_lin: np.ndarray, factor: int = 6) -> np.ndarray:
    """Linear-power block-mean by ``factor`` along the time axis (D8: 200 us
    detector frames = factor 6 at hop 512 / 15.36 MS/s). Input and output
    stay in *linear* power (the live detector takes dB only on reduced
    quantities -- A3 memo section 5); any trailing remainder shorter than
    ``factor`` frames is dropped, consistent with ``ml_tensor``'s policy."""

    power_lin = np.asarray(power_lin)
    t = power_lin.shape[0]
    n_out = t // factor
    if n_out == 0:
        return np.zeros((0, power_lin.shape[1]), dtype=np.float32)
    trimmed = power_lin[: n_out * factor]
    return trimmed.reshape(n_out, factor, power_lin.shape[1]).mean(axis=1).astype(np.float32)


def canonical_products(
    iq: np.ndarray,
    fs: float,
    detector_factor: int = 6,
    *,
    _skip_detector: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Single-STFT path (F5 live-latency task): compute the hop-512 STFT
    once, in ``_CHUNK_MS``-ms chunks, and derive BOTH the D9 ML tensor and
    the D8 detector frames from the same per-frame spectrum -- the previous
    live path (``ml_tensor`` + a separate ``canonical_stft`` call for
    detector frames) computed the FFT twice over the same samples.

    Returns ``(ml_tensor_dbfs[n_ms, CANONICAL_FFT] float32,
    detector_frames_lin[n_det, CANONICAL_FFT] float32)`` where
    ``n_det = (len(iq) // CANONICAL_HOP) // detector_factor`` -- independent
    of, and always >= (``n_ms * frames_per_ms // detector_factor``), because
    the last (< 1 ms) tail of STFT frames past the final full ms block can
    still contain whole detector blocks (e.g. 1005 STFT frames -> 33 ms
    frames from the first 990, but 167 detector frames from 1002: the last 3
    frames are dropped, matching :func:`detector_frames`'s own remainder
    policy, not the ml-tensor grid's).

    Bit-for-bit equivalence with the previous two-call path (proven by
    ``tests/test_datasets_tensor.py::test_canonical_products_matches_old_two_pass_path``):
    the ml-tensor branch reproduces ``ml_tensor``'s exact float64-spectrum,
    float32-power, float32-mean arithmetic; the detector branch reproduces
    the exact ``canonical_stft`` complex64-rounding step (``spec.astype
    (complex64)``) followed by ``detector_frames``'s float64-power,
    float64-mean arithmetic. These two branches are *not* the same
    precision as each other -- that mismatch predates this function (see
    ``features_v2_from_iq``'s prior manual composition) and is preserved
    here on purpose, not introduced.

    ``frames_per_ms`` (``round(fs / CANONICAL_HOP / 1000)``) must be an
    integer multiple of ``detector_factor`` -- true for every ``fs`` this
    module is actually called with (the canonical 15.36 MS/s rate gives
    frames_per_ms=30, detector_factor=6) -- else a ``ValueError`` is raised
    rather than silently misaligning the two grids.
    """

    fs = float(fs)
    frames_per_ms = int(round(fs / CANONICAL_HOP / 1000.0))
    if frames_per_ms <= 0:
        raise ValueError(f"fs={fs!r} gives frames_per_ms <= 0 at hop={CANONICAL_HOP}")
    detector_factor = int(detector_factor)
    if detector_factor <= 0:
        raise ValueError(f"detector_factor={detector_factor!r} must be positive")
    if frames_per_ms % detector_factor != 0:
        raise ValueError(
            f"frames_per_ms={frames_per_ms} is not a multiple of "
            f"detector_factor={detector_factor}; canonical_products requires "
            "the ms and detector grids to align"
        )

    n = np.asarray(iq).shape[-1]
    n_stft_frames = _n_stft_frames(n)
    n_ms = n_stft_frames // frames_per_ms
    n_det = n_stft_frames // detector_factor

    win = _hann(CANONICAL_FFT)
    coherent_gain = win.sum()

    ms_out = np.empty((n_ms, CANONICAL_FFT), dtype=np.float32)
    det_out = np.empty((0 if _skip_detector else n_det, CANONICAL_FFT), dtype=np.float32)

    def _reduce_detector(spec: np.ndarray, n_blocks: int, out: np.ndarray, out_off: int) -> None:
        # Mirrors canonical_stft's complex64 rounding, then detector_frames's
        # float64 power + float64 mean.
        spec64 = spec.astype(np.complex64)
        power_lin = spec64.real.astype(np.float64) ** 2 + spec64.imag.astype(np.float64) ** 2
        block = power_lin.reshape(n_blocks, detector_factor, CANONICAL_FFT).mean(axis=1)
        out[out_off:out_off + n_blocks] = block.astype(np.float32)

    chunk_ms = max(1, _CHUNK_MS)
    ms_done = 0
    det_done = 0
    while ms_done < n_ms:
        g = min(chunk_ms, n_ms - ms_done)
        start_frame = ms_done * frames_per_ms
        n_frames_chunk = g * frames_per_ms
        frames = _frame_slice(iq, start_frame, n_frames_chunk)
        spec = sfft.fft(frames * win, axis=1, workers=-1)
        spec = _fftshift_axis1(spec)
        spec /= coherent_gain

        power_lin_ms = (spec.real * spec.real + spec.imag * spec.imag).astype(np.float32)
        block = power_lin_ms.reshape(g, frames_per_ms, CANONICAL_FFT).mean(axis=1)
        ms_out[ms_done:ms_done + g] = (10.0 * np.log10(np.maximum(block, _EPS))).astype(np.float32)

        if not _skip_detector:
            g_det = n_frames_chunk // detector_factor
            _reduce_detector(spec, g_det, det_out, det_done)
            det_done += g_det
        ms_done += g

    # Bounded tail: whole detector blocks obtainable from the (< frames_per_ms)
    # STFT frames past the last full ms block (module docstring: same
    # trailing-edge convention, no fabricated samples).
    leftover_det = 0 if _skip_detector else (n_det - det_done)
    if leftover_det > 0:
        leftover_start = n_ms * frames_per_ms
        n_frames_leftover = leftover_det * detector_factor
        frames = _frame_slice(iq, leftover_start, n_frames_leftover)
        spec = sfft.fft(frames * win, axis=1, workers=-1)
        spec = _fftshift_axis1(spec)
        spec /= coherent_gain
        _reduce_detector(spec, leftover_det, det_out, det_done)
        det_done += leftover_det

    return ms_out, det_out


def ml_tensor(iq: np.ndarray, fs: float) -> np.ndarray:
    """D9 ML tensor: linear block-mean x30 -> 1.000 ms frames, absolute
    dBFS, float32 ``[n_ms, CANONICAL_FFT]``.

    ``n_ms == (len(iq) // CANONICAL_HOP) // frames_per_ms`` where
    ``frames_per_ms = round(fs / CANONICAL_HOP / 1000)`` (30 at the
    canonical 15.36 MS/s rate). Thin wrapper over :func:`canonical_products`
    (module docstring / F5), with the detector-frame branch skipped
    (``_skip_detector=True``) since most callers (dataset ``prepare``) only
    need the ML tensor -- this keeps ``ml_tensor``'s cost/memory footprint
    what it was before F5.
    """

    return canonical_products(iq, fs, _skip_detector=True)[0]


def usable_mask(fs: float, usable_bw_hz: float) -> np.ndarray:
    """Boolean ``[CANONICAL_FFT]`` mask, True for bins within
    ``+-usable_bw_hz/2`` of the tuned centre (bin layout matches
    :func:`canonical_stft`'s fftshifted output: bin 0 = ``-fs/2``)."""

    freqs = np.fft.fftshift(np.fft.fftfreq(CANONICAL_FFT, d=1.0 / float(fs)))
    half = float(usable_bw_hz) / 2.0
    return (freqs >= -half) & (freqs <= half)
