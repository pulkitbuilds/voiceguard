"""
lite_features.py
-----------------
Vercel-serverless-friendly reimplementation of VoiceGuard's acoustic feature
extraction, using only numpy + scipy + soundfile (no librosa/numba). This
mirrors the algorithms used in the browser dashboard (autocorrelation pitch,
FFT-based spectral shape, RMS-based pause segmentation) and keeps the
function's deployed size and cold-start time small enough for a serverless
runtime. For higher-accuracy offline/batch analysis, use the full librosa
based `backend/` version instead (deploy it on Render/Railway/Fly.io etc,
where package size and long-lived processes aren't constrained).
"""

from __future__ import annotations
import numpy as np
import soundfile as sf
import io

FRAME = 2048
HOP = 512
F0_MIN, F0_MAX = 70, 400


def load_audio(raw: bytes, target_sr: int = 16000) -> tuple[np.ndarray, int]:
    y, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != target_sr:
        # simple polyphase-free resample via linear interpolation (adequate for
        # feature extraction here; swap for scipy.signal.resample_poly if you
        # need higher fidelity and don't mind the extra dependency weight)
        duration = len(y) / sr
        new_len = int(duration * target_sr)
        y = np.interp(
            np.linspace(0, len(y), new_len, endpoint=False),
            np.arange(len(y)), y,
        ).astype("float32")
        sr = target_sr
    return y, sr


def _autocorr_pitch(frame: np.ndarray, sr: int) -> float | None:
    rms = np.sqrt(np.mean(frame ** 2))
    if rms < 0.01:
        return None
    min_lag, max_lag = int(sr / F0_MAX), int(sr / F0_MIN)
    if max_lag >= len(frame):
        return None
    best_lag, best_corr = -1, 0.0
    for lag in range(min_lag, max_lag):
        corr = float(np.dot(frame[: len(frame) - lag], frame[lag:]))
        if corr > best_corr:
            best_corr, best_lag = corr, lag
    if best_lag <= 0:
        return None
    norm = best_corr / (len(frame) * rms ** 2 + 1e-9)
    if norm < 0.28:
        return None
    return sr / best_lag


def pitch_jitter(y: np.ndarray, sr: int) -> dict:
    pitches = []
    for start in range(0, len(y) - FRAME, HOP):
        f0 = _autocorr_pitch(y[start:start + FRAME], sr)
        if f0:
            pitches.append(f0)
    if len(pitches) < 6:
        return {"jitter_pct": None, "mean_f0": None, "n_voiced_frames": len(pitches)}
    diffs = np.abs(np.diff(pitches))
    mean_f0 = float(np.mean(pitches))
    jitter_pct = float(np.mean(diffs) / mean_f0 * 100) if mean_f0 > 0 else None
    return {"jitter_pct": jitter_pct, "mean_f0": mean_f0, "n_voiced_frames": len(pitches)}


def spectral_shape(y: np.ndarray, sr: int) -> dict:
    flatness_vals, slope_vals, rolloff_vals = [], [], []
    window = np.hanning(FRAME)
    freqs = np.fft.rfftfreq(FRAME, d=1 / sr)
    for start in range(0, len(y) - FRAME, HOP):
        seg = y[start:start + FRAME] * window
        mag = np.abs(np.fft.rfft(seg)) + 1e-12
        arith_mean = float(np.mean(mag))
        geo_mean = float(np.exp(np.mean(np.log(mag))))
        flatness_vals.append(geo_mean / arith_mean)

        cum = np.cumsum(mag)
        target = 0.85 * cum[-1]
        bin_idx = int(np.searchsorted(cum, target))
        rolloff_vals.append(freqs[min(bin_idx, len(freqs) - 1)])

        w = max(2, int(0.02 * len(freqs)))
        lo, hi = max(0, bin_idx - w), min(len(freqs) - 1, bin_idx + w)
        slope_vals.append((mag[lo] - mag[hi]) / (mag[lo] + mag[hi] + 1e-9))

    if not flatness_vals:
        return {"flatness_mean": None, "rolloff_mean_hz": None, "rolloff_drop_slope": None}
    return {
        "flatness_mean": float(np.mean(flatness_vals)),
        "rolloff_mean_hz": float(np.mean(rolloff_vals)),
        "rolloff_drop_slope": float(np.mean(slope_vals)),
    }


def pause_pattern(y: np.ndarray, sr: int, rms_threshold: float = 0.012) -> dict:
    frame_rms = [
        np.sqrt(np.mean(y[s:s + FRAME] ** 2))
        for s in range(0, len(y) - FRAME, HOP)
    ]
    silent = np.array(frame_rms) < rms_threshold
    frame_dur_ms = HOP / sr * 1000
    durations, run = [], 0
    for is_silent in silent:
        if is_silent:
            run += 1
        elif run > 0:
            durations.append(run * frame_dur_ms)
            run = 0
    if run > 0:
        durations.append(run * frame_dur_ms)
    pauses = [d for d in durations if 80 < d < 2500]
    if len(pauses) < 3:
        return {"pause_cov": None, "n_pauses": len(pauses)}
    arr = np.array(pauses)
    cov = float(np.std(arr) / np.mean(arr)) if np.mean(arr) > 0 else None
    return {"pause_cov": cov, "n_pauses": len(pauses)}


def zcr_microvariability(y: np.ndarray) -> dict:
    zcrs = []
    for start in range(0, len(y) - FRAME, HOP):
        seg = y[start:start + FRAME]
        zcrs.append(float(np.mean(np.abs(np.diff(np.sign(seg))) > 0)))
    if not zcrs:
        return {"zcr_std": None}
    return {"zcr_std": float(np.std(zcrs))}


def extract_all(y: np.ndarray, sr: int) -> dict:
    return {
        "pitch": pitch_jitter(y, sr),
        "spectral": spectral_shape(y, sr),
        "pause": pause_pattern(y, sr),
        "zcr": zcr_microvariability(y),
        "duration_sec": float(len(y) / sr),
    }
