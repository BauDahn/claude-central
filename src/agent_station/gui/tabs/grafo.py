"""Mapa animado de comunicaciones entre agentes."""
import math
import time
from collections import defaultdict
from datetime import datetime

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics, QPolygonF, QPainterPath, QRadialGradient
from PyQt6.QtWidgets import QWidget, QToolTip, QSizePolicy


def _colors():
    from agent_station.gui import theme
    return theme.colors()


def _font_family():
    try:
        from agent_station.gui import theme
        return theme.current_family() or 'Sora'
    except Exception:
        return 'Sora'


def _src(ev): return str(ev.get('de') or ev.get('agente') or ev.get('backend') or 'Station')
def _dst(ev): return str(ev.get('a') or 'Station')
def _body(ev): return str(ev.get('cuerpo', ev.get('mensaje', ev.get('resultado', ev.get('tipo', 'Evento')))))
def _ts(ev):
    try: return float(ev.get('ts', 0) or 0)
    except (TypeError, ValueError, OverflowError): return 0.0


def _activity(ev):
    text = ' '.join(str(ev.get(k, '')) for k in ('tipo', 'estado', 'accion', 'cuerpo', 'mensaje', 'detalle')).casefold()
    if any(x in text for x in ('espera', 'esperando', 'wait', 'blocked', 'bloquead')): return 'Esperando'
    if any(x in text for x in ('pensando', 'thinking', 'reasoning', 'razonando')): return 'Pensando'
    if any(x in text for x in ('program', 'coding', 'implement', 'editando', 'escribiendo')): return 'Programando'
    if any(x in text for x in ('error', 'falló', 'fallo')): return 'Con error'
    return 'Trabajando'


def _split_label(name):
    """Divide nombres largos en 2 líneas en separadores naturales (-, _, espacio) o al medio."""
    for sep in ('-', '_', ' '):
        if sep in name and len(name) > 10:
            idx = len(name) // 2
            positions = [i for i, ch in enumerate(name) if ch == sep]
            best = min(positions, key=lambda i: abs(i - idx))
            left, right = name[:best + (1 if sep == '-' else 0)], name[best + 1:]
            if left and right:
                return f"{left}\n{right}"
    if len(name) >= 13:
        mid = len(name) // 2
        return f"{name[:mid]}-\n{name[mid:]}"
    return name


def fit_node_label(name, family='Sora', min_radius=40, max_radius=56):
    """Calcula (radio, tamaño_fuente, texto_ajustado) para que el nombre nunca se corte."""
    text = str(name or '')
    for pt in (10, 9.5, 9, 8.5):
        fm = QFontMetrics(QFont(family, round(pt), QFont.Weight.Bold))
        w = fm.horizontalAdvance(text)
        needed = math.ceil(w / 2 + 13)
        if needed <= max_radius:
            return max(min_radius, needed), pt, text
    wrapped = _split_label(text)
    if '\n' in wrapped:
        for pt in (9.5, 9, 8.5, 8):
            fm = QFontMetrics(QFont(family, round(pt), QFont.Weight.Bold))
            w = max(fm.horizontalAdvance(line) for line in wrapped.splitlines())
            needed = math.ceil(w / 2 + 13)
            if needed <= max_radius:
                return max(min_radius, needed), pt, wrapped
    for pt in (8, 7.5, 7):
        fm = QFontMetrics(QFont(family, round(pt), QFont.Weight.Bold))
        lines = wrapped.splitlines() if '\n' in wrapped else [text]
        w = max(fm.horizontalAdvance(line) for line in lines)
        needed = math.ceil(w / 2 + 12)
        if needed <= max_radius + 6:
            return max(min_radius, min(max_radius + 6, needed)), pt, wrapped
    return max_radius + 6, 7, wrapped


