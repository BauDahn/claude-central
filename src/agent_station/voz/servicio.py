"""Controlador Qt de voz local para la GUI de Station (sin bloquear el hilo de interfaz)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal

from agent_station.voz import motor


class VozController(QObject):
    """Gestiona un único worker local (TTS Kokoro + Whisper + Silero VAD) compartido entre pestañas."""

    estadoCambiado = pyqtSignal(str)     # idle, loading, listening, hearing, transcribing, talking, paused, error
    dictadoListo = pyqtSignal(str, str)  # target_id, text
    fraseEscuchada = pyqtSignal(str, bool)  # text, short
    ttsEstado = pyqtSignal(bool)         # True si está hablando
    aviso = pyqtSignal(str)

    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._proc: QProcess | None = None
        self._buf = b""
        self._ready = False
        self._pending: list[dict] = []
        self._spoken_hashes: dict[str, str] = {}
        self._estado = "idle"
        self._interactivo = False
        self._dictating_target = None

    def estado(self) -> str:
        return self._estado

    def interactivo_activo(self) -> bool:
        return self._interactivo

    def dictando(self) -> bool:
        return self._dictating_target is not None

    def disponible(self) -> tuple[bool, str]:
        d = motor.diagnostico_voz()
        if not d["python"]:
            return False, "No encontré entorno Python con kokoro-onnx y faster-whisper (ej. ~/.local/share/claude-voice/venv)."
        if not d["kokoro_onnx"] or not d["kokoro_voices"]:
            return False, "Faltan los modelos locales de Kokoro (kokoro-v1.0.onnx / voices-v1.0.bin)."
        if not d["parecord"] or not d["paplay"]:
            return False, "Faltan herramientas de audio PulseAudio/PipeWire (parecord / paplay)."
        return True, ""

    def aplicar_config(self, cfg):
        self._cfg = cfg
        if self._proc and self._proc.state() == QProcess.ProcessState.Running:
            self._send(self._config_payload(cfg))

    def _config_payload(self, cfg=None) -> dict:
        c = cfg or self._cfg
        return {
            "cmd": "config",
            "voice": getattr(c, "voz_nombre", "af_heart"),
            "speed": float(getattr(c, "voz_velocidad", 1.05)),
            "lang_tts": "en-us",
            "lang_stt": getattr(c, "voz_idioma_stt", "es"),
            "model_stt": getattr(c, "voz_modelo_stt", "small"),
            "barge_in": bool(getattr(c, "voz_barge_in", True)),
            "ducking": bool(getattr(c, "voz_ducking", True)),
        }

    def _ensure_worker(self) -> bool:
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            return True
        ok, err = self.disponible()
        if not ok:
            self.aviso.emit(err)
            return False
        py = motor.python_voz()
        worker_script = str(Path(__file__).with_name("worker.py"))
        self._buf = b""
        self._ready = False
        p = self._proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        src_root = str(Path(__file__).resolve().parents[2])
        old_pp = env.value("PYTHONPATH", "")
        env.insert("PYTHONPATH", f"{src_root}:{old_pp}" if old_pp else src_root)
        p.setProcessEnvironment(env)
        p.readyReadStandardOutput.connect(self._on_stdout)
        p.readyReadStandardError.connect(self._on_stderr)
        p.finished.connect(self._on_finished)
        p.start(py, [worker_script, "--rpc"])
        if self._cfg:
            self._send(self._config_payload(self._cfg))
        return True

    def _send(self, payload: dict):
        if not self._ensure_worker():
            return
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        if not self._ready and payload.get("cmd") != "config":
            self._pending.append(payload)
            return
        if self._proc and self._proc.state() == QProcess.ProcessState.Running:
            self._proc.write(line)

    def hablar(self, text: str, force: bool = False, key: str | None = None):
        if not text:
            return
        if key:
            import hashlib
            h = hashlib.md5(text.strip().encode()).hexdigest()
            if self._spoken_hashes.get(key) == h:
                return
            self._spoken_hashes[key] = h
        self._send({"cmd": "speak", "text": text, "id": key or str(time.time_ns()), "force": force})

    def hablar_respuesta(self, full_text: str, turn_key: str, force: bool = False):
        """Extrae <voz>...</voz> de la respuesta y la habla una sola vez por bloque distinto."""
        voz = motor.extraer_voz(full_text)
        if voz:
            self.hablar(voz, force=force, key=turn_key)
        elif force:
            body = motor.quitar_voz(full_text)
            if body:
                self.hablar(body[:400], force=True, key=None)

    def parar_habla(self):
        if self._proc and self._proc.state() == QProcess.ProcessState.Running:
            self._send({"cmd": "stop_tts"})
        motor.stop_detached_pid()

    def toggle_dictado(self, target_id: str):
        if self._dictating_target is not None:
            self._send({"cmd": "dictate_stop"})
            return
        self._dictating_target = target_id
        self._send({"cmd": "dictate_start", "target": target_id})

    def set_interactivo(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._interactivo:
            return
        self._interactivo = enabled
        if enabled:
            self._send({"cmd": "listen_start"})
        else:
            if self._proc and self._proc.state() == QProcess.ProcessState.Running:
                self._send({"cmd": "listen_stop"})

    def pausar_escucha(self, paused: bool):
        if self._proc and self._proc.state() == QProcess.ProcessState.Running:
            self._send({"cmd": "listen_pause", "paused": bool(paused)})

    def _on_stdout(self):
        if not self._proc:
            return
        self._buf += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            self._handle_event(ev)

    def _on_stderr(self):
        if not self._proc:
            return
        err = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace").strip()
        if err:
            # Ignorar mensajes informativos de ctranslate2/onnxruntime salvo líneas de error reales
            last = err.splitlines()[-1]
            if "error" in last.lower() or "traceback" in last.lower():
                self.aviso.emit(last[-220:])

    def _handle_event(self, ev: dict):
        kind = ev.get("event")
        if kind == "ready":
            self._ready = True
            if self._cfg:
                self._send(self._config_payload(self._cfg))
            pending = list(self._pending)
            self._pending.clear()
            for item in pending:
                self._send(item)
        elif kind == "state":
            self._estado = ev.get("state", "idle")
            self.estadoCambiado.emit(self._estado)
        elif kind == "tts_start":
            self.ttsEstado.emit(True)
        elif kind == "tts_end":
            self.ttsEstado.emit(False)
        elif kind == "dictate_result":
            target = ev.get("target") or self._dictating_target or "chat"
            self._dictating_target = None
            text = (ev.get("text") or "").strip()
            if not text and ev.get("reason") in ("no_speech", "too_short"):
                self.aviso.emit("No escuché voz clara para transcribir.")
            self.dictadoListo.emit(target, text)
        elif kind == "heard":
            text = (ev.get("text") or "").strip()
            if text:
                self.fraseEscuchada.emit(text, bool(ev.get("short", False)))
        elif kind == "error":
            self.aviso.emit(ev.get("message") or "Error en el módulo de voz.")

    def _on_finished(self, _code, _status):
        self._ready = False
        self._dictating_target = None
        if self._interactivo:
            self._interactivo = False
        self._estado = "idle"
        self.ttsEstado.emit(False)
        self.estadoCambiado.emit("idle")

    def cerrar(self):
        self._interactivo = False
        if self._proc and self._proc.state() != QProcess.ProcessState.NotRunning:
            try:
                self._proc.write(b'{"cmd":"quit"}\n')
                self._proc.waitForFinished(1200)
            except Exception:
                pass
            if self._proc.state() != QProcess.ProcessState.NotRunning:
                self._proc.kill()
                self._proc.waitForFinished(500)
        motor.restore_volumes()
