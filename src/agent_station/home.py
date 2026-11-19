"""Ubicación de los datos. AGENT_STATION_HOME (def. ~/.agent-station). Nada depende de Claude, Codex ni del SO."""
import os
from pathlib import Path


def home() -> Path:
    p = Path(os.environ.get("AGENT_STATION_HOME", Path.home() / ".agent-station"))
    p.mkdir(parents=True, exist_ok=True)
    return p
