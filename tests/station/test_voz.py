import json
import os
from pathlib import Path

from agent_station import cli, lanzar
from agent_station.voz import cli_voz, motor


def test_extraer_y_quitar_voz():
    raw = "<voz>Done fixing the graph.</voz>\n\nAcá está el detalle."
    assert motor.extraer_voz(raw) == "Done fixing the graph."
    assert motor.quitar_voz(raw) == "Acá está el detalle."
    # Etiqueta abierta sin cerrar mientras streamea
    partial = "<voz>Still thinking about"
    assert motor.extraer_voz(partial) is None
    assert motor.quitar_voz(partial) == ""


def test_limpiar_y_dividir_frases():
    txt = "First sentence here. And a very long second sentence that has a comma, right in the middle to split early! ```code``` `x`"
    cleaned = motor.limpiar_para_tts(txt)
    assert "```" not in cleaned and "`" not in cleaned
    parts = motor.dividir_frases(cleaned)
    assert len(parts) >= 3
    assert parts[0] == "First sentence here."


def test_comandos_modos_y_prefijos():
    assert motor.match_command("enviar") == "send"
    assert motor.match_command("pausa por favor") == "pause"
    assert motor.match_command("cállate") == "stop_tts"
    assert motor.match_command("modo manual") == "manual"
    assert motor.match_command("explicame esta función") is None

    assert motor.match_mode("pasemos a modo interactivo") == "interactive"
    assert motor.match_mode("salir del modo interactivo") == "normal"
    assert motor.match_mode("modo normal") == "normal"
    assert motor.match_mode("modo de compilación") is None

    ag, rest = motor.match_agent_prefix("constructor, arreglá el mapa", ["principal", "constructor", "revisor"])
    assert ag == "constructor" and rest == "arreglá el mapa"
    ag2, rest2 = motor.match_agent_prefix("explicame qué hace esto", ["principal", "constructor", "revisor"])
    assert ag2 is None and rest2 == "explicame qué hace esto"


def test_fix_rioplatense():
    assert motor.fix_rioplatense("hay un fasho en el test") == "hay un fallo en el test"
    assert motor.fix_rioplatense("Fashos encontrados") == "Fallos encontrados"


def test_lanzar_con_voz_e_interactivo(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATION_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("AGENT_STATION_CONTEXTO", str(tmp_path / "ctx"))
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/claude" if n == "claude" else "/usr/bin/station")
    cmd = lanzar.comando(tmp_path, ["--voz", "--interactivo", "--model", "opus"])
    assert "--voz" not in cmd and "--interactivo" not in cmd
    assert cmd[-2:] == ["--model", "opus"]
    assert "--settings" in cmd
    sistema = Path(cmd[cmd.index("--append-system-prompt-file") + 1]).read_text()
    assert "<voz>" in sistema and "MODO INTERACTIVO" in sistema
    hooks_json = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text())
    assert "Stop" in hooks_json["hooks"] and "UserPromptSubmit" in hooks_json["hooks"]


def test_hook_stop_inyecta_interactivo(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_STATION_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("AGENT_STATION_INTERACTIVO", "1")
    cli_voz.cmd_hook("stop")
    out = capsys.readouterr().out
    assert "MODO INTERACTIVO" in out


def test_already_spoken_dedup(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATION_HOME", str(tmp_path / "h"))
    assert motor.already_spoken("s1", "Hello there.") is False
    assert motor.already_spoken("s1", "Hello there.") is True
    assert motor.already_spoken("s1", "New message.") is False
