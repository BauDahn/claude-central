"""Visor mínimo de Central: grafo de comunicación, bitácora (logs) y consumo por IA. Se lanza con `central ver`."""
import sys

from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget

from central.gui import theme
from central.gui.settings import load_settings
from central.gui.tabs.bitacora import BitacoraTab
from central.gui.tabs.consumo import ConsumoTab

VISTAS = ("grafo", "logs", "uso")


def main(vista: str = "grafo") -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app, load_settings())
    win = QMainWindow()
    win.setWindowTitle("central — " + vista)
    win.resize(1280, 800)
    tabs = QTabWidget()
    bit, uso = BitacoraTab(), ConsumoTab()
    tabs.addTab(bit, "Comunicación")
    tabs.addTab(uso, "Uso por IA")
    win.setCentralWidget(tabs)
    if vista == "uso":
        tabs.setCurrentWidget(uso)
    else:
        bit.mode.select("Mapa" if vista == "grafo" else "Lista")
        bit._set_mode("Mapa" if vista == "grafo" else "Lista")
    win.show()
    return app.exec()
