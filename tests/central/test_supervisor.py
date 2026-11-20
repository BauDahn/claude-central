import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from central import cli, eventos, supervisor


def _preparar_entorno(tmp_path: Path, monkeypatch, inicio_sesion: float):
    ag = tmp_path / "agentes"
    subs = ag / "estado" / "subs"
    subs.mkdir(parents=True)
    ch = tmp_path / "central"
    ch.mkdir()
    monkeypatch.setenv("AGENTES_HOME", str(ag))
    monkeypatch.setenv("CENTRAL_HOME", str(ch))
    monkeypatch.setenv("CENTRAL_SESSION_START", str(inicio_sesion))
    return ag, subs, ch


def test_caso_real_beta_codex_inactivo_y_alfa_activo(tmp_path, monkeypatch):
    # Simula lanzamiento a las 00:13:16 y supervisión 62 minutos después (01:15:16)
    base = datetime(2026, 11, 20, 0, 13, 16).timestamp()
    ahora = base + 62 * 60
    ag, subs, _ = _preparar_entorno(tmp_path, monkeypatch, base - 60)

    eventos.registrar("decision", ts=base, id="d1", origen="sub", nombre="agy-001315", motor="agy", modelo="Gemini")
    eventos.registrar("decision", ts=base + 1, id="d2", origen="sub", nombre="codex-001316", motor="codex", modelo="gpt-6-luna")
    eventos.registrar("decision", ts=base + 2, id="d3", origen="sub", nombre="agy-001834", motor="agy", modelo="Gemini")

    (ag / "estado" / "subs.json").write_text(json.dumps({
        "agy-001315": {"motor": "agy", "modelo": "Gemini", "dir": "/tmp", "ts": int(base)},
        "codex-001316": {"motor": "codex", "modelo": "gpt-6-luna", "dir": "/tmp", "ts": int(base + 1)},
        "agy-001834": {"motor": "agy", "modelo": "Gemini", "dir": "/tmp", "ts": int(base + 2)},
    }))

    (subs / "bus.log").write_text(
        "00:13:16 [agy-001315] inicia (agy Gemini) en /tmp\n"
        "00:13:17 [codex-001316] inicia (codex gpt-6-luna) en /tmp\n"
        "00:13:18 [agy-001834] inicia (agy Gemini) en /tmp\n"
        "00:28:00 [agy-001315] [cp270-agy] Iniciando entrenamiento Gemma 3 270M LoRA\n"
        "00:29:18 [agy-001834] [grafo-agy] Listo: visor arreglado en src/central/gui/visor.py, 34/34 pytest ok\n"
        "00:32:14 [agy-001834] terminó (código 0)\n"
    )

    # alfa: log recién actualizado (entrenando)
    log_alfa = subs / "agy-001315.log"
    log_alfa.write_text("Epoch 1/3\nloss=0.42 step=200\n")
    os.utime(log_alfa, (ahora - 15, ahora - 15))

    # beta (Codex): escribió resultado en su TUI a los 2m y quedó en prompt quieto 60m
    log_beta = subs / "codex-001316.log"
    log_beta.write_text(
        "\x1b[2J\x1b[1;1H• Creé datos/cp_local.jsonl con 264 problemas y 264 IDs únicos.\r"
        "Intenté reportar los hitos con reportar, pero el sandbox impidió escribir en el log.\r"
        "Worked for 2m 35s • 12:15 AM\r"
        "› Ask Codex to do anything\r"
        "← for agents · ? for shortcuts\r"
    )
    os.utime(log_beta, (base + 155, base + 155))

    # gamma: terminó bien y reportó
    log_gamma = subs / "agy-001834.log"
    log_gamma.write_text(
        "Arreglo aplicado en visor.py y tests en verde (34 passed).\n"
        'Script terminado en 2026-11-20 00:32:14+01:00 [CÓDIGO_SALIDA_ORDEN="0"]\n'
    )

    procs = {
        "agy-001315": {"vivo": True, "cpu_pct": 24.5, "pids": [101, 102]},
        "codex-001316": {"vivo": True, "cpu_pct": 0.0, "pids": [201, 202]},
    }
    estados = {
        e.nombre: e
        for e in supervisor.inspeccionar(ag, ahora=ahora, procesos_fn=lambda: procs)
    }

    assert estados["agy-001315"].alias == "alfa"
    assert estados["agy-001315"].alertas == []

    assert estados["agy-001834"].alias == "gamma"
    assert estados["agy-001834"].alertas == []

    beta = estados["codex-001316"]
    assert beta.alias == "beta"
    assert [a["tipo"] for a in beta.alertas] == ["inactivo"]
    assert "CPU 0.0%" in beta.alertas[0]["mensaje"]


