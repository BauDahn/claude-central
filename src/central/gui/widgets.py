"""Componentes visuales reutilizables de Central."""
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, pyqtProperty, QParallelAnimationGroup, QPoint, QVariantAnimation, QTimer, QElapsedTimer
from PyQt6.QtGui import QPainter, QColor, QPixmap, QPen, QPainterPath, QRegion
from PyQt6.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QGraphicsOpacityEffect, QStackedWidget, QGraphicsDropShadowEffect, QScrollArea)
from central.gui.theme import colors, signals

def _refresh_theme_widgets():
    from PyQt6.QtWidgets import QApplication
    app=QApplication.instance()
    if app:
        for widget in app.allWidgets(): widget.update()

signals.changed.connect(_refresh_theme_widgets)

def backend_label(backend, model=""):
    """Nombre legible del proveedor y modelo configurados."""
    backend = str(backend).strip().casefold()
    model = str(model).strip()
    if backend == "codex":
        return f"OpenAI · {model}" if model else "OpenAI"
    if backend == "claude":
        return f"Anthropic · {model}" if model else "Anthropic"
    if backend == "openai":
        return "OpenAI"
    if backend == "eco":
        return "Eco"
    return f"{backend.title()} · {model}" if model else backend.title()

def _animation(widget, prop, end, duration=220):
    anim = QPropertyAnimation(widget, prop, widget)
    anim.setDuration(duration); anim.setEasingCurve(QEasingCurve.Type.OutBack)
    anim.setEndValue(end); anim.start()
    widget._central_animation = anim
    return anim

def paint_shadow(painter, rect, radius, color, spread=14, alpha=0.18, offset_y=0):
    """Sombra difusa cacheada por tamaño y estilo."""
    dpr=painter.device().devicePixelRatioF() if painter.device() else 1.0
    key=(rect.width(),rect.height(),radius,color,spread,round(alpha,3),round(dpr,3))
    cache=getattr(paint_shadow,"_cache",{})
    pix=cache.get(key)
    if pix is None:
        pix=QPixmap(round((rect.width()+spread*2)*dpr),round((rect.height()+spread*2)*dpr)); pix.setDevicePixelRatio(dpr); pix.fill(Qt.GlobalColor.transparent)
        q=QPainter(pix); q.setRenderHint(QPainter.RenderHint.Antialiasing); base=QColor(color)
        shape=QPainterPath(); shape.addRoundedRect(spread,spread,rect.width(),rect.height(),radius,radius)
        for i in range(spread,0,-1):
            c=QColor(base); c.setAlphaF(alpha*((spread-i+1)/spread)**2)
            q.setPen(QPen(c,1)); q.setBrush(Qt.BrushStyle.NoBrush); q.drawPath(shape)
        q.end(); cache[key]=pix; paint_shadow._cache=cache
    painter.drawPixmap(rect.topLeft()+QPoint(-spread,-spread+offset_y),pix)

def _paint_cost(widget, timer, name):
    elapsed=timer.elapsed()
    if elapsed>4: print(f"[paint] {name} {elapsed}ms size={widget.width()}x{widget.height()}",flush=True)

def _cached_panel(width,height,rect,radius,c):
    dpr=QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0
    key=(width,height,rect.x(),rect.y(),rect.width(),rect.height(),radius,c['bg'],c['surface'],c['line'],round(dpr,2))
    cache=getattr(_cached_panel,'_cache',{})
    pix=cache.get(key)
    if pix is None:
        pix=QPixmap(round(width*dpr),round(height*dpr)); pix.setDevicePixelRatio(dpr); pix.fill(Qt.GlobalColor.transparent)
        q=QPainter(pix); q.setRenderHint(QPainter.RenderHint.Antialiasing)
        paper=c['bg']=='#F6F3EC'
        paint_shadow(q,rect,radius,'#766E60' if paper else '#000000',14 if paper else 18,.20 if paper else .50,0 if paper else 4)
        q.setPen(QPen(QColor(c['line']),1)); q.setBrush(QColor(c['surface'])); q.drawRoundedRect(rect,radius,radius)
        if not paper:
            q.setPen(QPen(QColor(255,255,255,18),1)); q.drawLine(rect.left()+radius,rect.top()+1,rect.right()-radius,rect.top()+1)
        q.end()
        if len(cache)>128: cache.clear()
        cache[key]=pix; _cached_panel._cache=cache
    return pix

