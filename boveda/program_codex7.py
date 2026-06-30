#!/usr/bin/env python3
"""Small PyQt5/pipx package browser driven by repository JSON files.

Set REPOSITORIES_PATH (and optionally INSTALLED_FILEPATH) before running, e.g.:
    REPOSITORIES_PATH=./repositories python3 package_browser.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

from PyQt5.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

REPOSITORIES_PATH = Path(os.environ.get("REPOSITORIES_PATH", "repositories"))
INSTALLED_FILEPATH = Path(os.environ.get("INSTALLED_FILEPATH", "installed.json"))
DEFAULT_ICON_SIZE = 64


def fetch_json(url: str) -> dict:
    try:
        request = Request(url, headers={"User-Agent": "PyQt5PackageBrowser/1.0"})
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def fetch_image_data(url: str) -> bytes:
    if not url:
        return b""
    try:
        request = Request(url, headers={"User-Agent": "PyQt5PackageBrowser/1.0"})
        with urlopen(request, timeout=12) as response:
            return response.read()
    except Exception:
        return b""


def pixmap_from_data(data: bytes, size: int = DEFAULT_ICON_SIZE) -> QPixmap:
    if not data:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        return pixmap

    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        return QPixmap()

    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def load_installed_packages() -> dict:
    if not INSTALLED_FILEPATH.exists():
        return {}
    try:
        return json.loads(INSTALLED_FILEPATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_installed_packages(data: dict) -> None:
    INSTALLED_FILEPATH.write_text(json.dumps(data, indent=4, sort_keys=True), encoding="utf-8")


def installed_version(package_name: str) -> str:
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:
        return ""


def get_console_scripts(package_name: str) -> List[str]:
    try:
        from importlib.metadata import distribution

        dist = distribution(package_name)
        return sorted(ep.name for ep in dist.entry_points if ep.group == "console_scripts")
    except Exception:
        return []


@dataclass
class RepositoryPackage:
    name: str
    icon: str = ""
    screenshots: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=lambda: ["Any"])
    enabled: bool = True
    repository: str = ""
    icon_data: bytes = b""
    screenshot_data: List[bytes] = field(default_factory=list)
    pypi_data: dict = field(default_factory=dict)

    def summary(self) -> str:
        info = self.pypi_data.get("info", {}) if self.pypi_data else {}
        return info.get("summary") or "Sem summary disponível"


class WorkerSignals(QObject):
    progress = pyqtSignal(int, int, str)
    packages_loaded = pyqtSignal(list, dict)
    package_info_loaded = pyqtSignal(object, dict, object, list)
    command_finished = pyqtSignal(str, bool, str)


class RepositoryLoader(QRunnable):
    def __init__(self, repository_path: Path):
        super().__init__()
        self.repository_path = repository_path
        self.signals = WorkerSignals()

    def run(self) -> None:
        packages: List[RepositoryPackage] = []
        files = sorted(self.repository_path.glob("*.json")) if self.repository_path.exists() else []
        installed = load_installed_packages()
        repository_total = max(len(files), 1)
        for index, file_path in enumerate(files, start=1):
            self.signals.progress.emit(index, repository_total, f"Lendo {file_path.name}")
            try:
                repository = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            repo_name = repository.get("name", file_path.stem)
            for item in repository.get("packages", []):
                if not item.get("name") or item.get("enabled", True) is False:
                    continue
                categories = item.get("categories") or ["Any"]
                if isinstance(categories, str):
                    categories = [categories]
                packages.append(
                    RepositoryPackage(
                        name=item["name"],
                        icon=item.get("icon", ""),
                        screenshots=item.get("screenshots", []) or [],
                        categories=categories or ["Any"],
                        enabled=item.get("enabled", True),
                        repository=repo_name,
                    )
                )

        asset_total = max(len(packages), 1)
        for index, package in enumerate(packages, start=1):
            self.signals.progress.emit(index, asset_total, f"Baixando dados de {package.name}")
            package.pypi_data = fetch_json(f"https://pypi.org/pypi/{package.name}/json")
            package.icon_data = fetch_image_data(package.icon)
            package.screenshot_data = [fetch_image_data(url) for url in package.screenshots]

        self.signals.packages_loaded.emit(packages, installed)


class PackageInfoLoader(QRunnable):
    def __init__(self, package: RepositoryPackage):
        super().__init__()
        self.package = package
        self.signals = WorkerSignals()

    def run(self) -> None:
        data = self.package.pypi_data or fetch_json(f"https://pypi.org/pypi/{self.package.name}/json")
        self.package.pypi_data = data
        self.signals.package_info_loaded.emit(self.package, data, self.package.icon_data, self.package.screenshot_data)


class PipxCommand(QRunnable):
    def __init__(self, action: str, package_name: str):
        super().__init__()
        self.action = action
        self.package_name = package_name
        self.signals = WorkerSignals()

    def run(self) -> None:
        command = ["pipx", self.action, self.package_name]
        try:
            completed = subprocess.run(command, check=True, text=True, capture_output=True)
            message = completed.stdout or completed.stderr or "OK"
            installed = load_installed_packages()
            if self.action in {"install", "upgrade"}:
                installed[self.package_name] = {
                    "version": installed_version(self.package_name),
                    "executables": get_console_scripts(self.package_name),
                }
            elif self.action == "uninstall":
                installed.pop(self.package_name, None)
            save_installed_packages(installed)
            self.signals.command_finished.emit(self.package_name, True, message)
        except Exception as exc:
            self.signals.command_finished.emit(self.package_name, False, str(exc))


class CategorySection(QWidget):
    def __init__(self, category: str):
        super().__init__()
        self.category = category
        self.button = QToolButton(text=f"▾  {category}", checkable=True, checked=True)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.clicked.connect(self.toggle)
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setIconSize(QSize(DEFAULT_ICON_SIZE, DEFAULT_ICON_SIZE))
        self.list_widget.setGridSize(QSize(128, 108))
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setWrapping(True)
        self.list_widget.setSpacing(12)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setMinimumHeight(118)
        layout = QVBoxLayout(self)
        layout.addWidget(self.button)
        layout.addWidget(self.list_widget)

    def toggle(self) -> None:
        expanded = self.button.isChecked()
        self.button.setText(("▾  " if expanded else "▸  ") + self.category)
        self.list_widget.setVisible(expanded)
        if expanded:
            self.adjust_height()

    def adjust_height(self) -> None:
        count = self.list_widget.count()
        if count == 0:
            self.list_widget.setFixedHeight(0)
            return

        cell_width = max(self.list_widget.gridSize().width(), 1)
        cell_height = max(self.list_widget.gridSize().height(), 1)
        available_width = max(self.list_widget.viewport().width(), self.width(), cell_width)
        columns = max(available_width // cell_width, 1)
        rows = (count + columns - 1) // columns
        self.list_widget.setFixedHeight(rows * cell_height + 8)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.adjust_height()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyPI Package Browser")
        self.resize(1050, 720)
        self.thread_pool = QThreadPool.globalInstance()
        self.packages: List[RepositoryPackage] = []
        self.installed: Dict[str, dict] = {}
        self.sections: Dict[str, CategorySection] = {}
        self.current_package: Optional[RepositoryPackage] = None
        self.screenshots: List[QPixmap] = []
        self.screenshot_index = 0
        self._build_ui()
        self.load_repositories()

    def _build_ui(self) -> None:
        root = QWidget()
        main = QVBoxLayout(root)
        self.search = QLineEdit(placeholderText="Buscar por nome ou categoria...")
        self.search.textChanged.connect(self.populate_packages)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.stack = QStackedWidget()
        self.list_page = QWidget()
        self.list_layout = QVBoxLayout(self.list_page)
        self.list_layout.addWidget(self.search)
        self.list_layout.addWidget(self.progress)
        self.scroll = QScrollArea(widgetResizable=True)
        self.category_container = QWidget()
        self.category_layout = QVBoxLayout(self.category_container)
        self.category_layout.addStretch()
        self.scroll.setWidget(self.category_container)
        self.list_layout.addWidget(self.scroll)
        self.detail_page = self._build_detail_page()
        self.stack.addWidget(self.list_page)
        self.stack.addWidget(self.detail_page)
        main.addWidget(self.stack)
        self.setCentralWidget(root)

    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        self.back_button = QPushButton("← Voltar")
        self.back_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.list_page))
        self.install_button = QPushButton("Install")
        self.install_button.clicked.connect(self.install_or_uninstall)
        self.update_button = QPushButton("Update")
        self.update_button.clicked.connect(lambda: self.run_pipx("upgrade"))
        toolbar.addWidget(self.back_button)
        toolbar.addStretch()
        toolbar.addWidget(self.install_button)
        toolbar.addWidget(self.update_button)
        header = QHBoxLayout()
        self.detail_icon = QLabel()
        self.detail_icon.setFixedSize(80, 80)
        self.title = QLabel()
        self.title.setFont(QFont("Sans", 22, QFont.Bold))
        header.addWidget(self.detail_icon)
        header.addWidget(self.title, 1)
        self.summary_metadata = QLabel()
        self.summary_metadata.setTextFormat(Qt.RichText)
        self.summary_metadata.setWordWrap(True)
        self.metadata = QLabel()
        self.metadata.setTextFormat(Qt.RichText)
        self.metadata.setWordWrap(True)
        self.screenshot_label = QLabel(alignment=Qt.AlignCenter)
        self.screenshot_label.setMinimumHeight(260)
        shot_buttons = QHBoxLayout()
        previous_button = QPushButton("‹")
        next_button = QPushButton("›")
        previous_button.clicked.connect(lambda: self.change_screenshot(-1))
        next_button.clicked.connect(lambda: self.change_screenshot(1))
        shot_buttons.addStretch(); shot_buttons.addWidget(previous_button); shot_buttons.addWidget(next_button); shot_buttons.addStretch()
        layout.addLayout(toolbar)
        layout.addLayout(header)
        layout.addWidget(self.summary_metadata)
        layout.addWidget(self.screenshot_label)
        layout.addLayout(shot_buttons)
        layout.addWidget(self.metadata)
        layout.addStretch()
        return page

    def load_repositories(self) -> None:
        self.progress.setVisible(True)
        self.progress.setRange(0, 1)
        worker = RepositoryLoader(REPOSITORIES_PATH)
        worker.signals.progress.connect(lambda value, total, text: (self.progress.setRange(0, total), self.progress.setValue(value), self.progress.setFormat(text)))
        worker.signals.packages_loaded.connect(self.on_packages_loaded)
        self.thread_pool.start(worker)

    def on_packages_loaded(self, packages: list, installed: dict) -> None:
        self.packages = packages
        self.installed = installed
        self.progress.setVisible(False)
        self.populate_packages()

    def populate_packages(self) -> None:
        while self.category_layout.count() > 1:
            item = self.category_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.sections.clear()
        query = self.search.text().strip().lower()
        packages_by_category: Dict[str, List[RepositoryPackage]] = {}

        for package in self.packages:
            if query and query not in package.name.lower() and not any(query in c.lower() for c in package.categories):
                continue
            for category in package.categories:
                packages_by_category.setdefault(category, []).append(package)

        for category in sorted(packages_by_category, key=str.lower):
            section = CategorySection(category)
            section.list_widget.itemClicked.connect(self.open_package)
            self.sections[category] = section
            self.category_layout.insertWidget(self.category_layout.count() - 1, section)

            for package in sorted(packages_by_category[category], key=lambda p: p.name.lower()):
                item = QListWidgetItem(QIcon(pixmap_from_data(package.icon_data)), package.name)
                item.setData(Qt.UserRole, package)
                item.setToolTip(package.summary())
                if package.name in self.installed:
                    item.setText(f"✓ {package.name}")
                    item.setBackground(QColor("#dff7e8"))
                    item.setToolTip(f"{package.summary()}\n\nInstalado")
                section.list_widget.addItem(item)
            section.adjust_height()

    def open_package(self, item: QListWidgetItem) -> None:
        package = item.data(Qt.UserRole)
        self.current_package = package
        self.stack.setCurrentWidget(self.detail_page)
        self.title.setText(package.name)
        self.summary_metadata.setText("Carregando metadados...")
        self.metadata.clear()
        self.screenshot_label.clear()
        worker = PackageInfoLoader(package)
        worker.signals.package_info_loaded.connect(self.on_package_info_loaded)
        self.thread_pool.start(worker)

    def on_package_info_loaded(self, package: RepositoryPackage, data: dict, icon: bytes, screenshots: list) -> None:
        info = data.get("info", {}) if data else {}
        project_urls = info.get("project_urls") or {}
        name = info.get("name") or package.name
        self.title.setText(name)
        self.detail_icon.setPixmap(pixmap_from_data(icon, 80))
        self.screenshots = []
        for image in screenshots:
            if not image:
                continue
            pixmap = pixmap_from_data(image, 760)
            if not pixmap.isNull():
                self.screenshots.append(pixmap)
        self.screenshot_index = 0
        self.show_screenshot()
        installed_data = self.installed.get(package.name)
        installed_text = f"installed + version: {installed_data.get('version', '') or installed_version(package.name) or 'unknown'}" if installed_data else "not installed"
        urls = "<br>".join(f"&nbsp;&nbsp;{key}: <a href='{value}'>{value}</a>" for key, value in project_urls.items()) or "-"
        self.summary_metadata.setText(
            f"<p><b>Summary:</b> {info.get('summary') or '-'}</p>"
            f"<p><b>Version:</b> {info.get('version') or '-'}</p>"
        )
        self.metadata.setText(
            f"<p><b>Author:</b> {info.get('author') or '-'}</p>"
            f"<p><b>email:</b> {info.get('author_email') or '-'}</p>"
            f"<p><b>Licença:</b> {info.get('license') or '-'}</p>"
            f"<p><b>homepage:</b> <a href='{info.get('home_page') or '#'}'>{info.get('home_page') or '-'}</a></p>"
            f"<p><b>project_urls:</b><br>{urls}</p>"
            f"<p><b>{installed_text}</b></p>"
        )
        self.summary_metadata.setOpenExternalLinks(True)
        self.metadata.setOpenExternalLinks(True)
        self.install_button.setText("Uninstall" if installed_data else "Install")
        self.update_button.setEnabled(bool(installed_data))

    def show_screenshot(self) -> None:
        if not self.screenshots:
            self.screenshot_label.setPixmap(QPixmap())
            self.screenshot_label.setText("Sem screenshots")
            return
        pixmap = self.screenshots[self.screenshot_index].scaled(760, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.screenshot_label.clear()
        self.screenshot_label.setPixmap(pixmap)

    def change_screenshot(self, step: int) -> None:
        if self.screenshots:
            self.screenshot_index = (self.screenshot_index + step) % len(self.screenshots)
            self.show_screenshot()

    def install_or_uninstall(self) -> None:
        if self.current_package:
            self.run_pipx("uninstall" if self.current_package.name in self.installed else "install")

    def run_pipx(self, action: str) -> None:
        if not self.current_package:
            return
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        worker = PipxCommand(action, self.current_package.name)
        worker.signals.command_finished.connect(self.on_command_finished)
        self.thread_pool.start(worker)

    def on_command_finished(self, package_name: str, ok: bool, message: str) -> None:
        self.installed = load_installed_packages()
        self.install_button.setEnabled(True)
        self.update_button.setEnabled(package_name in self.installed)
        self.install_button.setText("Uninstall" if package_name in self.installed else "Install")
        self.populate_packages()
        QMessageBox.information(self, "pipx", message if ok else f"Erro: {message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

