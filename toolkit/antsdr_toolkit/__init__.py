"""antsdr_toolkit: RF drone detection with an ANTSDR E200 (AD9361, 2x2, <= 56 MHz).

Research-independent core: sample sources (file replay, synthetic scenes),
SigMF recording/playback, spectral DSP (STFT, bursts, features) and bridges to
the E200 DroneID firmware. No hardware library is imported at module import
time; the pyadi-iio device driver lives behind the optional ``e200`` extra.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
