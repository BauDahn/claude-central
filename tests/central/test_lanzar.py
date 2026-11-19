import os
from pathlib import Path

from central import cli, lanzar


def test_comando_de_claude_con_sistema_y_central_permitido(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTRAL_HOME", str(tmp_path / "h")); monkeypatch.setenv("CENTRAL_CONTEXTO", str(tmp_path / "ctx"))
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/claude")
    cmd = lanzar.comando(tmp_path, ["--model", "opus"])
    assert cmd[0] == "/usr/bin/claude" and cmd[-2:] == ["--model", "opus"]
    permitidas = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert "Bash(central correr:*)" in permitidas and "Bash(pytest:*)" in permitidas and "Bash(agy:*)" in permitidas
    assert not any("permisos dar" in p for p in permitidas) and "Bash(central:*)" not in permitidas
    assert "--append-system-prompt-file" in cmd
    sistema = Path(cmd[cmd.index("--append-system-prompt-file") + 1]).read_text()
    assert "central correr" in sistema and "constructor" in sistema and str(tmp_path) in sistema


def test_central_principal_lanza_claude_y_pasa_flags(monkeypatch):
    llamado = []
    monkeypatch.setattr(lanzar, "lanzar", lambda extra: llamado.append(extra))
    cli.main(["principal"]); cli.main(["principal", "--model", "opus"])
    assert llamado == [[], ["--model", "opus"]]
