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
