"""Temas y fuentes de Central."""
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette


class _ThemeSignals(QObject):
    changed = pyqtSignal()


signals = _ThemeSignals()
_loaded = False
_COLORS = {
    "negro": dict(bg="#050505", surface="#101010", surface2="#181818", line="#292929", text="#F8F8F5", muted="#92928D", accent="#C6F68D", accent2="#B2A6FF", danger="#FF6B6B"),
    "papel": dict(bg="#F6F3EC", surface="#FFFEFA", surface2="#EEEAE1", line="#D8D2C7", text="#171714", muted="#706D66", accent="#FF6A3D", accent2="#6657C8", danger="#C83F36"),
    "medianoche": dict(bg="#0B0F1A", surface="#121827", surface2="#1A2234", line="#29344A", text="#F3F5FA", muted="#9AA6BC", accent="#9B8CFF", accent2="#5CE1E6", danger="#FF718A"),
}


def colors(tema=None):
    """Paleta activa, o la paleta indicada."""
    key = tema or _active_theme
    return dict(_COLORS.get(key, _COLORS["negro"]))


_active_theme = "negro"
_active_cfg = None
_active_app = None

def px(n, chat=False):
    """Tamaño CSS proporcional al tamaño tipográfico activo (en píxeles lógicos)."""
    base = getattr(_active_cfg, "tamano", 14) or 14
    scale = getattr(_active_cfg, "escala_chat", 1.15) if chat else 1.0
    dpi = 96.0
    try:
        if _active_app and _active_app.primaryScreen():
            dpi = _active_app.primaryScreen().logicalDotsPerInch()
    except (RuntimeError, AttributeError):
        pass
    return max(11, round(float(n) * base * scale * dpi / 72.0))

def _zoom(delta=0, reset=False):
    if _active_cfg is None or _active_app is None:
        return
    _active_cfg.tamano = 14 if reset else max(10, min(24, int(_active_cfg.tamano) + delta))
    apply(_active_app, _active_cfg)
    try:
        from central.gui.settings import CONFIG_PATH
        _active_cfg.save(CONFIG_PATH)
    except (OSError, RuntimeError):
        pass

def zoom_in(): _zoom(1)
def zoom_out(): _zoom(-1)
def reset_zoom(): _zoom(reset=True)


def load_fonts():
    global _loaded
    if _loaded:
        return
    directory = Path(__file__).with_name("fonts")
    for path in directory.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(path))
    _loaded = True


_family = "Sora"

def current_family():
    return _family

def apply(app, cfg=None):
    global _active_theme, _family, _active_cfg, _active_app
    from central.gui.settings import Settings
    cfg = cfg or Settings()
    _active_cfg, _active_app = cfg, app
    load_fonts()
    _active_theme = cfg.tema
    c = colors()
    family = cfg.fuente.replace(" ", "")
    aliases = {"PlusJakartaSans": "Plus Jakarta Sans", "SpaceGrotesk": "Space Grotesk", "DMSans": "DM Sans", "BricolageGrotesque": "Bricolage Grotesque"}
    family = aliases.get(family, cfg.fuente)
    _family = family
    pal = QPalette()
    for role, key in ((QPalette.ColorRole.Window, 'bg'), (QPalette.ColorRole.Base, 'surface'), (QPalette.ColorRole.AlternateBase, 'surface2'), (QPalette.ColorRole.Button, 'surface'),
                      (QPalette.ColorRole.WindowText, 'text'), (QPalette.ColorRole.Text, 'text'), (QPalette.ColorRole.ButtonText, 'text'), (QPalette.ColorRole.ToolTipText, 'text'),
                      (QPalette.ColorRole.PlaceholderText, 'muted'), (QPalette.ColorRole.Highlight, 'accent'), (QPalette.ColorRole.ToolTipBase, 'surface')):
        pal.setColor(role, QColor(c[key]))
    app.setPalette(pal)
    tops = [w for w in app.topLevelWidgets() if w.isVisible()]
    for w in tops: w.setUpdatesEnabled(False)
    app.setFont(QFont(family, max(10, min(24, int(cfg.tamano)))) )
    app.setStyleSheet(f'''
      QMainWindow,QDialog {{ background:{c['bg']}; color:{c['text']}; font-family:"{family}"; }}
      QLabel,QPushButton,QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QCheckBox,QRadioButton,QSpinBox,QDoubleSpinBox,QListView,QTableView,QProgressBar {{ color:{c['text']}; font-family:"{family}"; outline:none; }}
      QFrame#sidebar {{ background:{c['surface']}; border-right:1px solid {c['line']}; }}
      QLabel {{ color:{c['text']}; background:transparent; }}
      QPushButton {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['line']}; border-radius:11px; padding:9px 14px; }}
      QPushButton:hover {{ border-color:{c['accent']}; }} QPushButton:checked,QPushButton#primary {{ background:{c['accent']}; color:{c['bg']}; }}
      QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QTableWidget,QListWidget {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['line']}; border-radius:10px; padding:8px; selection-background-color:{c['accent']}; }}
      QLineEdit:focus,QTextEdit:focus,QComboBox:focus {{ border:1px solid {c['accent']}; }}
      QHeaderView::section {{ background:{c['surface2']}; color:{c['muted']}; border:0; padding:8px; }}
      QScrollArea,QScrollArea > QWidget > QWidget {{ background:transparent; border:0; }}
      QAbstractScrollArea {{ background:transparent; }}
      QToolButton {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['line']}; border-radius:9px; padding:5px 8px; }}
      QToolButton:hover {{ border-color:{c['accent']}; }}
      QMenu {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['line']}; padding:4px; }}
      QMenu::item:selected {{ background:{c['surface2']}; }}
      QScrollBar:vertical {{ background:transparent; width:6px; }} QScrollBar::handle:vertical {{ background:{c['muted']}; border-radius:3px; min-height:20px; }}
    ''')
    signals.changed.emit()
    for w in tops: w.setUpdatesEnabled(True); w.update()
