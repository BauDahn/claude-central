import json

from agent_station import buzon, ejecutor, uso, backends
from agent_station.backends import Resultado
from agent_station.config import Rol


def test_claude_ligero_sin_herramientas():
    cmd = backends._cmd_claude(Rol("charla", prompt="Sos breve.", opciones={"ligero": True, "model": "haiku"}), "hola", "claude")
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd and "--setting-sources" in cmd and "--no-session-persistence" in cmd
    assert "Sos breve." in cmd and cmd[-2:] == ["--", "hola"]
    assert "acceptEdits" not in cmd and "--allowedTools" not in cmd


def test_claude_normal_conserva_permisos():
    cmd = backends._cmd_claude(Rol("constructor", opciones={"escribir": True}), "hola", "claude")
    assert "acceptEdits" in cmd and "--allowedTools" in cmd


def preparar(tmp_path, monkeypatch, backend="eco"):
    monkeypatch.setenv("AGENT_STATION_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("AGENT_STATION_ROLES", str(tmp_path / "roles"))
    monkeypatch.setenv("AGENT_STATION_CONTEXTO", str(tmp_path / "ctx"))
    (tmp_path / "roles").mkdir(); (tmp_path / "ctx" / "mapas").mkdir(parents=True)
    (tmp_path / "roles" / "dev.md").write_text("Sos dev.")
    (tmp_path / "roles" / "dev.toml").write_text(f'backend = "{backend}"\nmodel = "m"\n')
    monkeypatch.setattr(ejecutor, "modelo_por_id", lambda i: {"id": i, "backend": backend})   # el modelo es obligatorio y sale del catálogo
    proyecto = tmp_path / "proy"; proyecto.mkdir()
    return proyecto


def test_inyecta_contexto_si_existe(tmp_path, monkeypatch):
    proy = preparar(tmp_path, monkeypatch)
    (tmp_path / "ctx" / "mapas" / "p.md").write_text("MAPA-DEL-PROYECTO")
    (tmp_path / "ctx" / "INDEX.md").write_text(f"mapas/p.md | {proy} | 2026-11-18 | ~10 | mapa\n")
    r = ejecutor.correr("dev", "hacé X", proy, ajustes={"model": "m"})
    assert "MAPA-DEL-PROYECTO" in r.texto and "hacé X" in r.texto
    assert not [m for m in buzon.leer() if m["a"] == "optimizador"]   # no pide contexto: ya había


def test_sin_contexto_pide_al_optimizador(tmp_path, monkeypatch):
    proy = preparar(tmp_path, monkeypatch)
    ejecutor.correr("dev", "hacé X", proy, ajustes={"model": "m"})
    assert any(m["a"] == "optimizador" and m["cuerpo"].startswith("PEDIR-CONTEXTO") for m in buzon.leer())


def test_respuesta_sin_envolver_y_registro(tmp_path, monkeypatch):
    proy = preparar(tmp_path, monkeypatch)
    monkeypatch.setitem(backends.BACKENDS, "eco", lambda rol, p, cwd: Resultado("hecho, listo!", 100, 40, 5, modelo="m"))
    r = ejecutor.correr("dev", "t", proy, ajustes={"model": "m"})
    assert r.texto == "hecho, listo!"
    assert uso.resumen(por="backend")["eco"]["input"] == 100


def test_carpeta_inexistente_no_deja_rastro(tmp_path, monkeypatch):
    import pytest
    preparar(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match="no existe"):
        ejecutor.correr("dev", "t", tmp_path / "nada", ajustes={"model": "m"})
    assert buzon.leer() == []


def test_backend_que_explota_queda_como_bloqueado(tmp_path, monkeypatch):
    proy = preparar(tmp_path, monkeypatch)
    def mal(rol, p, cwd): raise FileNotFoundError("x")
    monkeypatch.setitem(backends.BACKENDS, "eco", mal)
    r = ejecutor.correr("dev", "t", proy, ajustes={"model": "m"})
    assert r.texto.startswith("BLOQUEADO") and r.codigo == 1


def test_openai_sin_clave(tmp_path, monkeypatch):
    proy = preparar(tmp_path, monkeypatch, backend="openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = ejecutor.correr("dev", "t", proy, ajustes={"model": "m"})
    assert "falta la variable de entorno OPENAI_API_KEY" in r.texto and r.codigo == 2


def test_profundidad_maxima_y_ajustes(tmp_path, monkeypatch):
    import os
    from agent_station import backends, ejecutor
    from agent_station.backends import Resultado
    monkeypatch.setenv("AGENT_STATION_HOME", str(tmp_path / "h")); monkeypatch.setenv("AGENT_STATION_ROLES", str(tmp_path / "r"))
    visto = {}
    monkeypatch.setattr(ejecutor, "modelo_por_id", lambda i: {"id": i, "backend": "eco"})
    monkeypatch.setitem(backends.BACKENDS, "eco", lambda rol, pr, cwd, sesion=None: visto.update(rol=rol, prof=os.environ["AGENT_STATION_PROFUNDIDAD"], ag=os.environ["AGENT_STATION_AGENTE"]) or Resultado("LISTO: ok"))
    r = ejecutor.correr("constructor", "x", tmp_path, de="principal", ajustes={"backend": "eco", "model": "m7"})
    assert r.texto.startswith("LISTO") and visto["rol"].opciones["model"] == "m7" and visto["prof"] == "1" and visto["ag"] == "constructor"
    monkeypatch.setenv("AGENT_STATION_PROFUNDIDAD", "2")
    assert ejecutor.correr("constructor", "x", tmp_path, ajustes={"backend": "eco"}).texto.startswith("BLOQUEADO: profundidad")
