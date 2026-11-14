<!-- equipo:inicio -->
## Equipo multi-máquina (`equipo`)
Si existe `~/agentes/equipo.conf`, esta máquina trabaja en equipo con otras (cada una con su central). Lo compartido vive en GitHub (`REPO` del conf); `ListAgents`/`SendMessage` solo ven esta máquina.
- **Al arrancar y cada vez que el usuario pregunte "qué pasa" o termine algo:** `equipo mensajes` (mensajes de otras máquinas) y `equipo mias` (issues asignados a esta máquina). Avisale al usuario lo nuevo.
- **Si `ROL=orquestador`** (el central que coordina todo el equipo): `equipo ver` muestra el estado de cada máquina (rama, cambios sin subir, agentes abiertos, últimas tareas de Codex), los issues por máquina y los PRs. Repartí trabajo con `equipo asignar <maquina> "título" --cuerpo "qué, criterio de hecho, archivos"` (un issue = una rama = un PR), y avisá con `equipo avisar <maquina> "..."`. Vigilá conflictos: dos máquinas tocando los mismos archivos, ramas muy atrasadas respecto de main, PRs sin revisar. Revisá los PRs de los demás (`gh pr diff`, o `/code-review <PR#>`).
- **Si `ROL=miembro`:** trabajá los issues de `equipo mias`; cuando cerrás uno (PR abierto), `equipo avisar <orquestador> "PR #N listo para revisar"`. Si necesitás algo de otra máquina, pedíselo al orquestador con `equipo avisar`.
- El estado de esta máquina se publica solo cada 10 min (timer de `guardar-estado`); después de un hito, `equipo publicar` para que se vea al momento.
<!-- equipo:fin -->
