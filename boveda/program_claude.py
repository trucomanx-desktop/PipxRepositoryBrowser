#!/usr/bin/python3
"""
Package Manager - A PyQt5 app to browse and install pipx packages from JSON repositories.
"""

import json
import subprocess
import sys
from pathlib import Path

import requests
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt5.QtGui import (
    QColor, QPainter, QFont, QLinearGradient, QPen, QBrush,
    QPixmap, QPalette
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QProgressBar,
    QFrame, QSizePolicy, QGridLayout, QMessageBox, QDialog,
    QToolButton, QSpacerItem, QAbstractScrollArea
)

# ─── Constants ────────────────────────────────────────────────────────────────

REPOSITORIES_PATH = Path("./repositories")
INSTALLED_JSON    = Path("./installed.json")

COL_BG        = "#0F1117"
COL_SURFACE   = "#1A1D27"
COL_SURFACE2  = "#22263A"
COL_ACCENT    = "#6C63FF"
COL_ACCENT2   = "#A78BFA"
COL_SUCCESS   = "#22C55E"
COL_DANGER    = "#EF4444"
COL_TEXT      = "#E8E9F3"
COL_MUTED     = "#6B7280"
COL_BORDER    = "#2D3148"

CARD_W = 96
CARD_H = 112
ICON_S = 54

