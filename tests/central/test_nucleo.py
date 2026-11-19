import json, time

from central import buzon, eventos, importar, uso


def test_buzon_y_uso(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path))
    buzon.enviar("a", "optimizador", "PEDIR-CONTEXTO: mapa | fuente: x")
    buzon.enviar("optimizador", "a", "CONTEXTO-LISTO: m.md (~1k tokens)")
    assert [m["de"] for m in buzon.leer("a")] == ["a", "optimizador"]
    assert buzon.prefijo("CONTEXTO-LISTO: x") == "CONTEXTO-LISTO"
    uso.registrar("x", "api-a", "m1", entrada=10, salida=2)
    uso.registrar("y", "api-b", "m2", entrada=5)
    r = uso.resumen(por="backend")
    assert r["api-a"]["input"] == 10 and r["api-b"]["tareas"] == 1


def test_tokens_declarados():
    assert buzon.tokens_declarados("~1.1k") == 1100
    assert buzon.tokens_declarados("32,8k") == 32800
    assert buzon.tokens_declarados("hola") is None


def test_reiniciar_uso_conserva_bitacora_y_descarta_consumo_anterior(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path))
    uso.registrar("x", "api-a", "m1", entrada=10, salida=2)
    uso.reiniciar()
    assert uso.resumen(por="backend") == {}
    assert len(list(eventos.leer(tipo="uso"))) == 1
    assert len(list(eventos.leer(tipo="uso_reset"))) == 1


def test_importar_idempotente(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path / "central"))
    ag = tmp_path / "agentes"; (ag / "estado").mkdir(parents=True)
    (ag / "estado" / "codex.jsonl").write_text(json.dumps(
        {"ts": 1, "rol": "backend", "modelo": "m", "hilo": "h", "tarea": "t", "uso": {"input": 7, "cached": 1, "output": 2, "reasoning": 1},
         "seg": 3, "resultado": "LISTO: x", "proyecto": "p"}) + "\n")
    assert importar.desde_central(ag, tmp_path / "noclaude") == {"uso": 1, "msg": 0}
    assert importar.desde_central(ag, tmp_path / "noclaude") == {"uso": 0, "msg": 0}
    assert uso.resumen()["codex"]["output"] == 3