def test_termino_sin_reportar_y_resultado_generico(tmp_path, monkeypatch):
    base = datetime(2026, 11, 20, 10, 0, 0).timestamp()
    ahora = base + 300
    ag, subs, _ = _preparar_entorno(tmp_path, monkeypatch, base - 60)

    (ag / "estado" / "subs.json").write_text(json.dumps({
        "sub-mudo": {"motor": "codex", "modelo": "gpt-6-luna", "dir": "/tmp", "ts": int(base)},
        "sub-vacio": {"motor": "agy", "modelo": "Gemini", "dir": "/tmp", "ts": int(base + 5)},
        "sub-generico": {"motor": "claude", "modelo": "haiku", "dir": "/tmp", "ts": int(base + 10)},
    }))

    (subs / "bus.log").write_text(
        "10:00:00 [sub-mudo] inicia (codex gpt-6-luna) en /tmp\n"
        "10:02:00 [sub-mudo] terminó (código 0)\n"
        "10:00:05 [sub-vacio] inicia (agy Gemini) en /tmp\n"
        "10:01:00 [sub-vacio] terminó (código 1)\n"
        "10:00:10 [sub-generico] inicia (claude haiku) en /tmp\n"
        "10:01:30 [sub-generico] Listo.\n"
        "10:01:31 [sub-generico] terminó (código 0)\n"
    )

    (subs / "sub-mudo.log").write_text(
        "Analicé 14 archivos en src/central/ y documenté los cambios en docs/notas.md con detalle completo.\n"
        "Se verificaron 12 tests unitarios sin errores.\n"
        'Script terminado en 2026-11-20 10:02:00+01:00 [CÓDIGO_SALIDA_ORDEN="0"]\n'
    )
    (subs / "sub-vacio.log").write_text(
        "hola\n"
        'Script terminado en 2026-11-20 10:01:00+01:00 [CÓDIGO_SALIDA_ORDEN="1"]\n'
    )
    (subs / "sub-generico.log").write_text(
        "Listo\n"
        'Script terminado en 2026-11-20 10:01:31+01:00 [CÓDIGO_SALIDA_ORDEN="0"]\n'
    )

    estados = {
        e.nombre: e
        for e in supervisor.inspeccionar(ag, ahora=ahora, procesos_fn=lambda: {})
    }

    assert [a["tipo"] for a in estados["sub-mudo"].alertas] == ["termino_sin_reportar"]
    assert {a["tipo"] for a in estados["sub-vacio"].alertas} == {"termino_sin_reportar", "resultado_generico"}
    assert [a["tipo"] for a in estados["sub-generico"].alertas] == ["resultado_generico"]

    emitidas = supervisor.notificar_alertas(list(estados.values()), ag, ahora=ahora)
    assert len(emitidas) == 4
    bus_txt = (subs / "bus.log").read_text()
    avisos_txt = (ag / "estado" / "avisos.log").read_text()
    assert "[supervisor] ALERTA [termino_sin_reportar] sub-mudo" in bus_txt
    assert "[supervisor] ALERTA [resultado_generico] sub-generico" in avisos_txt

    # Segunda corrida sin --repetir no duplica alertas ya emitidas
    assert supervisor.notificar_alertas(list(estados.values()), ag, ahora=ahora + 60) == []


def test_cruce_medianoche_y_cli_supervisar_solo_ver(tmp_path, monkeypatch, capsys):
    # Lanzado 23:42 del día 19, inspeccionado 00:50 del día 20
    inicio = datetime(2026, 11, 19, 23, 42, 0).timestamp()
    ahora = datetime(2026, 11, 20, 0, 50, 0).timestamp()
    ag, subs, _ = _preparar_entorno(tmp_path, monkeypatch, inicio - 60)

    (ag / "estado" / "subs.json").write_text(json.dumps({
        "nocturno": {"motor": "agy", "modelo": "Gemini", "dir": "/tmp", "ts": int(inicio)},
    }))
    (subs / "bus.log").write_text(
        "23:42:05 [nocturno] inicia (agy Gemini) en /tmp\n"
        "23:49:10 [nocturno] Listo: guardé 7 ideas en IDEAS.md con métricas completas.\n"
    )
    (subs / "nocturno.log").write_text(
        "Exploración completada: 7 ideas evaluadas y guardadas en IDEAS.md con tablas comparativas.\n"
        "Se validó estructura sin errores.\n"
        'Script terminado en 2026-11-19 23:49:12+01:00 [CÓDIGO_SALIDA_ORDEN="0"]\n'
    )

    monkeypatch.setattr(supervisor, "leer_procesos_ps", lambda: {})
    monkeypatch.setattr(time, "time", lambda: ahora)

    with pytest.raises(SystemExit) as exc:
        cli.main(["supervisar", "--desde", "24h", "--solo-ver", "--json"])
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["subagentes"]) == 1
    assert out["subagentes"][0]["reportes"] == 1
    assert out["subagentes"][0]["reporto_fin"] is True
    assert out["subagentes"][0]["alertas"] == []
    assert out["emitidas"] == []
    assert not (subs / "supervisor_estado.json").exists()
