"""Subcomandos CLI `station voz` y soporte de hooks de Claude Code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from agent_station.voz import motor


def _run_worker(args: list[str], capture: bool = False) -> subprocess.CompletedProcess | None:
    py = motor.python_voz()
    if not py:
        print("station voz: no encontré Python con kokoro-onnx y faster-whisper.", file=sys.stderr)
        return None
    worker = str(Path(__file__).with_name("worker.py"))
    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = f"{src_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src_root
    return subprocess.run([py, worker, *args], env=env, capture_output=capture, text=True)


def _speak_detached(text: str, voice: str = "af_heart", speed: float = 1.05, force: bool = False):
    clean = motor.limpiar_para_tts(text)
    if not clean:
        return
    if not force and motor.tiene_espanol(clean):
        return
    py = motor.python_voz()
    if not py:
        return
    motor.stop_detached_pid()
    pid = os.fork()
    if pid != 0:
        return
    os.setsid()
    pf = motor.voz_home() / "playing.pid"
    pf.write_text(str(os.getpid()))
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    worker = str(Path(__file__).with_name("worker.py"))
    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = f"{src_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src_root
    try:
        subprocess.run(
            [py, worker, "--oneshot", "speak", "--text", clean, "--voice", voice, "--speed", str(speed),
             *(["--force"] if force else [])],
            env=env, check=False,
        )
    finally:
        motor.restore_volumes()
        pf.unlink(missing_ok=True)
        os._exit(0)


def _last_assistant_text(data: dict) -> str:
    msg = data.get("last_assistant_message")
    if isinstance(msg, str) and msg:
        return msg
    path = data.get("transcript_path")
    if not path:
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                m = e.get("message") or {}
                if e.get("type") == "assistant" or m.get("role") == "assistant":
                    c = m.get("content")
                    if isinstance(c, str):
                        last = c
                    elif isinstance(c, list):
                        t = "".join(b.get("text", "") for b in c if b.get("type") == "text")
                        if t:
                            last = t
    except OSError:
        pass
    return last


def cmd_hook(mode: str):
    busy = motor.voz_home() / "busy"
    if mode == "register":
        return
    if mode == "stop":
        busy.touch()
        motor.stop_detached_pid()
        if os.environ.get("AGENT_STATION_INTERACTIVO") == "1":
            print(motor.instrucciones_interactivo())
        return
    if os.environ.get("AGENT_STATION_VOZ") != "1":
        if mode != "early":
            busy.unlink(missing_ok=True)
        return
    early = mode == "early"
    if not early:
        busy.unlink(missing_ok=True)
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if data.get("stop_hook_active") and not early:
        return
    text = _last_assistant_text({"transcript_path": data.get("transcript_path")} if early else data)
    voz = motor.extraer_voz(text)
    if voz and not motor.already_spoken(data.get("session_id", "station"), voz):
        _speak_detached(voz)


def cmd_dictar(lang: str = "es", model: str = "small", escribir: bool = False):
    py = motor.python_voz()
    if not py:
        sys.exit("station voz: falta entorno con kokoro-onnx y faster-whisper.")
    worker = str(Path(__file__).with_name("worker.py"))
    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = f"{src_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src_root
    r = subprocess.run(
        [py, worker, "--oneshot", "dictate", "--lang-stt", lang, "--model-stt", model],
        env=env, capture_output=True, text=True,
    )
    text = ""
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "dictate_result":
            text = (ev.get("text") or "").strip()
    if not text:
        return
    if escribir and shutil.which("wtype"):
        subprocess.run(["wtype", "--", text], check=False)
    else:
        print(text)


def cmd_escuchar(lang: str = "es", model: str = "small", dry: bool = False):
    py = motor.python_voz()
    if not py:
        sys.exit("station voz: falta entorno con kokoro-onnx y faster-whisper.")
    worker = str(Path(__file__).with_name("worker.py"))
    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = f"{src_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src_root
    proc = subprocess.Popen(
        [py, worker, "--rpc"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps({"cmd": "config", "lang_stt": lang, "model_stt": model}) + "\n")
    proc.stdin.write(json.dumps({"cmd": "listen_start"}) + "\n")
    proc.stdin.flush()
    print("🎙 Escuchando con Whisper local (Ctrl+C para salir)…", flush=True)
    try:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") == "heard":
                txt = ev.get("text", "")
                print(f"🗣  {txt}  [{ev.get('dt', 0)}s]", flush=True)
                if not dry and shutil.which("wtype"):
                    subprocess.run(["wtype", "--", txt], check=False)
            elif ev.get("event") == "error":
                print(f"error: {ev.get('message')}", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.stdin.write('{"cmd":"quit"}\n')
            proc.stdin.flush()
        except Exception:
            pass
        proc.terminate()


def hooks_settings_path() -> Path:
    """Genera un archivo de settings de Claude Code con los hooks de `station voz hook`."""
    p = motor.voz_home() / "claude-hooks.json"
    exe = shutil.which("station") or sys.executable
    base = f'"{exe}" voz hook' if exe.endswith("station") else f'"{exe}" -m agent_station.cli voz hook'
    data = {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"{base} stop", "timeout": 5}]}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": f"{base} early", "timeout": 5, "async": True}]}],
            "PostToolUse": [{"hooks": [{"type": "command", "command": f"{base} early", "timeout": 5, "async": True}]}],
            "Stop": [{"hooks": [{"type": "command", "command": f"{base} speak", "timeout": 10}]}],
        }
    }
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p
