"""Módulo PDR (P&D de reagentes) — blueprint montado sob /pdr no DocTrack."""
from .routes import pdr_bp, init_realtime

__all__ = ["pdr_bp", "init_realtime"]