def _card_frame(widget, selected=False, glow=0.0):
    c=colors(); paper=c['bg']=='#F6F3EC'; rect=widget.rect().adjusted(14,14,-14,-14)
    painter=QPainter(widget); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0,0,_cached_panel(widget.width(),widget.height(),rect,14,c))
    pbg=getattr(widget,'preview_bg',None)
    if pbg: painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(pbg)); painter.drawRoundedRect(rect,14,14)
    if selected or glow>0.01:
        accent=QColor(c['accent']); accent.setAlphaF(1.0 if selected else 0.85*glow)
        painter.setPen(QPen(accent,2 if selected else 1+glow)); painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1,1,-1,-1),14,14)
    painter.end()

class _SnapshotOverlay(QWidget):
    def __init__(self, blocks, parent):
        super().__init__(parent); self.blocks=blocks; self.progress=0.0; self._last_dirty=QRegion()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    def _get_progress(self): return self.progress
    def _set_progress(self,v):
        self.progress=float(v); dirty=QRegion()
        for pix,rect,start,duration in self.blocks:
            t=(self.progress-start)/max(.001,duration)
            if 0.0 <= t < 1.0:
                t=max(0.0,min(1.0,t)); y=round(26*max(0.0,1-t/.20)**3)
                dirty|=QRegion(rect.x(),rect.y()+y,pix.width(),pix.height())
        repaint=dirty|self._last_dirty
        self._last_dirty=dirty
        if not repaint.isEmpty(): self.update(repaint)
    progressValue=pyqtProperty(float,_get_progress,_set_progress)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for pix,rect,start,duration in self.blocks:
            t=max(0.0,min(1.0,(self.progress-start)/max(.001,duration)))
            eased=1-(1-t)**3
            if eased <= 0: continue
            # Settle the short offset early, then let the 600 ms fade carry
            # the rest of the reveal without shifting ink back out of view.
            shift=max(0.0,1-min(1.0,t/.20))**3
            p.setOpacity(eased); p.drawPixmap(rect+QPoint(0,round(26*shift)),pix)

def heading(texto, destacadas=()):
    from html import escape
    emphasized = set(destacadas); c = colors()
    parts = [f'<i><span style="font-family:Instrument Serif;font-size:40px;color:{c["accent"]}">{escape(word)}</span></i>' if word in emphasized else escape(word) for word in texto.split()]
    label = QLabel(" ".join(parts)); label.setTextFormat(Qt.TextFormat.RichText); label.setStyleSheet("font-size:30px;font-weight:700;")
    label._heading_text=texto; label._heading_emphasis=tuple(destacadas)
    def refresh():
        c=colors(); emphasized=set(label._heading_emphasis)
        label.setText(" ".join(f'<i><span style="font-family:Instrument Serif;font-size:40px;color:{c["accent"]}">{escape(word)}</span></i>' if word in emphasized else escape(word) for word in label._heading_text.split()))
    signals.changed.connect(refresh)
    return label

class PageHeader(QWidget):
    def __init__(self, primero, destacado, sub="", parent=None):
        super().__init__(parent); layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,12); layout.setSpacing(2)
        layout.addWidget(heading(f"{primero} {destacado}", destacado.split()))
        if sub:
            detail=QLabel(sub); detail.setStyleSheet(f"color:{colors()['muted']};margin-bottom:8px;"); layout.addWidget(detail)

class RotatingArrow(QLabel):
    def __init__(self): super().__init__("⌄"); self.angle=0.0; self.setStyleSheet("font-size:18px;")
    def _get_angle(self): return self.angle
    def _set_angle(self,value): self.angle=value; self.update()
    angleValue=pyqtProperty(float,_get_angle,_set_angle)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.translate(self.rect().center()); p.rotate(self.angle); p.translate(-self.rect().center()); p.setPen(QColor(colors()['muted'])); p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "⌄")

def stagger_in(widgets, delay=40, enabled=True):
    from PyQt6.QtCore import QTimer
    if enabled:
        for i, widget in enumerate(widgets): QTimer.singleShot(i*delay, lambda w=widget: fade_in(w, True))

