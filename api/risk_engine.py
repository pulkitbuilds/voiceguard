"""
risk_engine.py
--------------
Combines raw acoustic features into a 0-100 impersonation risk score with
a per-feature breakdown, a risk band, and a recommended action — mirroring
the "Real-Time Risk Scoring Engine" and "Alerting and User Interaction
Layer" components of the framework.

The thresholds below are heuristic starting points calibrated against
typical conversational-speech statistics reported in speech-science
literature. In a production deployment these should be replaced/tuned
using labeled genuine-vs-synthetic call data for the target population
(languages, accents, handset/codec conditions), and this whole module
should sit downstream of / alongside a trained neural spoof classifier
rather than standing in for one.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class FeatureScore:
    name: str
    risk: float                 # 0-100
    raw_value: Optional[float]
    detail: str


@dataclass
class RiskReport:
    overall_score: float
    band: str                   # LOW / MEDIUM / HIGH
    features: list = field(default_factory=list)
    recommendation: str = ""


WEIGHTS = {
    "jitter": 0.30,
    "flatness": 0.25,
    "rolloff": 0.20,
    "pause": 0.15,
    "zcr": 0.10,
}


def score_jitter(jitter_pct: Optional[float]) -> FeatureScore:
    if jitter_pct is None:
        return FeatureScore("pitch_jitter", 20.0, None, "Insufficient voiced audio to estimate pitch jitter.")
    if jitter_pct < 0.5:
        risk = clamp(80 - jitter_pct * 60, 40, 90)
        detail = "Unnaturally smooth pitch contour (below typical human jitter of ~0.5-3.5%)."
    elif jitter_pct <= 3.5:
        risk = clamp(25 - (jitter_pct - 0.5) * 4, 5, 25)
        detail = "Pitch jitter within natural conversational range."
    else:
        risk = clamp(30 + (jitter_pct - 3.5) * 10, 30, 92)
        detail = "Erratic pitch variation, consistent with vocoder glitching or channel artifacts."
    return FeatureScore("pitch_jitter", risk, jitter_pct, detail)


def score_flatness(flatness: Optional[float]) -> FeatureScore:
    if flatness is None:
        return FeatureScore("spectral_flatness", 20.0, None, "Insufficient data.")
    if flatness < 0.10:
        risk = clamp(75 - flatness * 300, 45, 88)
        detail = "Spectrum unnaturally tonal/smooth for conversational speech."
    elif flatness <= 0.42:
        risk = clamp(15 + abs(flatness - 0.25) * 40, 8, 30)
        detail = "Spectral flatness within natural range."
    else:
        risk = clamp(35 + (flatness - 0.42) * 120, 35, 90)
        detail = "Spectrum unusually noise-like, consistent with vocoder artifacts."
    return FeatureScore("spectral_flatness", risk, flatness, detail)


def score_rolloff(drop_slope: Optional[float]) -> FeatureScore:
    if drop_slope is None:
        return FeatureScore("rolloff_sharpness", 20.0, None, "Insufficient data.")
    risk = clamp(drop_slope * 140, 6, 92)
    detail = ("Sharp, step-like high-frequency cutoff typical of band-limited neural vocoders."
              if risk > 55 else "Gradual high-frequency roll-off consistent with natural speech/telephony.")
    return FeatureScore("rolloff_sharpness", risk, drop_slope, detail)


def score_pause(pause_cov: Optional[float]) -> FeatureScore:
    if pause_cov is None:
        return FeatureScore("pause_regularity", 20.0, None, "Insufficient pauses detected to assess timing.")
    if pause_cov < 0.20:
        risk = clamp(85 - pause_cov * 100, 55, 88)
        detail = "Pause durations unusually regular — a common TTS/segment-concatenation signature."
    elif pause_cov <= 0.6:
        risk = 20.0
        detail = "Pause timing shows natural irregularity."
    else:
        risk = clamp(25 + (pause_cov - 0.6) * 30, 25, 60)
        detail = "Highly irregular pausing; monitor alongside other indicators."
    return FeatureScore("pause_regularity", risk, pause_cov, detail)


def score_zcr(zcr_std: Optional[float]) -> FeatureScore:
    if zcr_std is None:
        return FeatureScore("zcr_microvariability", 20.0, None, "Insufficient data.")
    if zcr_std < 0.006:
        risk = clamp(80 - zcr_std * 4000, 45, 85)
        detail = "Suppressed frame-to-frame micro-variability, a hallmark of oversmoothed synthetic audio."
    else:
        risk = 15.0
        detail = "Micro-variability within natural range."
    return FeatureScore("zcr_microvariability", risk, zcr_std, detail)


def build_report(features: dict) -> RiskReport:
    """features: the dict returned by audio_features.extract_all()"""
    fj = score_jitter(features["pitch"].get("jitter_pct"))
    ff = score_flatness(features["spectral"].get("flatness_mean"))
    fr = score_rolloff(features["spectral"].get("rolloff_drop_slope"))
    fp = score_pause(features["pause"].get("pause_cov"))
    fz = score_zcr(features["zcr"].get("zcr_std"))

    overall = (
        WEIGHTS["jitter"] * fj.risk +
        WEIGHTS["flatness"] * ff.risk +
        WEIGHTS["rolloff"] * fr.risk +
        WEIGHTS["pause"] * fp.risk +
        WEIGHTS["zcr"] * fz.risk
    )
    overall = round(overall, 1)

    if overall > 65:
        band = "HIGH"
        rec = ("High impersonation risk. Do not approve fund transfers or disclose confidential "
               "information based on this call. Trigger an independent call-back on a verified number, "
               "require secondary verification (MFA / supervisor escalation), and log the interaction "
               "for review.")
    elif overall > 35:
        band = "MEDIUM"
        rec = ("Elevated risk. Ask a dynamic, unscripted verification question, avoid approving "
               "high-value or irreversible actions this call, and consider stepping up authentication.")
    else:
        band = "LOW"
        rec = "No strong synthetic-speech indicators detected. Continue standard verification practice."

    return RiskReport(
        overall_score=overall,
        band=band,
        features=[fj, ff, fr, fp, fz],
        recommendation=rec,
    )


def report_to_dict(report: RiskReport) -> dict:
    return {
        "overall_score": report.overall_score,
        "band": report.band,
        "recommendation": report.recommendation,
        "features": [
            {"name": f.name, "risk": round(f.risk, 1), "raw_value": f.raw_value, "detail": f.detail}
            for f in report.features
        ],
    }
