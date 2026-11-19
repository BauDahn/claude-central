import json
import unittest

from agent_station import eventos
from agent_station import cli, ejecutor
from agent_station.propuestas import parsear_bloque


class PropuestasTests(unittest.TestCase):
    def test_parsear_bloque_propuesta(self):
        data = {"id":"p1", "funcion":"revisor", "modelo_recomendado":"gpt-6-luna",
                "alternativas":["claude-sonnet-5-5"], "motivo":"revisar", "tarea":"mirá los cambios"}
        self.assertEqual(parsear_bloque("texto\n```propuesta\n" + json.dumps(data) + "\n```\n"), data)
        self.assertIsNone(parsear_bloque("```propuesta\n{mal}\n```"))


    def test_eventos_propuesta_aprobacion_lanzamiento(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as d:
            os.environ["AGENT_STATION_HOME"] = d
            try:
                propuesta = eventos.registrar("propuesta", id="p2", funcion="constructor", modelo="gpt-6-luna")
                aprobacion = eventos.registrar("aprobacion", id=propuesta["id"], modelo="claude-sonnet-5-5")
                lanzamiento = eventos.registrar("lanzamiento", funcion="constructor", modelo=aprobacion["modelo"], propuesta=propuesta["id"])
                self.assertEqual([e["tipo"] for e in eventos.leer()], ["propuesta", "aprobacion", "lanzamiento"])
                self.assertEqual(lanzamiento["propuesta"], "p2")
            finally:
                os.environ.pop("AGENT_STATION_HOME", None)

    def test_lanzamiento_requiere_aprobacion_y_registra_evento(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as d:
            os.environ["AGENT_STATION_HOME"] = d
            try:
                eventos.registrar("propuesta", id="p3", funcion="constructor", modelo="gpt-6-luna")
                with self.assertRaises(SystemExit):
                    ejecutor.correr("constructor", "tarea", __import__("pathlib").Path(d), ajustes={"model":"gpt-6-luna", "backend":"eco"}, propuesta="p3")
                eventos.registrar("aprobacion", id="p3", modelo="gpt-6-luna")
                result = ejecutor.correr("constructor", "tarea", __import__("pathlib").Path(d), ajustes={"model":"gpt-6-luna", "backend":"eco"}, propuesta="p3")
                self.assertEqual(result.codigo, 0)
                self.assertTrue(any(e["tipo"] == "lanzamiento" and e.get("propuesta") == "p3" for e in eventos.leer()))
            finally:
                os.environ.pop("AGENT_STATION_HOME", None)


    def test_correr_exige_modelo(self):
        try:
            cli.main(["correr", "constructor", "tarea"])
        except SystemExit as exc:
            self.assertIn("--modelo es obligatorio", str(exc))
            self.assertIn("gpt-6-luna", str(exc))
        else:
            self.fail("correr sin modelo debía fallar")
