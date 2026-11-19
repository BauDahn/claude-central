"""Bitácora incremental con modelo virtualizado y mapa de comunicaciones."""
import json
import os
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QAbstractListModel, QModelIndex, QThread, QTimer, pyqtSignal, QSize, QRect, QEvent
from PyQt6.QtGui import QColor, QPainter, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QListView,
                             QStyledItemDelegate, QStyle, QPushButton, QSplitter, QTextEdit, QScrollArea,
                             QSizePolicy)
from agent_station.gui.widgets import Chips, Switch, ShadowBox
from agent_station.gui.tabs.grafo import GrafoWidget


def _colors():
    from agent_station.gui import theme
    return theme.colors()


def _event_text(ev):
    kind = str(ev.get('tipo', 'evento')).upper()
    if kind == 'MSG':
        return str(ev.get('cuerpo', ev.get('mensaje', '')))
    if kind == 'USO':
        return f"{ev.get('backend', '')} · {ev.get('modelo', '')} · {ev.get('resultado', ev.get('tarea', ''))}"
    return str(ev.get('cuerpo', ev.get('mensaje', ev.get('detalle', ev.get('tipo', 'Evento')))))


def _agent(ev):
    return str(ev.get('de') or ev.get('agente') or ev.get('backend') or 'Station')


def _timestamp(ev):
    try: return float(ev.get('ts', 0) or 0)
    except (TypeError, ValueError, OverflowError): return 0.0


class EventReader(QThread):
    events = pyqtSignal(list)
    def __init__(self, path, parent=None):
        super().__init__(parent); self.path = Path(path); self._stop = False; self._active = False; self._offset = 0; self._partial = b''
    def run(self):
        while not self._stop:
            if not self._active:
                self.msleep(250); continue
            try:
                if self.path.exists():
                    size = self.path.stat().st_size
                    if size < self._offset: self._offset = 0; self._partial = b''
                    with self.path.open('rb') as f:
                        f.seek(self._offset); data = f.read(); self._offset = f.tell()
                    lines = (self._partial + data).split(b'\n'); self._partial = lines.pop()
                    rows=[]
                    for line in lines:
                        try: rows.append(json.loads(line.decode('utf-8', 'replace')))
                        except (ValueError, TypeError): pass
                    if rows: self.events.emit(rows)
            except OSError: pass
            self.msleep(350)
    def stop(self): self._stop = True; self.wait(1000)
    def set_active(self, active): self._active = bool(active)


class EventModel(QAbstractListModel):
    def __init__(self, parent=None): super().__init__(parent); self.rows=[]; self.agent='Todos'; self.period='todo'; self.complete=False; self._visible=[]
    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self._visible)
    def visible(self):
        now=time.time(); cutoff=now-3600 if self.period=='1h' else datetime.now().replace(hour=0,minute=0,second=0,microsecond=0).timestamp() if self.period=='hoy' else 0
        return [e for e in self.rows if _timestamp(e)>=cutoff and (self.agent=='Todos' or self.agent in (_agent(e),str(e.get('a',''))))]
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        ev=self._visible[index.row()]
        if role==Qt.ItemDataRole.UserRole: return ev
        if role==Qt.ItemDataRole.DisplayRole: return _event_text(ev)
        return None
    def add(self, rows):
        if not rows:return
        rows=sorted(rows,key=_timestamp,reverse=True)
        self.beginResetModel(); self.rows=rows+self.rows; self.rows=self.rows[:5000]; self._visible=self.visible(); self.endResetModel()
    def set_filter(self, agent=None, period=None):
        self.beginResetModel()
        if agent is not None:self.agent=agent
        if period is not None:self.period=period
        self._visible=self.visible()
        self.endResetModel()


