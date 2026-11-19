"""Persistencia de preferencias de Station."""
from dataclasses import dataclass, asdict
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "station-app" / "config.json"
FUENTES = ("Sora", "Outfit", "Manrope", "Space Grotesk", "Plus Jakarta Sans", "DM Sans", "Bricolage Grotesque", "Urbanist", "Figtree", "Lexend", "Syne", "Unbounded", "Fraunces")
TEMAS = ("negro", "papel", "medianoche")
VOCES = ("af_heart", "af_bella", "af_nova", "af_sky", "am_adam", "am_michael", "bf_emma", "bm_george")
IDIOMAS_STT = ("es", "en", "auto")
MODELOS_STT = ("tiny", "base", "small", "medium")


@dataclass
class Settings:
    fuente: str = "Sora"
    tamano: int = 14
    tema: str = "negro"
    animaciones: bool = True
    densidad: str = "comoda"
    escala_chat: float = 1.15
    voz_tts: bool = True
    voz_interactiva: bool = False
    voz_auto_enviar: bool = True
    voz_nombre: str = "af_heart"
    voz_velocidad: float = 1.05
    voz_idioma_stt: str = "es"
    voz_modelo_stt: str = "small"
    voz_barge_in: bool = True
    voz_ducking: bool = True

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

        voz_nombre = data.get("voz_nombre", defaults.voz_nombre)
        if voz_nombre not in VOCES:
            voz_nombre = defaults.voz_nombre
        try:
            voz_velocidad = max(0.7, min(1.5, float(data.get("voz_velocidad", defaults.voz_velocidad))))
        except (ValueError, TypeError):
            voz_velocidad = defaults.voz_velocidad
        voz_idioma_stt = data.get("voz_idioma_stt", defaults.voz_idioma_stt)
        if voz_idioma_stt not in IDIOMAS_STT:
            voz_idioma_stt = defaults.voz_idioma_stt
        voz_modelo_stt = data.get("voz_modelo_stt", defaults.voz_modelo_stt)
        if voz_modelo_stt not in MODELOS_STT:
            voz_modelo_stt = defaults.voz_modelo_stt

        return cls(
            fuente=fuente,
            tamano=tamano,
            tema=tema,
            animaciones=bool(data.get("animaciones", defaults.animaciones)),
            densidad=densidad,
            escala_chat=escala_chat,
            voz_tts=bool(data.get("voz_tts", defaults.voz_tts)),
            voz_interactiva=bool(data.get("voz_interactiva", defaults.voz_interactiva)),
            voz_auto_enviar=bool(data.get("voz_auto_enviar", defaults.voz_auto_enviar)),
            voz_nombre=voz_nombre,
            voz_velocidad=voz_velocidad,
            voz_idioma_stt=voz_idioma_stt,
            voz_modelo_stt=voz_modelo_stt,
            voz_barge_in=bool(data.get("voz_barge_in", defaults.voz_barge_in)),
            voz_ducking=bool(data.get("voz_ducking", defaults.voz_ducking)),
        )

    def save(self, path=CONFIG_PATH):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_settings(path=CONFIG_PATH):
    return Settings.load(path)
