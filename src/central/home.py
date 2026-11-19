"""Ubicación de los datos. CENTRAL_HOME (def. ~/.central). Nada depende de Claude, Codex ni del SO."""
import os
from pathlib import Path


def home() -> Path:
    p = Path(os.environ.get("CENTRAL_HOME", Path.home() / ".central"))
    p.mkdir(parents=True, exist_ok=True)
    return p
