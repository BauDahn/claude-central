import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from central import backends, cli, ejecutor, eventos, nombres
from central.backends import Resultado


def test_pool_griegas_luego_mitos_y_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("CENTRAL_SESSION_START", "1000")

    esperado = list(nombres.GRIEGAS) + list(nombres.MITOS) + ["agente-1", "agente-2"]
    obtenidos = [nombres.asignar() for _ in range(len(esperado))]
    assert obtenidos == esperado


def test_sesion_actual_alias_y_siguiente_libre(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("CENTRAL_SESSION_START", "2000")

    # Eventos previos a la sesión actual no deben consumir nombres de esta sesión
    eventos.registrar("decision", ts=1500.0, id="old1", origen="sub", nombre="agy-000100", motor="agy", modelo="m")
    eventos.registrar("decision", ts=2010.0, id="d1", origen="sub", nombre="agy-001315", motor="agy", modelo="Gemini 4 Hydrogen (High)")
    eventos.registrar("decision", ts=2010.1, id="d2", origen="sub", nombre="codex-001316", motor="codex", modelo="gpt-6-luna")
    eventos.registrar("decision", ts=2020.0, id="d3", origen="sub", nombre="agy-001834", motor="agy", modelo="Gemini 4 Hydrogen (High)")

    aliases = nombres.alias_sesion(eventos.leer(), since=2000.0)
    assert aliases == {"agy-001315": "alfa", "codex-001316": "beta", "agy-001834": "gamma"}
    assert nombres.asignar() == "delta"
    assert nombres.asignar() == "epsilon"

    # Nueva sesión vuelve a empezar desde alfa
    monkeypatch.setenv("CENTRAL_SESSION_START", "3000")
    assert nombres.asignar() == "alfa"


def test_central_correr_y_seguir_conservan_nombre_griego(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("CENTRAL_ROLES", str(tmp_path / "roles"))
    monkeypatch.setenv("CENTRAL_CONTEXTO", str(tmp_path / "ctx"))
    monkeypatch.setenv("CENTRAL_SESSION_START", "1000")
    (tmp_path / "roles").mkdir()
    (tmp_path / "ctx").mkdir()
    (tmp_path / "roles" / "constructor.md").write_text("Sos constructor.")
    monkeypatch.setattr(ejecutor, "modelo_por_id", lambda i: {"id": i, "backend": "eco"})

    vistos = []
    def fake_backend(rol, prompt, cwd, sesion=None):
        vistos.append((rol.nombre, os.environ.get("CENTRAL_AGENTE"), sesion))
        return Resultado("LISTO: ok", entrada=10, cache=2, salida=5, modelo="m-test", hilo="hilo-1")

    monkeypatch.setitem(backends.BACKENDS, "eco", fake_backend)
    proy = tmp_path / "proy"
    proy.mkdir()

    with pytest.raises(SystemExit) as exc:
        cli.main(["correr", "constructor", "hacer A", "-C", str(proy), "--backend", "eco", "--modelo", "m-test", "--aprobado"])
    assert exc.value.code == 0
    err = capsys.readouterr().err
    assert "[central] alfa (constructor)" in err

    with pytest.raises(SystemExit) as exc2:
        cli.main(["seguir", "hilo-1", "continuar B"])
    assert exc2.value.code == 0
    err2 = capsys.readouterr().err
    assert "[central] alfa ·" in err2

    assert vistos == [
        ("constructor", "alfa", None),
        ("constructor", "alfa", {"hilo": "hilo-1"}),
    ]
    evs = list(eventos.leer())
    assert any(e["tipo"] == "lanzamiento" and e.get("nombre") == "alfa" and e.get("funcion") == "constructor" for e in evs)
    assert any(e["tipo"] == "uso" and e.get("agente") == "alfa" for e in evs)
    assert any(e["tipo"] == "decision" and e.get("nombre") == "alfa" and e.get("funcion") == "constructor" for e in evs)


def test_sublog_y_sub_lista_aceptan_griego_e_id_viejo(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    ag = tmp_path / "agentes"
    subs = ag / "estado" / "subs"
    subs.mkdir(parents=True)
    ch = tmp_path / "central"
    ch.mkdir()

    env = dict(
        os.environ,
        AGENTES_HOME=str(ag),
        CENTRAL_HOME=str(ch),
        CENTRAL_SESSION_START="1000",
        PATH=f"{Path.home()}/.local/bin:{os.environ.get('PATH', '')}",
    )
    (ch / "eventos.jsonl").write_text(
        json.dumps({"ts": 1010.0, "tipo": "decision", "id": "d1", "origen": "sub", "nombre": "agy-001315", "motor": "agy", "modelo": "Gemini 4 Hydrogen (High)"}) + "\n"
        + json.dumps({"ts": 1011.0, "tipo": "decision", "id": "d2", "origen": "sub", "nombre": "codex-001316", "motor": "codex", "modelo": "gpt-6-luna"}) + "\n"
    )
    (ag / "estado" / "subs.json").write_text(json.dumps({
        "agy-001315": {"motor": "agy", "modelo": "Gemini 4 Hydrogen (High)", "dir": str(tmp_path), "ts": 1010},
        "codex-001316": {"motor": "codex", "modelo": "gpt-6-luna", "dir": str(tmp_path), "ts": 1011},
    }))
    (subs / "agy-001315.log").write_text("linea cruda de agy\n")
    (subs / "codex-001316.log").write_text("linea cruda de codex\n")
    (subs / "bus.log").write_text("00:13:16 [agy-001315] hola alfa\n00:13:17 [codex-001316] hola beta\n")

    sub_bin = str(repo / "agentes" / "bin" / "sub")
    sublog_bin = str(repo / "agentes" / "bin" / "sublog")

    r_crudo_g = subprocess.run([sublog_bin, "--crudo", "alfa"], env=env, capture_output=True, text=True, check=True)
    assert "linea cruda de agy" in r_crudo_g.stdout

    r_crudo_old = subprocess.run([sublog_bin, "--crudo", "agy-001315"], env=env, capture_output=True, text=True, check=True)
    assert "linea cruda de agy" in r_crudo_old.stdout

    r_bus = subprocess.run([sublog_bin], env=env, capture_output=True, text=True, check=True)
    assert "[alfa] hola alfa" in r_bus.stdout and "[beta] hola beta" in r_bus.stdout

    r_lista_g = subprocess.run([sub_bin, "--lista", "beta"], env=env, capture_output=True, text=True, check=True)
    assert "beta (codex-001316)" in r_lista_g.stdout and "agy-001315" not in r_lista_g.stdout

    r_lista_old = subprocess.run([sub_bin, "--lista", "agy-001315"], env=env, capture_output=True, text=True, check=True)
    assert "alfa (agy-001315)" in r_lista_old.stdout and "codex-001316" not in r_lista_old.stdout
