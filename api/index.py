"""
api/index.py
------------
Vercel serverless entrypoint. Exposes:
  GET  /api/health
  POST /api/analyze   (multipart/form-data, field name "file")

Note: WebSocket streaming (/stream in the full backend) is NOT available
here — Vercel serverless functions are request/response only and don't
support long-lived connections. Deploy the full backend (see /backend in
the project) on a platform with persistent processes (Render, Railway,
Fly.io, a VM) for real-time streaming analysis, and use this endpoint for
one-shot recording analysis only.
"""

from __future__ import annotations
import time
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import lite_features as lf
import risk_engine as re

app = FastAPI(title="VoiceGuard API (Vercel)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your dashboard's domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

MIN_ANALYZABLE_SECONDS = 1.0


class AnalyzeResponse(BaseModel):
    overall_score: float
    band: str
    recommendation: str
    features: list
    duration_sec: float
    processing_ms: float


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "voiceguard-api-vercel"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...)):
    t0 = time.time()
    raw = await file.read()
    y, sr = lf.load_audio(raw)

    if len(y) / sr < MIN_ANALYZABLE_SECONDS:
        return AnalyzeResponse(
            overall_score=0, band="INSUFFICIENT_AUDIO",
            recommendation="Clip too short for reliable analysis (need >= 1s of speech).",
            features=[], duration_sec=len(y) / sr, processing_ms=(time.time() - t0) * 1000,
        )

    features = lf.extract_all(y, sr)
    report = re.build_report(features)
    d = re.report_to_dict(report)
    return AnalyzeResponse(
        overall_score=d["overall_score"], band=d["band"], recommendation=d["recommendation"],
        features=d["features"], duration_sec=features["duration_sec"],
        processing_ms=(time.time() - t0) * 1000,
    )
