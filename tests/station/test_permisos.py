import time

import pytest

from agent_station import backends, cli, eventos, permisos
from agent_station.config import Rol


@pytest.fixture(autouse=True)
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATION_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("AGENT_STATION_ROLES", str(tmp_path / "roles"))
    monkeypatch.setenv("AGENT_STATION_PERMISOS", str(tmp_path / "permisos.toml"))
    monkeypatch.delenv("AGENT_STATION_PROFUNDIDAD", raising=False)
    monkeypatch.delenv("AGENT_STATION_AGENTE", raising=False)
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles" / "gemini.md").write_text("g")


def test_defectos_estrictos():
    assert not permisos.perfil_de("gemini").edita
    assert not permisos.perfil_de("rol-desconocido").edita           # sin perfil -> general (lectura)
    c = permisos.perfil_de("constructor")
    assert c.edita and "Bash(git push:*)" in c.denegar and "Bash(rm -rf:*)" in c.denegar
    assert permisos.perfil_de("gemini-constructor").rutas == ["src/", "tests/"]


def test_perfil_del_usuario_reemplaza(tmp_path):
    (tmp_path / "permisos.toml").write_text('[gemini]\nmodo = "editar"\n')
    assert permisos.perfil_de("gemini").edita
    assert permisos.perfil_de("constructor").edita and not permisos.perfil_de("general").edita


def test_escribir_solo_baja_nunca_sube():
    assert not permisos.perfil_de("constructor", escribir=False).edita
    assert not permisos.perfil_de("gemini", escribir=True).edita


def test_claude_traduce_perfil():
    cmd = backends._cmd_claude(Rol("gemini"), "x", "claude")
    assert "--permission-mode" not in cmd and {"Edit", "Write"} <= set(cmd[cmd.index("--disallowedTools") + 1].split(","))
    cmd = backends._cmd_claude(Rol("constructor"), "x", "claude")
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert "Bash(pytest:*)" in cmd[cmd.index("--allowedTools") + 1].split(",")
    assert "Bash(git push:*)" in cmd[cmd.index("--disallowedTools") + 1].split(",")
    cmd = backends._cmd_claude(Rol("gemini-constructor"), "x", "claude")
    assert "--permission-mode" not in cmd and "Edit(src/**)" in cmd[cmd.index("--allowedTools") + 1].split(",")


def test_dar_vence_y_quitar_y_bitacora():
    permisos.dar("gemini", "editar", "1h")
    assert permisos.perfil_de("gemini").edita
    permisos.dar("gemini", "Bash(pytest:*)", "30m")
    assert "Bash(pytest:*)" in permisos.perfil_de("gemini").permitir
    assert permisos.quitar("gemini", "editar") == 1 and not permisos.perfil_de("gemini").edita
    ev = [e for e in eventos.leer(tipo="permiso")]
    assert [e["accion"] for e in ev] == ["dar", "dar", "quitar"]
    assert "[permiso]" in cli.fmt(ev[0], False)


def test_concesion_vencida_no_aplica():
    c = permisos.dar("gemini", "editar", "1m")
    permisos._guardar([{**c, "hasta": time.time() - 1}])
    assert not permisos.perfil_de("gemini").edita


def test_principal_no_puede_darse_permisos():
    with pytest.raises(SystemExit): permisos.dar("principal", "editar")
    with pytest.raises(SystemExit): permisos.quitar("principal", "editar")
    assert not list(eventos.leer(tipo="permiso"))


def test_subagente_no_puede_dar(monkeypatch):
    monkeypatch.setenv("AGENT_STATION_PROFUNDIDAD", "1")
    with pytest.raises(SystemExit): permisos.dar("gemini", "editar")


def test_duracion_invalida():
    with pytest.raises(SystemExit): permisos.parsear_hasta("mañana")
    assert permisos.parsear_hasta("siempre") is None


def test_comandos_del_principal_editables(tmp_path):
    ok, _ = permisos.reglas_principal()
    assert {"Bash(python:*)", "Bash(pytest:*)", "Bash(agy:*)", "Bash(station correr:*)"} <= set(ok)
    (tmp_path / "permisos.toml").write_text('[principal]\ncomandos = ["pytest"]\ndenegar = ["Bash(rm:*)"]\n')
    assert permisos.reglas_principal() == (["Bash(pytest:*)"], ["Bash(rm:*)"])


def test_cli_permisos(capsys):
    cli.main(["permisos", "dar", "gemini", "editar", "--hasta", "2h"])
    cli.main(["permisos", "ver", "gemini"])
    assert "concedido: editar" in capsys.readouterr().out
    with pytest.raises(SystemExit): cli.main(["permisos", "dar", "principal", "editar"])
    cli.main(["permisos", "quitar", "gemini", "editar"])
    assert "quitadas: 1" in capsys.readouterr().out
