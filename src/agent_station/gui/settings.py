"""Persistencia de preferencias de Station."""
from dataclasses import dataclass, asdict
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "station-app" / "config.json"
FUENTES = ("Sora", "Outfit", "Manrope", "Space Grotesk", "Plus Jakarta Sans", "DM Sans", "Bricolage Grotesque", "Urbanist", "Figtree", "Lexend", "Syne", "Unbounded", "Fraunces")
TEMAS = ("negro", "papel", "medianoche")


@dataclass
class Settings:
    fuente: str = "Sora"
    tamano: int = 14
    tema: str = "negro"
    animaciones: bool = True
    densidad: str = "comoda"
    escala_chat: float = 1.15

    @classmethod
    def load(cls, path=CONFIG_PATH):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError, TypeError):
            data = {}
        defaults = cls()
        fuente = data.get("fuente", defaults.fuente)
        if fuente not in FUENTES:
            fuente = defaults.fuente
        tema = data.get("tema", defaults.tema)
        tema = {"oscuro": "negro", "claro": "papel"}.get(tema, tema)
        if tema not in TEMAS:
            tema = defaults.tema
        try:
            tamano = max(10, min(24, int(data.get("tamano", defaults.tamano))))
        except (ValueError, TypeError):
            tamano = defaults.tamano
        densidad = data.get("densidad", defaults.densidad)
        if densidad not in ("compacta", "comoda", "amplia"):
            densidad = defaults.densidad
        try:
            escala_chat = float(data.get("escala_chat", defaults.escala_chat))
        except (ValueError, TypeError):
            escala_chat = defaults.escala_chat
        if escala_chat not in (1.0, 1.15, 1.3, 1.5):
            escala_chat = defaults.escala_chat


        return cls(
            fuente=fuente,
            tamano=tamano,
            tema=tema,
            animaciones=bool(data.get("animaciones", defaults.animaciones)),
            densidad=densidad,
            escala_chat=escala_chat,
        )

    def save(self, path=CONFIG_PATH):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_settings(path=CONFIG_PATH):
    return Settings.load(path)
