"""Wrapper para rodar o DocTrack em porta alternativa (apenas para preview local)."""
import os
from servidor import app, socketio
port = int(os.environ.get("PORT", "5099"))
socketio.run(app, host="127.0.0.1", port=port, allow_unsafe_werkzeug=True)
