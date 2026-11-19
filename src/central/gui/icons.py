"""Iconos sencillos pintados para no depender de glifos emoji del sistema."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QPainterPath, QColor


def icon(name, color="#F8F8F5", size=18):
    pix = QPixmap(size, size); pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush); path = QPainterPath()
    if name == "clip":
        # Dos vueltas concéntricas con la abertura del clip hacia abajo.
        path.moveTo(size*.67,size*.2)
        path.cubicTo(size*.91,size*.2,size*.94,size*.4,size*.77,size*.57)
        path.lineTo(size*.46,size*.88)
        path.cubicTo(size*.25,size*1.08,size*.02,size*.8,size*.23,size*.59)
        path.lineTo(size*.57,size*.25)
        path.cubicTo(size*.72,size*.1,size*.87,size*.3,size*.72,size*.45)
        path.lineTo(size*.38,size*.79)
        path.cubicTo(size*.3,size*.87,size*.2,size*.76,size*.28,size*.68)
        p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    elif name == "send":
        path.moveTo(size*.16,size*.12); path.lineTo(size*.9,size*.48); path.lineTo(size*.16,size*.88); path.lineTo(size*.32,size*.52); path.closeSubpath(); p.setBrush(QColor(color))
    elif name == "copy":
        p.drawRoundedRect(QRectF(size*.31,size*.14,size*.55,size*.62),2,2); path.addRoundedRect(QRectF(size*.14,size*.32,size*.55,size*.58),2,2)
    elif name == "close":
        path.moveTo(size*.25,size*.25); path.lineTo(size*.75,size*.75); path.moveTo(size*.75,size*.25); path.lineTo(size*.25,size*.75)
    elif name == "mic":
        path.addRoundedRect(QRectF(size*.36, size*.14, size*.28, size*.42), size*.14, size*.14)
        path.moveTo(size*.24, size*.46)
        path.arcTo(QRectF(size*.24, size*.26, size*.52, size*.44), 180, 180)
        path.moveTo(size*.50, size*.70); path.lineTo(size*.50, size*.86)
        path.moveTo(size*.34, size*.86); path.lineTo(size*.66, size*.86)
    elif name == "volume":
        path.moveTo(size*.16, size*.38); path.lineTo(size*.34, size*.38); path.lineTo(size*.54, size*.20); path.lineTo(size*.54, size*.80); path.lineTo(size*.34, size*.62); path.lineTo(size*.16, size*.62); path.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.arcMoveTo(QRectF(size*.52, size*.30, size*.24, size*.40), -55); path.arcTo(QRectF(size*.52, size*.30, size*.24, size*.40), -55, 110)
        path.arcMoveTo(QRectF(size*.56, size*.18, size*.34, size*.64), -55); path.arcTo(QRectF(size*.56, size*.18, size*.34, size*.64), -55, 110)
    elif name == "volume_off":
        path.moveTo(size*.16, size*.38); path.lineTo(size*.34, size*.38); path.lineTo(size*.54, size*.20); path.lineTo(size*.54, size*.80); path.lineTo(size*.34, size*.62); path.lineTo(size*.16, size*.62); path.closeSubpath()
        path.moveTo(size*.66, size*.34); path.lineTo(size*.88, size*.66); path.moveTo(size*.88, size*.34); path.lineTo(size*.66, size*.66)
    elif name == "stop":
        p.setBrush(QColor(color))
        path.addRoundedRect(QRectF(size*.25, size*.25, size*.50, size*.50), 2, 2)
    elif name == "waveform":
        for x, h in ((.20, .30), (.35, .56), (.50, .74), (.65, .50), (.80, .32)):
            y0 = size * (0.5 - h / 2); y1 = size * (0.5 + h / 2)
            path.moveTo(size * x, y0); path.lineTo(size * x, y1)
    p.drawPath(path); p.end(); return QIcon(pix)