class Collapsible(QFrame):
    def __init__(self, titulo, subtitulo="", parent=None, animaciones=True):
        super().__init__(parent); self.animaciones = animaciones; self.open = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("centralCollapsible"); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.setContentsMargins(14,14,14,14)
        self.setStyleSheet("QFrame#centralCollapsible{background:transparent;border:0px;}" )
        self._shadow_spread=14; layout=QVBoxLayout(self); layout.setContentsMargins(20,16,20,16); layout.setSpacing(8)
        self.toggle=QPushButton(); self.toggle.setStyleSheet("text-align:left;border:0;background:transparent;padding:0 4px;")
        self.toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row=QHBoxLayout(); text=QVBoxLayout(); text.setContentsMargins(0,0,0,0); text.setSpacing(6); title=QLabel(titulo); title.setStyleSheet("font-weight:700;")
        text.addWidget(title)
        if subtitulo:
            sub=QLabel(subtitulo); sub.setStyleSheet(f"color:{colors()['muted']};"); text.addWidget(sub); self.subtitle=sub
        self.arrow=RotatingArrow(); row.addLayout(text,1); row.addWidget(self.arrow); self.toggle.setLayout(row)
        self.toggle.setMinimumHeight(row.sizeHint().height())
        layout.addWidget(self.toggle)
        self.body=QWidget(); self.body_layout=QVBoxLayout(self.body); self.body_layout.setContentsMargins(0,6,0,0)
        self.body.setMaximumHeight(0); self.body.setVisible(False); layout.addWidget(self.body)
        self.toggle.clicked.connect(lambda _checked=False: self.set_open())
        signals.changed.connect(self._theme_changed)
    def _theme_changed(self):
        if hasattr(self,"subtitle"): self.subtitle.setStyleSheet(f"color:{colors()['muted']};")
    def paintEvent(self,event):
        timer=QElapsedTimer(); timer.start()
        _card_frame(self)
        _paint_cost(self,timer,'Collapsible')
    def set_open(self, value=None):
        self.open=not self.open if value is None else bool(value)
        if self.animaciones:
            _animation(self.arrow, b"angleValue", 180.0 if self.open else 0.0, 260)
        else: self.arrow.angle = 180.0 if self.open else 0.0; self.arrow.update()
        target=self.body_layout.sizeHint().height() if self.open else 0
        if self.open: self.body.setVisible(True)
        if self.animaciones:
            anim=_animation(self.body,b"maximumHeight",target)
            if not self.open: anim.finished.connect(lambda:self.body.setVisible(False))
        else:
            self.body.setMaximumHeight(target)
            if not self.open: self.body.setVisible(False)

class Card(QFrame):
    selectedChanged=pyqtSignal(bool)
    def __init__(self,titulo,descripcion="",chip="",parent=None,animaciones=True):
        super().__init__(parent); self.animaciones=animaciones; self.selected=False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.setContentsMargins(14,14,14,14)
        self.setCursor(Qt.CursorShape.PointingHandCursor); self.setObjectName("centralCard")
        self._shadow_spread=14; lay=QVBoxLayout(self); lay.setContentsMargins(20,16,20,16); lay.setSpacing(6)
        self.title=QLabel(titulo); self.title.setStyleSheet("font-weight:700;"); lay.addWidget(self.title)
        if descripcion: self.description=QLabel(descripcion); self.description.setWordWrap(True); self.description.setStyleSheet("color:#888;"); lay.addWidget(self.description)
        if chip: self.chip=QLabel(chip); self.chip.setStyleSheet("color:#888;font-size:10px;"); lay.addWidget(self.chip)
        self._style()
        self._glow=0.0
        signals.changed.connect(self._theme_changed)
    def _theme_changed(self):
        c=colors()
        for attr in ("description","chip"):
            label=getattr(self,attr,None)
            if label: label.setStyleSheet(f"color:{c['muted']};"+("font-size:10px;" if attr=="chip" else ""))
        self.update()
    def hasHeightForWidth(self): return True
    def heightForWidth(self,width):
        lay=self.layout()
        return lay.heightForWidth(width) if lay and lay.hasHeightForWidth() else self.sizeHint().height()
    def _get_glow(self): return self._glow
    def _set_glow(self,v): self._glow=max(0.0,min(1.0,float(v))); self.update(self.rect().adjusted(10,10,-10,-10))
    glow=pyqtProperty(float,_get_glow,_set_glow)
    def _animate_glow(self,end,ms):
        if not self.animaciones: self._set_glow(end); return
        anim=QPropertyAnimation(self,b"glow",self); anim.setDuration(ms); anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self._glow); anim.setEndValue(end); anim.start(); self._glow_anim=anim
    def enterEvent(self,event): self._animate_glow(1.0,220); super().enterEvent(event)
    def leaveEvent(self,event): self._animate_glow(0.0,200); super().leaveEvent(event)
    def paintEvent(self,event):
        timer=QElapsedTimer(); timer.start()
        _card_frame(self,self.selected,self._glow)
        _paint_cost(self,timer,'Card')
    def _style(self):
        style="QFrame#centralCard{background:transparent;border:0px;}"
        if self.styleSheet()!=style: self.setStyleSheet(style)
        self.update()
    def set_selected(self,value):
        value=bool(value)
        if self.selected==value: return
        self.selected=value; self._style(); self.selectedChanged.emit(self.selected)
    def mousePressEvent(self,event): self.set_selected(not self.selected); super().mousePressEvent(event)

