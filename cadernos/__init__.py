"""Módulo Cadernos — cadernos de laboratório (substitui o OneNote do PDR)."""
from .routes import cadernos_bp, init_realtime, purgar_lixeira

__all__ = ["cadernos_bp", "init_realtime", "purgar_lixeira"]