STYLE_SHEET = f"""
QMainWindow, QDialog, QWidget {{
    background: {COL_BG};
    color: {COL_TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QScrollArea {{ border: none; background: {COL_BG}; }}
QScrollBar:vertical {{
    background: {COL_SURFACE}; width: 6px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {COL_BORDER}; border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {COL_ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLineEdit {{
    background: {COL_SURFACE}; border: 1.5px solid {COL_BORDER};
    border-radius: 8px; padding: 8px 14px; color: {COL_TEXT};
}}
QLineEdit:focus {{ border-color: {COL_ACCENT}; }}
QPushButton {{
    background: {COL_ACCENT}; color: white; border: none;
    border-radius: 8px; padding: 8px 20px; font-weight: 600;
}}
QPushButton:hover {{ background: {COL_ACCENT2}; }}
QPushButton#danger {{ background: {COL_DANGER}; }}
QPushButton#danger:hover {{ background: #DC2626; }}
QPushButton#secondary {{
    background: {COL_SURFACE2}; color: {COL_TEXT};
    border: 1.5px solid {COL_BORDER};
}}
QPushButton#secondary:hover {{ border-color: {COL_ACCENT}; color: {COL_ACCENT2}; }}
QProgressBar {{
    background: {COL_SURFACE}; border: none; border-radius: 4px;
    height: 6px; color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {COL_ACCENT}, stop:1 {COL_ACCENT2});
    border-radius: 4px;
}}
QToolButton#collapse {{
    background: transparent; border: none;
    color: {COL_MUTED}; font-size: 16px;
}}
QToolButton#collapse:hover {{ color: {COL_TEXT}; }}
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_installed() -> dict:
    if INSTALLED_JSON.exists():
        try:
            return json.loads(INSTALLED_JSON.read_text())
        except Exception:
            pass
    return {}

def save_installed(data: dict):
    INSTALLED_JSON.write_text(json.dumps(data, indent=4))

def is_installed(name: str, installed: dict) -> bool:
    return name.lower() in {k.lower() for k in installed}

def get_installed_version(name: str, installed: dict):
    for k, v in installed.items():
        if k.lower() == name.lower():
            return v.get("version")
    return None

def make_placeholder_icon(letter: str, size: int = ICON_S) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor(COL_ACCENT))
    grad.setColorAt(1, QColor(COL_ACCENT2))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    r = int(size * 0.18)
    p.drawRoundedRect(0, 0, size, size, r, r)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", int(size * 0.38), QFont.Bold)
    p.setFont(f)
    p.drawText(px.rect(), Qt.AlignCenter, letter.upper())
    p.end()
    return px

def overlay_check(pixmap: QPixmap) -> QPixmap:
    """Add green badge bottom-right."""
    result = QPixmap(pixmap)
    p = QPainter(result)
    p.setRenderHint(QPainter.Antialiasing)
    s = pixmap.width()
    b = max(14, int(s * 0.30))
    x, y = s - b - 1, s - b - 1
    p.setBrush(QColor(COL_SUCCESS))
    p.setPen(Qt.NoPen)
    p.drawEllipse(x, y, b, b)
    pen = QPen(QColor("white"), max(1.5, b * 0.13))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    cx, cy = x + b / 2, y + b / 2
    p.drawLine(
        int(cx - b*0.20), int(cy + b*0.02),
        int(cx - b*0.02), int(cy + b*0.22)
    )
    p.drawLine(
        int(cx - b*0.02), int(cy + b*0.22),
        int(cx + b*0.25), int(cy - b*0.20)
    )
    p.end()
    return result


# ─── Data model ───────────────────────────────────────────────────────────────

class PackageEntry:
    def __init__(self, data: dict, repo_name: str):
        self.name        = data.get("name", "")
        self.icon_url    = data.get("icon", "")
        self.screenshots = data.get("screenshots", [])
        self.categories  = data.get("categories", ["Any"])
        self.enabled     = data.get("enabled", True)
        self.repo_name   = repo_name
        self.icon_pixmap: QPixmap | None = None


# ─── Worker threads ───────────────────────────────────────────────────────────

class RepositoryLoader(QThread):
    progress      = pyqtSignal(int, int)
    package_found = pyqtSignal(object)
    finished_loading = pyqtSignal()

    def run(self):
        if not REPOSITORIES_PATH.exists():
            self.finished_loading.emit()
            return
        files = list(REPOSITORIES_PATH.glob("*.json"))
        total = len(files)
        for i, file in enumerate(files):
            self.progress.emit(i, total)
            try:
                data = json.loads(file.read_text())
                repo_name = data.get("name", file.stem)
                for pkg in data.get("packages", []):
                    if pkg.get("enabled", True):
                        self.package_found.emit(PackageEntry(pkg, repo_name))
            except Exception:
                pass
        self.progress.emit(total, total)
        self.finished_loading.emit()


class PyPIFetcher(QThread):
    done = pyqtSignal(dict)
    def __init__(self, name: str):
        super().__init__()
        self.name = name
    def run(self):
        try:
            r = requests.get(f"https://pypi.org/pypi/{self.name}/json", timeout=10)
            if r.status_code == 200:
                self.done.emit(r.json())
                return
        except Exception:
            pass
        self.done.emit({})


class IconFetcher(QThread):
    done = pyqtSignal(str, QPixmap)
    def __init__(self, name: str, url: str):
        super().__init__()
        self.name = name
        self.url  = url
    def run(self):
        try:
            r = requests.get(self.url, timeout=8)
            if r.status_code == 200:
                px = QPixmap()
                px.loadFromData(r.content)
                if not px.isNull():
                    # Emit full-resolution — callers scale to their display size
                    self.done.emit(self.name, px)
                    return
        except Exception:
            pass
        self.done.emit(self.name, QPixmap())


class PipxRunner(QThread):
    result = pyqtSignal(bool, str)
    def __init__(self, args):
        super().__init__()
        self.args = args
    def run(self):
        try:
            proc = subprocess.run(["pipx"] + self.args, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                self.result.emit(True, proc.stdout)
            else:
                self.result.emit(False, proc.stderr or proc.stdout)
        except FileNotFoundError:
            self.result.emit(False, "pipx not found. Please install pipx.")
        except Exception as e:
            self.result.emit(False, str(e))


# ─── Package card ─────────────────────────────────────────────────────────────

class PackageCard(QWidget):
    """
    Drawn entirely in paintEvent — no child widgets that could steal events.
    """
    clicked = pyqtSignal(object)

    def __init__(self, entry: PackageEntry, installed: dict, parent=None):
        super().__init__(parent)
        self.entry     = entry
        self.installed = installed
        self._hovered  = False
        self._pixmap   = self._build_pixmap()

        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(entry.name)
        self.setAttribute(Qt.WA_Hover, True)

    # ── pixmap helpers ────────────────────────────────────────────────────────

    def _get_icon(self) -> QPixmap:
        px = self.entry.icon_pixmap
        if px is None or px.isNull():
            px = make_placeholder_icon(self.entry.name[0] if self.entry.name else "?", ICON_S)
        else:
            # Two-step downscale from full-res for better quality
            if px.width() > ICON_S * 2 or px.height() > ICON_S * 2:
                px = px.scaled(ICON_S * 2, ICON_S * 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            px = px.scaled(ICON_S, ICON_S, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            if px.width() != ICON_S or px.height() != ICON_S:
                x = (px.width()  - ICON_S) // 2
                y = (px.height() - ICON_S) // 2
                px = px.copy(x, y, ICON_S, ICON_S)
        if is_installed(self.entry.name, self.installed):
            px = overlay_check(px)
        return px

    def _build_pixmap(self) -> QPixmap:
        """Pre-render the whole card into a QPixmap so paintEvent is trivial."""
        px = QPixmap(CARD_W, CARD_H)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        # Card background
        p.setBrush(QColor(COL_SURFACE))
        p.setPen(QPen(QColor(COL_BORDER), 1.5))
        p.drawRoundedRect(2, 2, CARD_W-4, CARD_H-4, 10, 10)

        # Icon (centered horizontally, near top)
        icon = self._get_icon()
        ix = (CARD_W - ICON_S) // 2
        iy = 10
        # Clip icon to rounded rect
        icon_clip = QPixmap(ICON_S, ICON_S)
        icon_clip.fill(Qt.transparent)
        cp = QPainter(icon_clip)
        cp.setRenderHint(QPainter.Antialiasing)
        cp.setBrush(QBrush(icon))
        cp.setPen(Qt.NoPen)
        cp.drawRoundedRect(0, 0, ICON_S, ICON_S, int(ICON_S*0.18), int(ICON_S*0.18))
        cp.end()
        p.drawPixmap(ix, iy, icon_clip)

        # Name label
        p.setPen(QColor(COL_TEXT))
        f = QFont("Segoe UI", 9)
        p.setFont(f)
        name = self.entry.name
        if len(name) > 13:
            name = name[:12] + "…"
        text_rect = px.rect().adjusted(4, ICON_S + 14, -4, -4)
        p.drawText(text_rect, Qt.AlignTop | Qt.AlignHCenter | Qt.TextWordWrap, name)

        p.end()
        return px

    def _build_hover_pixmap(self) -> QPixmap:
        px = QPixmap(self._pixmap)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(COL_ACCENT), 2))
        p.drawRoundedRect(2, 2, CARD_W-4, CARD_H-4, 10, 10)
        p.end()
        return px

    def refresh(self):
        self._pixmap = self._build_pixmap()
        self.update()

    def update_icon(self, px: QPixmap):
        self.entry.icon_pixmap = px
        self.refresh()

    def refresh_installed(self, installed: dict):
        self.installed = installed
        self.refresh()

    # ── events ────────────────────────────────────────────────────────────────

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.entry)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._hovered:
            # Draw hover variant inline (border only, don't rebuild full pixmap)
            p.drawPixmap(0, 0, self._pixmap)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(COL_ACCENT), 2))
            p.drawRoundedRect(2, 2, CARD_W-4, CARD_H-4, 10, 10)
        else:
            p.drawPixmap(0, 0, self._pixmap)


# ─── Category section ─────────────────────────────────────────────────────────

class CategorySection(QWidget):
    def __init__(self, category: str, parent=None):
        super().__init__(parent)
        self.category  = category
        self.cards: list[PackageCard] = []
        self._collapsed = False
        self._cols = 8

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 8)
        root.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        self.toggle_btn = QToolButton()
        self.toggle_btn.setObjectName("collapse")
        self.toggle_btn.setText("▾")
        self.toggle_btn.setFixedSize(22, 22)
        self.toggle_btn.clicked.connect(self._toggle)

        cat_lbl = QLabel(category.upper())
        cat_lbl.setStyleSheet(f"color:{COL_MUTED};font-size:11px;font-weight:700;letter-spacing:1.5px;background:transparent;")

        self.count_lbl = QLabel("0")
        self.count_lbl.setStyleSheet(f"color:{COL_MUTED};font-size:11px;background:transparent;")

        hdr.addWidget(self.toggle_btn)
        hdr.addWidget(cat_lbl)
        hdr.addWidget(self.count_lbl)
        hdr.addStretch()
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{COL_BORDER}; border:none; max-height:1px;")
        root.addWidget(sep)

        self.grid_widget = QWidget()
        self.grid_widget.setStyleSheet("background:transparent;")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 6, 0, 6)
        self.grid_layout.setSpacing(8)
        root.addWidget(self.grid_widget)

    def add_card(self, card: PackageCard):
        self.cards.append(card)
        # Append directly at the next grid position
        n = len(self.cards) - 1
        cols = max(1, self._cols)
        self.grid_layout.addWidget(card, n // cols, n % cols)
        card.show()
        self.count_lbl.setText(str(len(self.cards)))

    def _relayout(self):
        # Remove from grid without touching parent or visibility
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                self.grid_layout.removeWidget(item.widget())

        visible = [c for c in self.cards if not c.isHidden()]
        cols = max(1, self._cols)
        for i, card in enumerate(visible):
            self.grid_layout.addWidget(card, i // cols, i % cols)
            card.show()

    def set_columns(self, cols: int):
        if cols != self._cols:
            self._cols = cols
            self._relayout()

    def _toggle(self):
        self._collapsed = not self._collapsed
        self.grid_widget.setVisible(not self._collapsed)
        self.toggle_btn.setText("▸" if self._collapsed else "▾")

    def filter(self, text: str) -> bool:
        t = text.lower()
        any_visible = False
        for card in self.cards:
            match = (not t) or (t in card.entry.name.lower()) or \
                    any(t in c.lower() for c in card.entry.categories)
            # hide/show without reparenting
            card.setVisible(match)
            if match:
                any_visible = True
        self._relayout()
        self.setVisible(any_visible)
        return any_visible


# ─── Screenshot carousel ──────────────────────────────────────────────────────

class ScreenshotCarousel(QWidget):
    def __init__(self, urls: list, parent=None):
        super().__init__(parent)
        self.urls = urls
        self._current = 0
        self._cache: dict[int, QPixmap] = {}   # full-resolution pixmaps
        self._fetchers: list[IconFetcher] = []

        self.setMinimumHeight(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setMinimumHeight(300)
        self.img_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img_label.setStyleSheet(
            f"background:{COL_SURFACE};border-radius:8px;color:{COL_MUTED};"
        )
        lay.addWidget(self.img_label, 1)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("‹")
        self.prev_btn.setFixedSize(34, 34)
        self.next_btn = QPushButton("›")
        self.next_btn.setFixedSize(34, 34)
        self.counter  = QLabel("–")
        self.counter.setStyleSheet(f"color:{COL_MUTED};background:transparent;")
        self.counter.setAlignment(Qt.AlignCenter)
        nav.addStretch()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.counter)
        nav.addWidget(self.next_btn)
        nav.addStretch()
        lay.addLayout(nav)

        self.prev_btn.clicked.connect(self._prev)
        self.next_btn.clicked.connect(self._next)

        if urls:
            self._load(0)
            self._update_counter()
        else:
            self.img_label.setText("No screenshots")

    def _load(self, idx: int):
        if idx in self._cache:
            self._show(idx)
            return
        self.img_label.setText("Loading…")
        f = IconFetcher(str(idx), self.urls[idx])
        f.done.connect(lambda _, px, i=idx: self._on_loaded(i, px))
        self._fetchers.append(f)
        f.start()

    def _on_loaded(self, idx: int, px: QPixmap):
        self._cache[idx] = px   # store full-res
        if idx == self._current:
            self._show(idx)

    def _show(self, idx: int):
        px = self._cache.get(idx, QPixmap())
        if px.isNull():
            self.img_label.setText("Image unavailable")
        else:
            # Scale to the actual label dimensions at display time
            w = self.img_label.width()  or 500
            h = self.img_label.height() or 300
            self.img_label.setPixmap(
                px.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Re-render current image at new size
        if self._current in self._cache:
            self._show(self._current)

    def _prev(self):
        if self.urls:
            self._current = (self._current - 1) % len(self.urls)
            self._load(self._current)
            self._update_counter()

    def _next(self):
        if self.urls:
            self._current = (self._current + 1) % len(self.urls)
            self._load(self._current)
            self._update_counter()

    def _update_counter(self):
        if self.urls:
            self.counter.setText(f"{self._current+1} / {len(self.urls)}")


# ─── Detail dialog ────────────────────────────────────────────────────────────

class PackageDetailDialog(QDialog):
    install_requested   = pyqtSignal(str)
    uninstall_requested = pyqtSignal(str)
    update_requested    = pyqtSignal(str)

    def __init__(self, entry: PackageEntry, installed: dict, parent=None):
        super().__init__(parent)
        self.entry     = entry
        self.installed = installed
        self._pypi_fetcher = None

        self.setWindowTitle(entry.name)
        self.setMinimumSize(560, 680)
        self.setModal(True)
        self._build_ui()
        self._fetch()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(0)

        # Action bar
        abar = QHBoxLayout()
        self.btn_install   = QPushButton("Install")
        self.btn_uninstall = QPushButton("Uninstall")
        self.btn_uninstall.setObjectName("danger")
        self.btn_update    = QPushButton("Update")
        self.btn_update.setObjectName("secondary")
        btn_close = QPushButton("✕")
        btn_close.setObjectName("secondary")
        btn_close.setFixedSize(36, 36)
        btn_close.clicked.connect(self.close)
        for b in (self.btn_install, self.btn_uninstall, self.btn_update):
            b.setFixedHeight(36)
            abar.addWidget(b)
        abar.addStretch()
        abar.addWidget(btn_close)
        root.addLayout(abar)
        root.addSpacing(18)

        self.btn_install.clicked.connect(lambda: self.install_requested.emit(self.entry.name))
        self.btn_uninstall.clicked.connect(lambda: self.uninstall_requested.emit(self.entry.name))
        self.btn_update.clicked.connect(lambda: self.update_requested.emit(self.entry.name))

        # Scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        cw = QWidget()
        scroll.setWidget(cw)
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(14)

        # Header
        hdr = QHBoxLayout()
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(72, 72)
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        hdr.addWidget(self.icon_lbl)
        hdr.addSpacing(16)
        tc = QVBoxLayout()
        self.title_lbl   = QLabel(self.entry.name)
        self.title_lbl.setStyleSheet("font-size:20px;font-weight:700;background:transparent;")
        self.version_lbl = QLabel("Fetching metadata…")
        self.version_lbl.setStyleSheet(f"color:{COL_MUTED};font-size:12px;background:transparent;")
        tc.addWidget(self.title_lbl)
        tc.addWidget(self.version_lbl)
        tc.addStretch()
        hdr.addLayout(tc)
        hdr.addStretch()
        lay.addLayout(hdr)

        self.summary_lbl = QLabel("…")
        self.summary_lbl.setWordWrap(True)
        self.summary_lbl.setStyleSheet("font-size:14px;background:transparent;")
        lay.addWidget(self.summary_lbl)

        self.carousel = ScreenshotCarousel(self.entry.screenshots)
        lay.addWidget(self.carousel)

        self.meta_layout = QGridLayout()
        self.meta_layout.setColumnStretch(1, 1)
        self.meta_layout.setHorizontalSpacing(16)
        self.meta_layout.setVerticalSpacing(10)
        lay.addLayout(self.meta_layout)
        lay.addStretch()

        self._update_icon()
        self._refresh_buttons()

    def _update_icon(self):
        px = self.entry.icon_pixmap
        s = 96
        if px is None or px.isNull():
            px = make_placeholder_icon(self.entry.name[0] if self.entry.name else "?", s)
        else:
            if px.width() > s * 2 or px.height() > s * 2:
                px = px.scaled(s * 2, s * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            px = px.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if is_installed(self.entry.name, self.installed):
            px = overlay_check(px)
        self.icon_lbl.setFixedSize(s, s)
        self.icon_lbl.setPixmap(px)

    def _meta_row(self, row: int, key: str, value: str, bold=False):
        kl = QLabel(key)
        kl.setStyleSheet(f"color:{COL_MUTED};background:transparent;")
        kl.setAlignment(Qt.AlignTop | Qt.AlignRight)
        vl = QLabel(value)
        vl.setWordWrap(True)
        vl.setOpenExternalLinks(True)
        vl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        vl.setStyleSheet(
            ("font-weight:700;" if bold else "") +
            f"background:transparent;color:{COL_TEXT};"
        )
        self.meta_layout.addWidget(kl, row, 0)
        self.meta_layout.addWidget(vl, row, 1)

    def _fetch(self):
        self._pypi_fetcher = PyPIFetcher(self.entry.name)
        self._pypi_fetcher.done.connect(self._on_pypi)
        self._pypi_fetcher.start()

    def _on_pypi(self, data: dict):
        info = data.get("info", {})
        project_urls = info.get("project_urls") or {}

        self.title_lbl.setText(info.get("name", self.entry.name))
        self.version_lbl.setText(f"v{info.get('version', '?')}")
        self.summary_lbl.setText(info.get("summary", "No summary available."))

        # Clear
        while self.meta_layout.count():
            item = self.meta_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        row = 0
        iv = get_installed_version(self.entry.name, self.installed)
        inst_text = f"✔  {iv}" if iv else "Not installed"
        self._meta_row(row, "Installed", inst_text, bold=bool(iv)); row += 1

        for label, key in [("Author", "author"), ("Email", "author_email"),
                            ("License", "license"), ("Requires Python", "requires_python")]:
            if info.get(key):
                self._meta_row(row, label, info[key]); row += 1

        if info.get("home_page"):
            u = info["home_page"]
            self._meta_row(row, "Homepage", f'<a href="{u}" style="color:{COL_ACCENT2}">{u}</a>'); row += 1

        if project_urls:
            links = "  ".join(
                f'<a href="{v}" style="color:{COL_ACCENT2}">{k}</a>'
                for k, v in project_urls.items() if v
            )
            self._meta_row(row, "Links", links); row += 1

        self._refresh_buttons()

    def _refresh_buttons(self):
        inst = is_installed(self.entry.name, self.installed)
        self.btn_install.setVisible(not inst)
        self.btn_uninstall.setVisible(inst)
        self.btn_update.setVisible(inst)

    def refresh_installed(self, installed: dict):
        self.installed = installed
        self._update_icon()
        self._refresh_buttons()


# ─── Main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Package Manager")
        self.resize(1100, 740)
        self.setMinimumSize(700, 500)

        self._installed: dict = load_installed()
        self._packages:  list = []
        self._cards:     dict = {}
        self._sections:  dict = {}
        self._icon_fetchers: list = []
        self._active_dialog = None
        self._pipx_runner   = None

        self._build_ui()
        self._start_loading()

    def _build_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(20, 16, 20, 12)
        root.setSpacing(10)

        # Title
        title = QLabel("📦  Package Manager")
        title.setStyleSheet("font-size:20px;font-weight:700;background:transparent;")
        root.addWidget(title)

        # Search
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search by name or category…")
        self.search_box.setFixedHeight(38)
        self.search_box.textChanged.connect(self._filter)
        root.addWidget(self.search_box)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        root.addWidget(self.progress_bar)

        # Scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.scroll)

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet(f"background:{COL_BG};")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 8, 8, 8)
        self.content_layout.setSpacing(4)
        self.content_layout.addStretch()
        self.scroll.setWidget(self.content_widget)

        # Status
        self.status_lbl = QLabel("Loading repositories…")
        self.status_lbl.setStyleSheet(f"color:{COL_MUTED};font-size:12px;background:transparent;")
        root.addWidget(self.status_lbl)

    def _start_loading(self):
        self.progress_bar.setRange(0, 0)
        self._loader = RepositoryLoader()
        self._loader.progress.connect(self._on_progress)
        self._loader.package_found.connect(self._on_package)
        self._loader.finished_loading.connect(self._on_loaded)
        self._loader.start()

    def _on_progress(self, cur: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(cur)

    def _on_package(self, entry: PackageEntry):
        self._packages.append(entry)

        for cat in (entry.categories or ["Any"]):
            if cat not in self._sections:
                section = CategorySection(cat)
                self._sections[cat] = section
                idx = self.content_layout.count() - 1
                self.content_layout.insertWidget(idx, section)

            # Each category gets its own card instance (widget can only have one parent)
            card = PackageCard(entry, self._installed)
            card.clicked.connect(self._open_detail)
            # Store only first card per name for icon/installed updates
            if entry.name not in self._cards:
                self._cards[entry.name] = []
            self._cards[entry.name].append(card)
            self._sections[cat].add_card(card)

        if entry.icon_url:
            f = IconFetcher(entry.name, entry.icon_url)
            f.done.connect(self._on_icon)
            self._icon_fetchers.append(f)
            f.start()

    def _on_loaded(self):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.status_lbl.setText(f"{len(self._packages)} packages  •  click a card to view details")
        self._recalc_cols()

    def _on_icon(self, name: str, px: QPixmap):
        for card in self._cards.get(name, []):
            card.update_icon(px)

    def _filter(self, text: str):
        for s in self._sections.values():
            s.filter(text)

    def showEvent(self, e):
        super().showEvent(e)
        self._recalc_cols()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._recalc_cols()

    def _recalc_cols(self):
        w = self.scroll.viewport().width() - 16
        cols = max(2, w // (CARD_W + 8))
        for s in self._sections.values():
            s.set_columns(cols)

    def _open_detail(self, entry: PackageEntry):
        dlg = PackageDetailDialog(entry, self._installed, self)
        self._active_dialog = dlg
        dlg.install_requested.connect(self._install)
        dlg.uninstall_requested.connect(self._uninstall)
        dlg.update_requested.connect(self._update_pkg)
        dlg.exec_()
        self._active_dialog = None

    def _run_pipx(self, args: list, callback):
        self._pipx_runner = PipxRunner(args)
        self._pipx_runner.result.connect(callback)
        self._pipx_runner.start()
        self.status_lbl.setText(f"Running: pipx {' '.join(args)}")

    def _install(self, name: str):
        self._run_pipx(["install", name], lambda ok, msg: self._after_install(name, ok, msg))

    def _after_install(self, name: str, ok: bool, msg: str):
        if ok:
            self._installed[name] = {"version": "?", "executables": []}
            save_installed(self._installed)
            for card in self._cards.get(name, []):
                card.refresh_installed(self._installed)
            self.status_lbl.setText(f"✔  {name} installed")
            QMessageBox.information(self, "Installed", f"{name} installed successfully.")
        else:
            QMessageBox.critical(self, "Error", f"Failed to install {name}:\n{msg}")
            self.status_lbl.setText("Error during install")
        if self._active_dialog:
            self._active_dialog.refresh_installed(self._installed)

    def _uninstall(self, name: str):
        if QMessageBox.question(self, "Uninstall", f"Uninstall {name}?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._run_pipx(["uninstall", name], lambda ok, msg: self._after_uninstall(name, ok, msg))

    def _after_uninstall(self, name: str, ok: bool, msg: str):
        if ok:
            self._installed.pop(name, None)
            save_installed(self._installed)
            for card in self._cards.get(name, []):
                card.refresh_installed(self._installed)
            self.status_lbl.setText(f"✔  {name} uninstalled")
            QMessageBox.information(self, "Uninstalled", f"{name} uninstalled.")
        else:
            QMessageBox.critical(self, "Error", f"Failed to uninstall {name}:\n{msg}")
            self.status_lbl.setText("Error during uninstall")
        if self._active_dialog:
            self._active_dialog.refresh_installed(self._installed)

    def _update_pkg(self, name: str):
        self._run_pipx(["upgrade", name], lambda ok, msg: self._after_update(name, ok, msg))

    def _after_update(self, name: str, ok: bool, msg: str):
        if ok:
            self.status_lbl.setText(f"✔  {name} updated")
            QMessageBox.information(self, "Updated", f"{name} updated.")
        else:
            QMessageBox.critical(self, "Error", f"Failed to update {name}:\n{msg}")
            self.status_lbl.setText("Error during update")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Package Manager")
    app.setStyleSheet(STYLE_SHEET)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