class Switch(QPushButton):
    toggled=pyqtSignal(bool)
    def __init__(self,checked=False,parent=None,animaciones=True):
        super().__init__(parent); self.checked=checked; self.animaciones=animaciones; self._offset=26 if checked else 4; self.setFixedSize(52,30); self.setCheckable(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self._toggle)
    def _get_offset(self): return self._offset
    def _set_offset(self,value): self._offset=value; self.update()
    offset=pyqtProperty(float,_get_offset,_set_offset)
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c=colors(); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c['accent'] if self.checked else c['surface2'])); p.drawRoundedRect(self.rect(),15,15)
        p.setBrush(QColor("#fff" if self.checked else "#aaa")); p.drawEllipse(int(self._offset),4,22,22)
    def _toggle(self,checked=False):
        self.checked=not self.checked
        if self.animaciones: _animation(self,b"offset",26.0 if self.checked else 4.0,200)
        else: self._offset=26 if self.checked else 4; self.update()
        self.toggled.emit(self.checked)
    def isChecked(self): return self.checked
    def setChecked(self,value): self.checked=bool(value); self._offset=26 if self.checked else 4; self.update()

class Chips(QWidget):
    selectionChanged=pyqtSignal(str)
    def __init__(self,options,selected=None,parent=None):
        super().__init__(parent); self.buttons={}; grid=QGridLayout(self); grid.setContentsMargins(0,0,0,0); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        columns=4
        for i, option in enumerate(options):
            b=QPushButton(str(option)); b.setCheckable(True); b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # Explicit checked colors keep the selected chip readable across themes
            # and avoid stylesheet inheritance leaving the text the same color as fill.
            c=colors(); b.setStyleSheet(f"QPushButton:checked{{background:{c['accent']};color:{c['bg']};border:1px solid {c['accent']};}}")
            b.clicked.connect(lambda checked, x=str(option):self.select(x)); grid.addWidget(b, i//columns, i%columns); self.buttons[str(option)]=b
        self.select(str(selected if selected is not None else options[0])); signals.changed.connect(self._theme_changed)
    def _theme_changed(self):
        c=colors()
        for b in self.buttons.values(): b.setStyleSheet(f"QPushButton:checked{{background:{c['accent']};color:{c['bg']};border:1px solid {c['accent']};}}")
    def select(self,value):
        for name,button in self.buttons.items(): button.setChecked(name==value)
        self.selectionChanged.emit(value)
    def current(self): return next((name for name,b in self.buttons.items() if b.isChecked()),"")

class FadeStack(QStackedWidget):
    def __init__(self,parent=None,animaciones=True):
        super().__init__(parent); self.animaciones=animaciones; self._overlays=[]; self._pending_initial=None
    def setCurrentIndex(self,index):
        if index<0 or index>=self.count() or index==self.currentIndex(): return
        self._finish_transition()
        animate=self.animaciones
        if not animate:
            self._finish_transition(); super().setCurrentIndex(index); return
        new=self.widget(index)
        if not new: super().setCurrentIndex(index); return
        super().setCurrentIndex(index)
        new.hide()
        self._begin_transition(new)
    def animateCurrent(self):
        if not self.animaciones or self.currentIndex()<0: return
        self._finish_transition(); new=self.currentWidget(); new.hide(); self._begin_transition(new)
    def _begin_transition(self,new):
        new.ensurePolished(); new.adjustSize(); layout=new.layout()
        if layout: layout.activate()
        blocks=[]
        root=new.widget() if isinstance(new,QScrollArea) else new
        lay=root.layout() if root else None
        # PagePanel wraps the actual page layout in one outer layout item.
        if lay and lay.count()==1 and lay.itemAt(0).layout(): lay=lay.itemAt(0).layout()
        if lay:
            for i in range(lay.count()):
                item=lay.itemAt(i); w=item.widget()
                if not w or w.isHidden(): continue
                w.ensurePolished(); pix=w.grab()
                if not pix.isNull(): blocks.append((pix,w.mapTo(self,QPoint(0,0)),i))
        # Hide the real page before changing the stack index so it cannot paint
        # a full frame beneath the snapshots.
        new.hide()
        if not blocks:
            new.show(); return
        duration=900
        count=len(blocks)
        schedule=[]
        for pix,pos,i in blocks:
            # The first visible content starts at zero; later blocks cascade in.
            start=min(i*110, max(0,duration-600))
            schedule.append((pix,pos,start/duration,600/duration))
        incoming=_SnapshotOverlay(schedule,self); incoming.setGeometry(self.rect()); incoming.show(); incoming.raise_(); self._overlays=[incoming]
        anim=QVariantAnimation(self); anim.setDuration(duration); anim.setStartValue(0.0); anim.setEndValue(1.0); anim.setEasingCurve(QEasingCurve.Type.Linear)
        anim.valueChanged.connect(incoming._set_progress)
        def finish():
            new.show(); self._finish_transition()
        anim.finished.connect(finish); anim.start(); self._transition=anim
    def _finish_transition(self):
        a=getattr(self,'_transition',None)
        if a: a.stop(); self._transition=None
        for overlay in self._overlays: overlay.hide(); overlay.deleteLater()
        self._overlays=[]

class PagePanel(QWidget):
    def __init__(self, child=None, parent=None, radius=18):
        super().__init__(parent); self.radius=radius
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay=QVBoxLayout(self); lay.setContentsMargins(16,16,16,16)
        if child: child.setParent(self); lay.addWidget(child)
    def paintEvent(self,event):
        timer=QElapsedTimer(); timer.start()
        c=colors(); r=self.rect().adjusted(14,14,-14,-14); p=QPainter(self)
        p.drawPixmap(0,0,_cached_panel(self.width(),self.height(),r,self.radius,c))
        p.end(); _paint_cost(self,timer,'PagePanel')

class ShadowBox(PagePanel):
    def __init__(self, inner_widget, radius=14, parent=None): super().__init__(inner_widget,parent,radius)

class ShadowSurface(QFrame):
    """Frame with a cached theme surface and soft shadow behind its children."""
    def __init__(self,parent=None,radius=16):
        super().__init__(parent); self.radius=radius
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        signals.changed.connect(self.update)
    def paintEvent(self,event):
        timer=QElapsedTimer(); timer.start(); c=colors(); r=self.rect().adjusted(8,8,-8,-8)
        p=QPainter(self); p.drawPixmap(0,0,_cached_panel(self.width(),self.height(),r,self.radius,c)); p.end()
        _paint_cost(self,timer,'ShadowBox')

class Toast(QFrame):
    def __init__(self,texto,parent=None):
        super().__init__(parent); layout=QHBoxLayout(self); layout.addWidget(QLabel(texto)); self.setStyleSheet("QFrame{background:#222;border-radius:12px;padding:8px;} QLabel{color:white;}")
    def dismiss(self): self.hide()

def fade_in(widget,animaciones=True):
    if not animaciones: return None
    return None
