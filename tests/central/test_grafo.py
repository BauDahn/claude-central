import pytest

PyQt6 = pytest.importorskip("PyQt6")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_fit_node_label_no_corta_nombres(qapp):
    from central.gui.tabs.grafo import fit_node_label, GrafoWidget

    for name in ("principal", "constructor", "optimizador", "orquestador", "contextualizador", "gemini-constructor"):
        radius, pt, label = fit_node_label(name)
        assert radius >= 40
        assert pt >= 7
        assert label.replace("\n", "").replace("-\n", "-").replace("-", "") == name.replace("-", "")

    g = GrafoWidget()
    g.resize(800, 560)
    g.set_events([
        {"ts": 1000.0, "tipo": "msg", "de": "principal", "a": "constructor", "cuerpo": "hola"},
        {"ts": 1001.0, "tipo": "msg", "de": "constructor", "a": "optimizador", "cuerpo": "ctx"},
    ])
    pos = g._positions()
    assert set(pos.keys()) == {"principal", "constructor", "optimizador"}
    for name, pt in pos.items():
        r = g._radii[name]
        assert r < pt.x() < g.width() - r
        assert r < pt.y() < g.height() - r


def test_bitacora_oculta_list_shadow_en_mapa(qapp, tmp_path, monkeypatch):
    from central.gui.tabs.bitacora import BitacoraTab

    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path))
    tab = BitacoraTab()
    tab.show()
    qapp.processEvents()
    assert tab.list_shadow.isVisible()
    assert not tab.map_split.isVisible()

    tab._set_mode("Mapa")
    qapp.processEvents()
    assert not tab.list_shadow.isVisible()
    assert tab.map_split.isVisible()
    assert tab.filtros.buttons["Todos"].parent() is tab.filtros._inner
    tab.reader.stop()
    tab.close()


def test_grafo_decisiones_sub_y_sin_superposicion(qapp):
    import math
    from central.gui.tabs.grafo import GrafoWidget

    g = GrafoWidget()
    g.resize(720, 600)
    g.set_events([
        {"ts": 1000.0, "tipo": "decision", "id": "d1", "origen": "sub", "nombre": "agy-001315", "motor": "agy", "modelo": "Gemini 4 Hydrogen (High)", "motivo": "test"},
        {"ts": 1001.0, "tipo": "decision", "id": "d2", "origen": "sub", "nombre": "codex-001316", "motor": "codex", "modelo": "gpt-6-luna", "motivo": "test2"},
        {"ts": 1005.0, "tipo": "decision_resultado", "id": "d2", "estado": "terminado", "seg": 4.0, "tokens": 100},
    ])
    assert set(g.nodes) == {"agy-001315", "central", "codex-001316"}
    assert g.statuses["agy-001315"] == "Corriendo"
    assert g.statuses["codex-001316"] == "Terminado"
    assert {(a, b) for a, b, _ in g.edges} == {("central", "agy-001315"), ("central", "codex-001316")}

    # 30 nodos en modo historial no deben superponerse
    many = [{"ts": 1000.0 + i, "tipo": "msg", "de": f"agente-{i:02d}", "a": f"agente-{(i + 1) % 30:02d}", "cuerpo": "x"} for i in range(30)]
    g.set_events(many)
    pos = g._positions()
    assert len(pos) == 30
    names = list(pos)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ni, nj = names[i], names[j]
            dist = math.hypot(pos[ni].x() - pos[nj].x(), pos[ni].y() - pos[nj].y())
            assert dist >= g._radii[ni] + g._radii[nj] + 4
    assert not g.grab().isNull()


