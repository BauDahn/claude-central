"""Subsistema de voz local de Station (TTS Kokoro + dictado/escucha Silero VAD & Whisper)."""
from .motor import (
    VOCES_KOKORO,
    extraer_voz,
    instrucciones_interactivo,
    instrucciones_voz,
    limpiar_para_tts,
    match_agent_prefix,
    match_command,
    match_mode,
    modelos_kokoro,
    python_voz,
    quitar_voz,
    tiene_espanol,
)

__all__ = [
    "VOCES_KOKORO",
    "extraer_voz",
    "instrucciones_interactivo",
    "instrucciones_voz",
    "limpiar_para_tts",
    "match_agent_prefix",
    "match_command",
    "match_mode",
    "modelos_kokoro",
    "python_voz",
    "quitar_voz",
    "tiene_espanol",
]
