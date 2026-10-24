"""FastAPI app factory. From backend/:

    uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.audio_store import AudioStore
from app.config import FRONTEND_DIR, Settings
from app.loader import load_slot
from app.modules import correction, emotion, lipreading, telephony, tts
from app.pipeline import Pipeline
from app.sessions import SessionStore

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    pipeline = Pipeline(
        lipreading=load_slot("lipreading", lipreading, settings.lipreading),
        correction=load_slot("correction", correction, settings.correction),
        emotion=load_slot("emotion", emotion, settings.emotion),
        tts=load_slot("tts", tts, settings.tts),
        telephony=load_slot("telephony", telephony, settings.telephony),
        audio_store=AudioStore(),
    )

    app = FastAPI(title="Silent Speech")
    app.state.settings = settings
    app.state.pipeline = pipeline
    app.state.sessions = SessionStore()
    app.state.audio_store = pipeline.audio_store

    # Lets the frontend be hosted somewhere else (e.g. Vercel) and still call this backend.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(api_router)
    if pipeline.telephony.impl.router is not None:  # e.g. webhooks of the phone provider
        app.include_router(pipeline.telephony.impl.router)
    # Mounted last: it catches every path the routes above don't handle.
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
