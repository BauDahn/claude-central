"""Resumen visual del uso de tokens."""
import re
from PyQt6.QtCore import QTimer, Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame
from central.gui.cli import central_lines_cached, run_background
from central.gui.widgets import Card, Chips
from central.gui import theme


class ConsumoTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dimension = 'backend'; self._data = {}; self._optimizer = ''
        root = QVBoxLayout(self); root.setSpacing(14)
        row = QHBoxLayout(); row.setSpacing(12)
        self.total_card = Card('0', 'Tokens usados en total', 'ENTRADA + SALIDA')
        self.cache_card = Card('0%', 'Ahorro gracias a la caché', 'TOKENS REUTILIZADOS')
        self.tasks_card = Card('0', 'Tareas realizadas', 'EN ESTA MEDICIÓN')
        for card in (self.total_card, self.cache_card, self.tasks_card):
            card.setMaximumHeight(142); row.addWidget(card)
        root.addLayout(row)
        note = QLabel('La caché guarda partes ya procesadas para no volver a contarlas como trabajo nuevo.')
        note.setStyleSheet('color:#888;'); note.setWordWrap(True); root.addWidget(note)
        grouprow = QHBoxLayout(); grouprow.addWidget(QLabel('Ver uso por')); self.groups = Chips(['backend','agente','modelo'], 'backend'); grouprow.addWidget(self.groups); grouprow.addStretch(1); root.addLayout(grouprow)
        self.empty = QLabel('Cargando el uso…'); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); self.empty.setStyleSheet('color:#888;padding:20px;'); root.addWidget(self.empty)
        self.bars = QVBoxLayout(); self.bars.setSpacing(10); root.addLayout(self.bars)
        self.optimizer = QLabel(); self.optimizer.setWordWrap(True); self.optimizer.setStyleSheet('color:#888;'); root.addWidget(self.optimizer)
        self.groups.selectionChanged.connect(self._group_changed)
        self._refreshing = False; self._digest = None
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.setInterval(10000)

    def showEvent(self, event):
        super().showEvent(event); self.timer.start(); self.refresh()

    def hideEvent(self, event):
        self.timer.stop(); super().hideEvent(event)

    def _group_changed(self, value): self.dimension = value; self.refresh()

    def refresh(self):
        if self._refreshing or not self.isVisible(): return
        self._refreshing = True; dimension = self.dimension
        self._job = run_background(lambda: (dimension, central_lines_cached(['uso', '--por', dimension], 8), central_lines_cached(['optimizador'], 8)), self._loaded)

    def _loaded(self, result):
        self._refreshing = False
        if isinstance(result, Exception): data, opt = '', str(result)
        else:
            dimension, data, opt = result
            if dimension != self.dimension: return
        import hashlib
        digest = hashlib.sha256((data + '\0' + opt).encode()).digest()
        if digest == self._digest: return
        self._digest = digest
        parsed = {}; total = tasks = cached = input_total = 0
        for line in data.splitlines():
            parts = re.split(r'\s{2,}|\t', line.strip())
            if len(parts) < 2 or parts[0].casefold() in ('backend','agente','modelo',''): continue
            nums = [int(v.replace(',', '')) for v in re.findall(r'(?<![\w.])\d[\d,]*', ' '.join(parts[1:]))]
            if not nums: continue
            name = parts[0].strip()
            # central uso expone tareas, entrada, caché y salida; se conserva la proporción por grupo.
            task_count = nums[0] if len(nums) >= 2 else 0
            cache_count = nums[2] if len(nums) >= 4 else 0
            if len(nums) >= 4: input_total += nums[1]
            token_count = nums[1] + nums[2] + nums[3] if len(nums) >= 4 else nums[-1]
            parsed[name] = token_count; tasks += task_count; total += token_count; cached += cache_count
        self._data = parsed; self._optimizer = opt.strip()
        self.total_card.title.setText(f'{total:,}'.replace(',', ' ')); self.tasks_card.title.setText(f'{tasks:,}'.replace(',', ' '))
        self.cache_card.title.setText(f'{(cached * 100 // (input_total + cached)) if input_total + cached else 0}%')
        self.optimizer.setText(self._optimizer)
        while self.bars.count():
            item = self.bars.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if not parsed:
            self.empty.setText('Todavía no hay datos de consumo. Cuando ejecutes tareas, vas a ver acá el uso de tokens.')
            self.empty.show(); return
        self.empty.hide(); maximum = max(parsed.values()) or 1
        for name, amount in sorted(parsed.items(), key=lambda pair: pair[1], reverse=True):
            line = QHBoxLayout(); label = QLabel(name); label.setMinimumWidth(100); line.addWidget(label)
            bar = QProgressBar(); bar.setRange(0, maximum); bar.setValue(0); bar.setTextVisible(False); bar.setFixedHeight(8)
            palette = theme.colors()
            bar.setStyleSheet('QProgressBar{border:0;background:%s;border-radius:4px;} QProgressBar::chunk{background:%s;border-radius:4px;}' % (palette['surface2'], palette['accent'] if len(self.bars.children()) % 2 == 0 else palette['accent2']))
            animation = QPropertyAnimation(bar, b'value', bar); animation.setDuration(500); animation.setStartValue(0); animation.setEndValue(amount); animation.setEasingCurve(QEasingCurve.Type.OutCubic); animation.start(); bar._usage_animation = animation
            line.addWidget(bar,1); value = QLabel(f'{amount:,}'.replace(',', ' ')); value.setStyleSheet('color:#888;'); line.addWidget(value)
            holder = QWidget(); holder.setLayout(line); self.bars.addWidget(holder)