def test_bitacora_filtra_sesion_actual_y_historial(qapp, tmp_path, monkeypatch):
    import json, time
    from datetime import datetime, timezone
    from central.gui.tabs.bitacora import BitacoraTab

    now = time.time()
    t0 = now - 5400  # sesión arrancó hace 1.5h
    t0_iso = datetime.fromtimestamp(t0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    proj = tmp_path / "claude" / "projects" / "-home-baudahn-central"
    proj.mkdir(parents=True)
    (proj / "sess.jsonl").write_text(json.dumps({"type": "user", "timestamp": t0_iso}) + "\n")

    ch = tmp_path / "central"
    ch.mkdir()
    monkeypatch.setenv("CENTRAL_HOME", str(ch))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))

    tab = BitacoraTab()
    try:
        tab.resize(900, 700)
        tab.show()
        tab._set_mode("Mapa")
        tab._apply([
            {"ts": t0 - 3600, "tipo": "msg", "de": "alpha", "a": "beta", "cuerpo": "viejo"},
            {"ts": t0 + 60, "tipo": "decision", "id": "s1", "origen": "sub", "nombre": "agy-viejo-en-sesion", "motor": "agy", "modelo": "m1"},
            {"ts": now - 60, "tipo": "decision", "id": "s2", "origen": "sub", "nombre": "codex-reciente", "motor": "codex", "modelo": "m2"},
        ])
        qapp.processEvents()

        assert set(tab.graph.nodes) == {"agy-viejo-en-sesion", "central", "codex-reciente"}
        assert set(tab.filtros.buttons) == {"Todos", "agy-viejo-en-sesion", "codex-reciente"}
        for b in tab.filtros.buttons.values():
            assert b.x() + b.width() <= tab.filtros.viewport().width() + 1

        # Filtro 1h dentro de sesión actual oculta el de hace 1.5h y deja el reciente
        tab._filters(period="1h")
        assert set(tab.graph.nodes) == {"central", "codex-reciente"}

        # Volver a todo + activar Ver todo / historial muestra los viejos y luego vuelve a ocultarlos
        tab._filters(period="todo")
        tab.historial.click()
        qapp.processEvents()
        assert {"alpha", "beta", "agy-viejo-en-sesion", "codex-reciente"}.issubset(set(tab.graph.nodes))
        assert "alpha" in tab.filtros.buttons

        tab.historial.click()
        qapp.processEvents()
        assert set(tab.graph.nodes) == {"agy-viejo-en-sesion", "central", "codex-reciente"}

        # Vista Lista sigue mostrando todo
        tab._set_mode("Lista")
        qapp.processEvents()
        assert tab.model.rowCount() == 3
    finally:
        tab.reader.stop()
        tab.close()


def test_visor_alias_sesion_y_estabilidad_en_filtros(qapp, tmp_path, monkeypatch):
    import json, time
    from datetime import datetime, timezone
    from central.gui.tabs.bitacora import BitacoraTab

    now = time.time()
    t0 = now - 5400
    t0_iso = datetime.fromtimestamp(t0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    proj = tmp_path / "claude" / "projects" / "-home-baudahn-central"
    proj.mkdir(parents=True)
    (proj / "sess.jsonl").write_text(json.dumps({"type": "user", "timestamp": t0_iso}) + "\n")

    ch = tmp_path / "central"
    ch.mkdir()
    monkeypatch.setenv("CENTRAL_HOME", str(ch))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))
    monkeypatch.delenv("CENTRAL_SESSION_START", raising=False)

    tab = BitacoraTab()
    try:
        tab.resize(900, 700)
        tab.show()
        tab._set_mode("Mapa")
        tab._apply([
            {"ts": t0 + 60, "tipo": "decision", "id": "d1", "origen": "sub", "nombre": "agy-001315", "motor": "agy", "modelo": "Gemini 4 Hydrogen (High)"},
            {"ts": now - 60, "tipo": "decision", "id": "d2", "origen": "sub", "nombre": "codex-001316", "motor": "codex", "modelo": "gpt-6-luna"},
        ])
        qapp.processEvents()

        assert set(tab.graph.nodes) == {"alfa", "beta", "central"}
        assert set(tab.filtros.buttons) == {"Todos", "alfa", "beta"}
        assert tab.graph.models["alfa"] == "Gemini 4 Hydrogen (High)"
        assert tab.graph.models["beta"] == "gpt-6-luna"

        pos = tab.graph._positions()
        tab.graph._show_details([tab.graph.events[0]], "beta · últimos mensajes")
        assert "central → beta" in tab.detail.toPlainText()
        assert pos

        # Con filtro 1h, alfa (1.5h atrás) se oculta pero beta sigue siendo beta (no se renumera a alfa)
        tab._filters(period="1h")
        qapp.processEvents()
        assert set(tab.graph.nodes) == {"beta", "central"}
        assert set(tab.filtros.buttons) == {"Todos", "beta"}
    finally:
        tab.reader.stop()
        tab.close()