class EventDelegate(QStyledItemDelegate):
    def __init__(self,parent=None): super().__init__(parent); self.arrivals={}
    def sizeHint(self, option, index):
        ev=index.data(Qt.ItemDataRole.UserRole) or {}; full=index.model().complete
        lines=min(14,max(2,(len(_event_text(ev))+88)//89)) if full else 2
        return QSize(480,64+lines*18)
    def paint(self, painter, option, index):
        ev=index.data(Qt.ItemDataRole.UserRole) or {}; c=_colors(); rect=option.rect
        painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg=QColor(c['surface']); bg.setAlpha(245); painter.setPen(QColor(c['line'])); painter.setBrush(bg); painter.drawRoundedRect(rect.adjusted(3,3,-5,-3),14,14)
        x=rect.x()+18; y=rect.y()+23; who=_agent(ev); to=str(ev.get('a','Station')); ts=_timestamp(ev)
        try: stamp=datetime.fromtimestamp(ts).strftime('%H:%M:%S') if ts else ''
        except (OSError, OverflowError, ValueError): stamp=''
        painter.setFont(QFont('Sora',10,QFont.Weight.DemiBold)); painter.setPen(QColor(c['accent'])); painter.drawText(x,y,who)
        who_width=painter.fontMetrics().horizontalAdvance(who)
        painter.setPen(QColor(c['muted'])); painter.drawText(x+who_width+8,y,'→')
        painter.setPen(QColor(c['accent2'])); painter.drawText(x+who_width+24,y,to)
        painter.setPen(QColor(c['muted'])); painter.setFont(QFont('Sora',8)); painter.drawText(rect.right()-90,y,stamp)
        painter.setPen(QColor(c['text'])); painter.setFont(QFont('Sora',9)); msg=_event_text(ev).replace('\n',' ')
        full=index.model().complete
        painter.drawText(QRect(x,y+22,rect.width()-38,rect.height()-29), int(Qt.TextFlag.TextWordWrap), msg if full or len(msg)<250 else msg[:247]+'…')
        painter.restore()


class AgentChips(QScrollArea):
    """Chips de agente estables: 'Todos' fijo, orden inicial alfabetico, ancho por contenido,
    scroll horizontal; un agente nuevo solo AGREGA un chip al final (no toca los existentes)."""
    selectionChanged = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False); self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFixedHeight(46); self.buttons = {}; self._sel = 'Todos'
        self.setStyleSheet("QScrollBar:horizontal{height:4px;background:transparent;} QScrollBar::handle:horizontal{background:#444;border-radius:2px;min-width:20px;} QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}")
        inner = QWidget(); inner.setFixedHeight(38); self._inner = inner
        self.setWidget(inner); self.add_agents(['Todos'])
    def add_agents(self, names):
        for n in sorted(n for n in names if n not in self.buttons):
            b = QPushButton(n, self._inner); b.setCheckable(True); b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.ensurePolished(); b.setFixedSize(b.sizeHint())
            b.clicked.connect(lambda _c, x=n: self.select(x))
            x = max((button.x() + button.width() + 8 for button in self.buttons.values()), default=0)
            b.move(x, 0); b.show(); self.buttons[n] = b
            b.setChecked(n == self._sel)
            self._inner.resize(x + b.width(), self._inner.height())
    def select(self, value, emit=True):
        if value not in self.buttons: return
        self._sel = value
        for n, b in self.buttons.items(): b.setChecked(n == value)
        if emit: self.selectionChanged.emit(value)
    def current(self): return self._sel


class BitacoraTab(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self._events=[]; self._agents=['Todos']; self._mode='Lista'
        root=QVBoxLayout(self); root.setSpacing(12)
        top=QHBoxLayout(); top.addWidget(QLabel('Actividad reciente')); top.addStretch(1)
        top.addWidget(QLabel('Ver detalle completo')); self.completo=Switch(False); top.addWidget(self.completo)
        top.addWidget(QLabel('En vivo')); self.en_vivo=Switch(True); top.addWidget(self.en_vivo); root.addLayout(top)
        controls=QHBoxLayout(); self.mode=Chips(['Lista','Mapa']); self.period=Chips(['1h','hoy','todo'],'todo'); controls.addWidget(self.mode); controls.addStretch(1); controls.addWidget(self.period); root.addLayout(controls)
        self.filtros=AgentChips(); root.addWidget(self.filtros); self._held=[]
        self.model=EventModel(self); self.list=QListView(); self.list.setModel(self.model); self.list.setItemDelegate(EventDelegate(self.list)); self.list.setUniformItemSizes(False); self.list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.graph=GrafoWidget(self); self.detail=QTextEdit(); self.detail.setReadOnly(True); self.detail.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth); self.detail.setPlainText('Tocá una flecha o un agente para ver qué se pidieron')
        self.detail.setMinimumWidth(220); self.detail.setMaximumWidth(340); self._style_detail()
        self.map_split=QSplitter(); self.map_split.addWidget(self.graph); self.map_split.addWidget(self.detail); self.map_split.setStretchFactor(0,1); self.map_split.setStretchFactor(1,0); self.map_split.setSizes([920,280]); self.map_split.setHandleWidth(8); self.map_split.setChildrenCollapsible(False); self.map_split.hide()
        self.list_shadow=ShadowBox(self.list,radius=14); root.addWidget(self.list_shadow,1); root.addWidget(self.map_split,1)
        self.mode.selectionChanged.connect(self._set_mode); self.period.selectionChanged.connect(lambda p:self._filters(period=p)); self.filtros.selectionChanged.connect(lambda a:self._filters(agent=a)); self.completo.toggled.connect(self._toggle_complete); self.en_vivo.toggled.connect(self._toggle_live)
        self._pending=[]
        self.pill=QPushButton('',self.list.viewport()); self.pill.setCursor(Qt.CursorShape.PointingHandCursor); self.pill.setFocusPolicy(Qt.FocusPolicy.NoFocus); self.pill.hide()
        self.pill.setStyleSheet('QPushButton{background:#6c5ce7;color:white;border:none;border-radius:13px;padding:5px 16px;font-weight:600;}')
        self.pill.clicked.connect(self._flush_held); self.list.viewport().installEventFilter(self)
        home=Path(os.environ.get('AGENT_STATION_HOME',Path.home()/'.agent-station')); self.reader=EventReader(home/'eventos.jsonl',self); self.reader.events.connect(self._receive); self.reader.start()
        self.live_timer=QTimer(self); self.live_timer.timeout.connect(self._tick); self.live_timer.setInterval(33)
        from agent_station.gui import theme
        theme.signals.changed.connect(self._theme_changed)
    def _style_detail(self):
        c=_colors()
        self.detail.setStyleSheet(
            f"QTextEdit{{background:{c['surface']};color:{c['text']};border:1px solid {c['line']};border-radius:14px;padding:8px;font-size:12px;}}"
            f"QScrollBar:vertical{{background:transparent;width:6px;margin:6px 1px;}}"
            f"QScrollBar::handle:vertical{{background:{c['line']};border-radius:3px;min-height:30px;}}"
            f"QScrollBar::handle:vertical:hover{{background:{c['accent']};}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
            f"QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:transparent;}}")
    def showEvent(self,event):
        super().showEvent(event); self.reader.set_active(True); self.live_timer.start()
    def hideEvent(self,event):
        self.reader.set_active(False); self.live_timer.stop(); super().hideEvent(event)
    def _receive(self,events):
        if not self.en_vivo.isChecked(): self._pending.extend(events); return
        if self._pending: events=self._pending+events; self._pending=[]
        if self._mode=='Lista' and self.list.verticalScrollBar().value()>0:
            # el usuario esta leyendo: no insertar ni empujar; acumular y avisar con la pildora.
            self._held.extend(events); self._update_pill(); self._sync_agents(self._held); return
        self._apply(events)
    def _sync_agents(self,events):
        self.filtros.add_agents(sorted({_agent(e) for e in events if _agent(e)!='Station'}))
    def _apply(self,events):
        events=sorted(events,key=_timestamp,reverse=True); self.model.add(events); self._events=self.model.rows
        self._sync_agents(events)
        self.graph.set_events(self.model.visible())
        if self.en_vivo.isChecked() and events:
            latest=events[0]; self.graph.pulse(_agent(latest),str(latest.get('a') or 'Station'))
    def _update_pill(self):
        n=len(self._held)
        if not n: self.pill.hide(); return
        self.pill.setText(str(n)+(' nuevo' if n==1 else ' nuevos')+' ↑'); self.pill.adjustSize(); self._place_pill(); self.pill.show(); self.pill.raise_()
    def _place_pill(self):
        self.pill.move(max(0,(self.list.viewport().width()-self.pill.width())//2),8)
    def _flush_held(self):
        held=self._held; self._held=[]; self.pill.hide()
        if held: self._apply(held)
        self.list.verticalScrollBar().setValue(0)
    def eventFilter(self,obj,ev):
        if obj is self.list.viewport() and ev.type()==QEvent.Type.Resize and self.pill.isVisible(): self._place_pill()
        return super().eventFilter(obj,ev)
    def _filters(self,agent=None,period=None):
        self.model.set_filter(agent,period); self.graph.set_events(self.model.visible())
    def _set_mode(self,mode):
        self._mode=mode; self.list_shadow.setVisible(mode=='Lista'); self.map_split.setVisible(mode=='Mapa')
        if mode=='Mapa': self.graph.set_events(self.model.visible())
    def _tick(self):
        if self._mode=='Mapa' and self.en_vivo.isChecked():self.graph.advance()
    def _toggle_live(self,live):
        if live and self._pending: self._receive(self._pending); self._pending=[]
    def _toggle_complete(self,complete):
        self.model.complete=bool(complete); self.list.doItemsLayout(); self.list.viewport().update()
    def _theme_changed(self):
        self._style_detail(); self.list.viewport().update(); self.graph.update()
    def closeEvent(self,event):
        self.reader.stop(); super().closeEvent(event)