class GrafoWidget(QWidget):
    edgeSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.events, self.nodes, self.edges = [], [], []
        self.hover = None
        self.selected = None
        self.phase = 0.
        self.pulse_until = 0.
        self.pulse_edge = None
        self.last_message = ''
        self.active_window = None
        self.statuses = {}
        self.models = {}
        self.counts = {}
        self.backends = {}
        self._radii = {}
        self._node_layout_meta = {}
        self._last_agg = 0.0

    def set_events(self, events):
        self.events = list(events)
        self._aggregate()
        self.update()

    def pulse(self, a=None, b=None):
        self.pulse_until = time.monotonic() + .5
        self.pulse_edge = (a, b) if a and b else None
        self.update()

    def advance(self):
        self.phase = (self.phase + .016) % 1.
        if self.active_window and time.monotonic() - self._last_agg >= 1.0:
            self._aggregate()
        self.update()

    def _aggregate(self):
        self._last_agg = time.monotonic()
        agg = defaultdict(list)
        counts = defaultdict(lambda: [0, 0])
        self.backends = {}
        if self.active_window:
            cutoff = time.time() - self.active_window
            live = [ev for ev in self.events if _ts(ev) >= cutoff]
        else:
            live = list(self.events)
        self.statuses = {}
        active = set()
        workflow = {}
        for ev in sorted(live, key=_ts):
            if ev.get('tipo') in ('propuesta', 'aprobacion', 'rechazo', 'lanzamiento', 'terminado'):
                fn = ev.get('funcion')
                if not fn and ev.get('tipo') in ('aprobacion', 'rechazo'):
                    proposal = next((x for x in reversed(self.events) if x.get('tipo') == 'propuesta' and x.get('id') == ev.get('id')), {})
                    fn = proposal.get('funcion')
                if fn:
                    state = {
                        'propuesta': 'Propuesta pendiente',
                        'aprobacion': 'Aprobado',
                        'rechazo': 'Rechazado',
                        'lanzamiento': 'Corriendo',
                        'terminado': 'Terminado',
                    }.get(ev['tipo'])
                    workflow[fn] = (state, ev.get('modelo', ''))
                    active.add(fn)
                    continue
            a, b = _src(ev), _dst(ev)
            agents = [name for name in (a, b) if name.casefold() not in ('station', 'usuario', 'user', 'consumo')]
            for name in agents:
                active.add(name)
                self.statuses[name] = _activity(ev)
            if len(agents) == 2 and a != b:
                agg[(a, b)].append(ev)
                counts[a][0] += 1
                counts[b][1] += 1
            backend = str(ev.get('backend') or ev.get('compania') or '').casefold()
            if backend:
                self.backends.setdefault(a, backend)
                self.backends.setdefault(b, backend)
        self.nodes = sorted(active, key=str.casefold)
        self.models = {n: workflow[n][1] for n in workflow}
        self.statuses.update({n: workflow[n][0] for n in workflow})
        self.edges = [(a, b, rows) for (a, b), rows in agg.items()]
        self.counts = counts
        family = _font_family()
        self._node_layout_meta = {n: fit_node_label(n, family=family) for n in self.nodes}
        self._radii = {n: meta[0] for n, meta in self._node_layout_meta.items()}

    def _positions(self):
        if not self.nodes:
            return {}
        w, h = max(320, self.width()), max(280, self.height())
        n = len(self.nodes)
        max_r = max((self._radii.get(name, 46) for name in self.nodes), default=46)
        top = max_r + 18
        bottom = max_r + 68
        side = max_r + 36
        avail_h = max(80, h - top - bottom)
        avail_w = max(120, w - 2 * side)
        cx, cy = w / 2, top + avail_h / 2
        if n == 1:
            return {self.nodes[0]: QPointF(cx, cy)}
        if n == 2 and w >= h:
            dx = max(95, avail_w * 0.34)
            return {self.nodes[0]: QPointF(cx - dx, cy), self.nodes[1]: QPointF(cx + dx, cy)}

        rx = max(90, avail_w / 2)
        ry = max(75, avail_h / 2)
        pts = {
            name: [
                cx + rx * math.cos(-math.pi / 2 + 2 * math.pi * i / n),
                cy + ry * math.sin(-math.pi / 2 + 2 * math.pi * i / n),
            ]
            for i, name in enumerate(self.nodes)
        }
        # Relajación suave para garantizar separación mínima entre nodos (incluyendo etiquetas inferiores)
        if n >= 5:
            x_lo, x_hi = side, w - side
            y_lo, y_hi = top, h - bottom
            for _ in range(36):
                moved = False
                for i in range(n):
                    ni = self.nodes[i]
                    ri = self._radii.get(ni, 46)
                    for j in range(i + 1, n):
                        nj = self.nodes[j]
                        rj = self._radii.get(nj, 46)
                        dx = pts[nj][0] - pts[ni][0]
                        dy = pts[nj][1] - pts[ni][1]
                        # Más separación vertical para dejar lugar al estado/modelo debajo de cada nodo
                        min_dx = ri + rj + 24
                        min_dy = ri + rj + 44
                        dist = math.hypot(dx, dy * (min_dx / min_dy))
                        if dist < min_dx:
                            moved = True
                            if dist < 1e-3:
                                dx, dy = 1.0, 0.5
                                dist = 1.0
                            push = (min_dx - dist) * 0.45
                            ux, uy = dx / dist, (dy * (min_dx / min_dy)) / dist
                            pts[ni][0] -= ux * push
                            pts[ni][1] -= uy * push * (min_dy / min_dx)
                            pts[nj][0] += ux * push
                            pts[nj][1] += uy * push * (min_dy / min_dx)
                for name in self.nodes:
                    pts[name][0] = min(x_hi, max(x_lo, pts[name][0]))
                    pts[name][1] = min(y_hi, max(y_lo, pts[name][1]))
                if not moved:
                    break
        return {name: QPointF(xy[0], xy[1]) for name, xy in pts.items()}

    def _node_color(self, name, c):
        status = self.statuses.get(name, 'Trabajando')
        return QColor({
            'Esperando': '#F4B942',
            'Propuesta pendiente': '#F4B942',
            'Pensando': '#70DDE3',
            'Con error': '#F06A73',
            'Rechazado': '#F06A73',
            'Programando': c['accent'],
            'Corriendo': c['accent'],
            'Aprobado': c['accent'],
            'Trabajando': c['accent2'],
            'Terminado': c['accent2'],
        }.get(status, c['accent2']))

    def _edge_path(self, a, b, pos):
        u, v = pos[a], pos[b]
        dx, dy = v.x() - u.x(), v.y() - u.y()
        length = max(1., math.hypot(dx, dy))
        ux, uy = dx / length, dy / length
        ra = self._radii.get(a, 46)
        rb = self._radii.get(b, 46)
        start = QPointF(u.x() + ux * (ra + 5), u.y() + uy * (ra + 5))
        end = QPointF(v.x() - ux * (rb + 7), v.y() - uy * (rb + 7))
        reverse = any(x == b and y == a for x, y, _ in self.edges)
        offset = min(44., length * .20) * (1 if (a, b) < (b, a) else -1) if reverse else 0
        normal = QPointF(-uy * offset, ux * offset)
        control = QPointF((start.x() + end.x()) / 2 + normal.x(),
                          (start.y() + end.y()) / 2 + normal.y())
        path = QPainterPath(start)
        path.quadTo(control, end)
        return path, start, end, control

    def paintEvent(self, event):
        c = _colors()
        family = _font_family()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_background(p, c)
        if not self.nodes:
            self._draw_empty(p, c, family)
            p.end()
            return
        pos = self._positions()
        now = time.monotonic()
        edge_badges = []
        active_badges = []

        for a, b, rows in self.edges:
            if a not in pos or b not in pos:
                continue
            path, start, end, control = self._edge_path(a, b, pos)
            highlighted = self.hover == ('edge', a, b) or self.selected == ('edge', a, b)
            pulsing = self.pulse_edge == (a, b) and now < self.pulse_until
            active_edge = highlighted or pulsing
            color = QColor(c['accent'] if active_edge else c['line'])
            width = max(1.8, min(5.5, 1.8 + math.log1p(len(rows)) * 1.15))
            if active_edge:
                width += 1.0
            p.setPen(QPen(color, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            tangent = QPointF(end.x() - control.x(), end.y() - control.y())
            length = max(1., math.hypot(tangent.x(), tangent.y()))
            ux, uy = tangent.x() / length, tangent.y() / length
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            arrow = QPolygonF([
                end,
                QPointF(end.x() - ux * 11 - uy * 5, end.y() - uy * 11 + ux * 5),
                QPointF(end.x() - ux * 11 + uy * 5, end.y() - uy * 11 - ux * 5),
            ])
            p.drawPolygon(arrow)

            t = (self.phase + (abs(hash((a, b))) % 100) / 100) % 1
            dot = QPointF(
                (1 - t) * (1 - t) * start.x() + 2 * (1 - t) * t * control.x() + t * t * end.x(),
                (1 - t) * (1 - t) * start.y() + 2 * (1 - t) * t * control.y() + t * t * end.y(),
            )
            p.setBrush(QColor(c['accent'] if active_edge else c['accent2']))
            p.drawEllipse(dot, 3.8, 3.8)

            mid = QPointF(.25 * start.x() + .5 * control.x() + .25 * end.x(),
                          .25 * start.y() + .5 * control.y() + .25 * end.y())
            if active_edge:
                label = f"{a} → {b} ({len(rows)})"
                active_badges.append((mid, label))
            else:
                edge_badges.append((mid, str(len(rows))))

        # Pastillas discretas con cantidad de mensajes en aristas
        p.setFont(QFont(family, 8, QFont.Weight.DemiBold))
        fm_small = p.fontMetrics()
        for mid, txt in edge_badges:
            bw = max(24, fm_small.horizontalAdvance(txt) + 12)
            box = QRectF(mid.x() - bw / 2, mid.y() - 10, bw, 20)
            bg = QColor(c['surface'])
            bg.setAlpha(230)
            p.setPen(QPen(QColor(c['line']), 1))
            p.setBrush(bg)
            p.drawRoundedRect(box, 10, 10)
            p.setPen(QColor(c['muted']))
            p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), txt)

        # Nodos siempre encima de las líneas/etiquetas normales
        for name, point in pos.items():
            base_r, font_pt, label_txt = self._node_layout_meta.get(name) or fit_node_label(name, family=family)
            hovered = self.hover == ('node', name)
            selected = self.selected == ('node', name)
            color = self._node_color(name, c)
            radius = base_r + (3 if hovered or selected else 0)
            if hovered or selected:
                halo = QColor(color)
                halo.setAlpha(60)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(halo)
                p.drawEllipse(point, radius + 7, radius + 7)
            p.setPen(QPen(QColor(c['text'] if hovered or selected else c['line']), 2.2 if selected else 1.6))
            p.setBrush(color)
            p.drawEllipse(point, radius, radius)

            p.setPen(QColor(c['bg']))
            f_node = QFont(family)
            f_node.setPointSizeF(font_pt)
            f_node.setWeight(QFont.Weight.Bold)
            p.setFont(f_node)
            inner = radius - 6
            p.drawText(QRectF(point.x() - inner, point.y() - inner, inner * 2, inner * 2),
                       int(Qt.AlignmentFlag.AlignCenter), label_txt)

            status = self.statuses.get(name, 'Trabajando')
            p.setPen(QColor(color))
            p.setFont(QFont(family, 9, QFont.Weight.DemiBold))
            p.drawText(QRectF(point.x() - 100, point.y() + radius + 5, 200, 18),
                       int(Qt.AlignmentFlag.AlignCenter), status)
            if self.models.get(name):
                p.setPen(QColor(c['muted']))
                p.setFont(QFont(family, 8))
                p.drawText(QRectF(point.x() - 110, point.y() + radius + 22, 220, 16),
                           int(Qt.AlignmentFlag.AlignCenter), self.models[name])

        # Etiqueta completa de la arista activa/seleccionada siempre al frente
        if active_badges:
            p.setFont(QFont(family, 9, QFont.Weight.DemiBold))
            fm_edge = p.fontMetrics()
            for mid, label in active_badges:
                lw = min(max(110, fm_edge.horizontalAdvance(label) + 20), max(140, self.width() // 2))
                box = QRectF(mid.x() - lw / 2, mid.y() - 13, lw, 26)
                bg = QColor(c['surface2'])
                bg.setAlpha(245)
                p.setPen(QPen(QColor(c['accent']), 1.2))
                p.setBrush(bg)
                p.drawRoundedRect(box, 8, 8)
                p.setPen(QColor(c['text']))
                p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), label)

        self._draw_legend(p, c, family)
        p.end()

    def _draw_background(self, p, c):
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.fillRect(self.rect(), QColor(c['bg']))
        panel = QPainterPath()
        panel.addRoundedRect(rect, 16, 16)
        p.setPen(QPen(QColor(c['line']), 1))
        p.setBrush(QColor(c['surface']))
        p.drawPath(panel)
        p.save()
        p.setClipPath(panel)
        dot = QColor(c['line'])
        dot.setAlpha(150)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot)
        step = 28
        for x in range(step, self.width(), step):
            for y in range(step, self.height(), step):
                p.drawEllipse(QPointF(x, y), 1.1, 1.1)
        glow = QColor(c['accent'])
        glow.setAlpha(22)
        grad = QRadialGradient(QPointF(self.width() / 2, self.height() / 2), max(self.width(), self.height()) * .55)
        grad.setColorAt(0, glow)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(grad)
        p.drawRect(self.rect())
        p.restore()

    def _draw_empty(self, p, c, family='Sora'):
        cx, cy = self.width() / 2, self.height() / 2 - 20
        ring = QColor(c['accent'])
        for r, a in ((70, 25), (50, 45), (30, 90)):
            ring.setAlpha(a)
            p.setPen(QPen(ring, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c['accent']))
        p.drawEllipse(QPointF(cx, cy), 7, 7)
        p.setPen(QColor(c['text']))
        p.setFont(QFont(family, 15, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, cy + 84, self.width(), 28), int(Qt.AlignmentFlag.AlignCenter), 'Ningún agente trabajando ahora')
        p.setPen(QColor(c['muted']))
        p.setFont(QFont(family, 10))
        p.drawText(QRectF(0, cy + 114, self.width(), 22), int(Qt.AlignmentFlag.AlignCenter),
                   'Cuando los agentes se comuniquen, el mapa aparece acá')

    def _draw_legend(self, p, c, family='Sora'):
        colors = [
            ('Programando / Corriendo', c['accent']),
            ('Esperando', '#F4B942'),
            ('Pensando', '#70DDE3'),
            ('Trabajando / Terminado', c['accent2']),
            ('Con error', '#F06A73'),
        ]
        x, y = 20, self.height() - 16
        p.setFont(QFont(family, 9))
        for label, color in colors:
            if x + 140 > self.width():
                break
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(x + 5, y - 4), 5, 5)
            p.setPen(QColor(c['muted']))
            p.drawText(x + 15, y, label)
            x += p.fontMetrics().horizontalAdvance(label) + 30

    def _hit(self, point):
        pos = self._positions()
        for name, p in pos.items():
            r = self._radii.get(name, 46)
            if math.hypot(p.x() - point.x(), p.y() - point.y()) < r + 6:
                return ('node', name)
        for a, b, _ in self.edges:
            if a not in pos or b not in pos:
                continue
            path, start, end, control = self._edge_path(a, b, pos)
            for i in range(1, 21):
                t = i / 20
                cur = QPointF(
                    (1 - t) * (1 - t) * start.x() + 2 * (1 - t) * t * control.x() + t * t * end.x(),
                    (1 - t) * (1 - t) * start.y() + 2 * (1 - t) * t * control.y() + t * t * end.y(),
                )
                if math.hypot(point.x() - cur.x(), point.y() - cur.y()) < 12:
                    return ('edge', a, b)
        return None

    def mouseMoveEvent(self, event):
        self.hover = self._hit(event.position())
        self.update()
        if self.hover and self.hover[0] == 'node':
            name = self.hover[1]
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"{name}: pidió {self.counts.get(name, [0, 0])[0]} veces / recibió {self.counts.get(name, [0, 0])[1]}",
                self,
            )
        else:
            QToolTip.hideText()

    def _show_details(self, rows, title):
        rows = rows[:6]
        messages = []
        for ev in rows:
            ts = float(ev.get('ts', 0) or 0)
            stamp = datetime.fromtimestamp(ts).strftime('%H:%M:%S') if ts else ''
            messages.append(f"{_src(ev)} → {_dst(ev)} · {stamp}\n{str(ev.get('tipo', 'evento')).upper()}\n{_body(ev)}")
        self.last_message = f"{title}\n\n" + "\n\n──────────\n\n".join(reversed(messages))
        self.edgeSelected.emit(self.last_message)
        parent = self.parent()
        while parent and not hasattr(parent, 'detail'):
            parent = parent.parent()
        if parent:
            parent.detail.setPlainText(self.last_message)

    def mousePressEvent(self, event):
        hit = self._hit(event.position())
        self.selected = hit
        self.update()
        if not hit:
            return
        if hit[0] == 'edge':
            rows = next((r for a, b, r in self.edges if (a, b) == (hit[1], hit[2])), [])
            if rows:
                self._show_details(rows, f"{hit[1]} → {hit[2]} · últimos mensajes")
        elif hit[0] == 'node':
            name = hit[1]
            rows = [ev for ev in self.events if name in (_src(ev), _dst(ev), ev.get('funcion'))]
            if rows:
                self._show_details(rows, f"{name} · últimos mensajes")
