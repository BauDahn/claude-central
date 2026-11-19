"""Contrato: wrapper de la CLI `station` con QProcess (sin shell)."""
from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal
import threading
import time

_line_cache = {}; _line_locks = {}; _line_guard = threading.Lock()


class _TaskSignals(QObject):
    result = pyqtSignal(object)


class _Task:
    def __init__(self, fn, signals): self.fn, self.signals = fn, signals
    def run(self):
        try: value = self.fn()
        except Exception as exc: value = exc
        self.signals.result.emit(value)


def run_background(fn, callback):
    """Ejecuta trabajo bloqueante fuera de UI; callback recibe resultado o excepción."""
    from PyQt6.QtCore import QRunnable, QThreadPool
    signals = _TaskSignals()
    signals.result.connect(callback)
    task = _Task(fn, signals)
    runnable = QRunnable.create(task.run)
    QThreadPool.globalInstance().start(runnable)
    return signals


class Station(QObject):
    salida = pyqtSignal(str)        # texto (stdout+stderr) a medida que llega
    terminado = pyqtSignal(int)     # código de salida

    def __init__(self, parent=None):
        super().__init__(parent)
        self._p = None

    def run(self, args: list[str]) -> None:
        """Ejecuta `station *args`. args SIEMPRE lista; nunca shell."""
        self._p = QProcess(self)
        self._p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._p.readyReadStandardOutput.connect(
            lambda: self.salida.emit(bytes(self._p.readAllStandardOutput()).decode(errors="replace")))
        self._p.finished.connect(lambda code, _s: self.terminado.emit(code))
        env = QProcessEnvironment.systemEnvironment()
        if not env.contains("STATION_LOCAL_KEY"):
            env.insert("STATION_LOCAL_KEY", "local")
        self._p.setProcessEnvironment(env)
        self._p.start("station", args)

    def detener(self) -> None:
        if self._p:
            self._p.kill()


def station_lines(args: list[str], timeout: int = 15) -> str:
    """Llamada síncrona corta (roles, uso, optimizador)."""
    import subprocess
    r = subprocess.run(["station", *args], capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def station_lines_cached(args: list[str], ttl: float = 10, timeout: int = 15) -> str:
    key = tuple(args)
    with _line_guard:
        lock = _line_locks.setdefault(key, threading.Lock())
    with lock:
        now = time.monotonic(); cached = _line_cache.get(key)
        if cached and now - cached[0] < ttl: return cached[1]
        value = station_lines(args, timeout)
        _line_cache[key] = (time.monotonic(), value)
        return value
