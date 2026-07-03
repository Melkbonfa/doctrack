"""Wrapper para rodar o DocTrack em porta alternativa (apenas para preview local)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from servidor import app, socketio
port = int(os.environ.get("PORT", "5099"))
socketio.run(app, host="127.0.0.1", port=port, allow_unsafe_werkzeug=True)
