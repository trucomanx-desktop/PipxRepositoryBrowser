#!/usr/bin/env python3
"""Small PyQt5/pipx package browser driven by repository JSON files.

"""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import signal
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

from email.utils import parseaddr

from PyQt5.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QSizePolicy, 
    QAction
)


import pipx_repository_browser.about as about
import pipx_repository_browser.modules.configure as configure 
from pipx_repository_browser.modules.resources import resource_path

from pipx_repository_browser.modules.wabout    import show_about_window
from pipx_repository_browser.desktop import create_desktop_file, create_desktop_directory, create_desktop_menu




# ---------- Path to config file ----------
CONFIG_PATH = os.path.join( os.path.expanduser("~"),
                            ".config", 
                            about.__package__, 
                            "config.json" )

DEFAULT_CONTENT={   
    "toolbar_directory": "Directory",
    "toolbar_directory_tooltip": "Open the repository directory",
    "toolbar_refresh": "Refresh",
    "toolbar_refresh_tooltip": "Reload repository and package data",
    "toolbar_configure": "Configure",
    "toolbar_configure_tooltip": "Open the program GUI configuration JSON file",
    "toolbar_about": "About",
    "toolbar_about_tooltip": "About the program",
    "toolbar_coffee": "Coffee",
    "toolbar_coffee_tooltip": "Buy me a coffee (TrucomanX)",
    "toolbar_name": "Main",
    "pipx_home": "",
    "status_pipx_home": "pipx home: {path}",
    "status_category_saved": "Moved {package} to {category}",
    "error_save_category": "Could not save category change: {error}",
    "label_launch_apps": "Launch applications",
    "launch_app_tooltip": "Launch {app}",
    "error_launch_app": "Could not launch {app}: {error}",
    "search_placeholder": "Search by name or category...",
    "button_back": "Back",
    "button_install": "Install",
    "button_uninstall": "Uninstall",
    "button_update": "Update",
    "button_previous_screenshot": "‹",
    "button_next_screenshot": "›",
    "screenshot_previous_tooltip": "Previous screenshot",
    "screenshot_next_tooltip": "Next screenshot",
    "category_default": "Any",
    "category_expanded": "▾  {category}",
    "category_collapsed": "▸  {category}",
    "package_summary_unavailable": "No summary available",
    "package_tooltip": "{summary}",
    "package_installed_tooltip": "{summary}\n\nInstalled",
    "package_installed_marker": "✓ {name}",
    "progress_reading_repository": "Reading {repository}",
    "progress_loading_package_data": "Loading package data for {package}",
    "text_loading_metadata": "Loading metadata...",
    "text_no_screenshots": "No screenshots available",
    "text_installed_version": "Installed · version: {version}",
    "text_installed_version_unknown": "Unknown",
    "text_not_installed": "Not installed",
    "label_summary": "Summary",
    "label_version": "Version",
    "label_author": "Author",
    "label_email": "Email",
    "label_license": "License",
    "label_homepage": "Homepage",
    "label_project_urls": "Project URLs",
    "metadata_value_unavailable": "—",
    "dialog_pipx_title": "pipx output",
    "dialog_pipx_error_title": "pipx error",
    "dialog_error_message": "Error: {message}",
    "command_success_fallback": "OK",
    "about_title": "About",
    "about_package": "Package",
    "about_program": "Program",
    "about_version": "Version",
    "about_author": "Author",
    "about_email": "Email",
    "about_source": "Source",
    "about_documentation": "Documentation",
    "about_funding": "Funding",
    "about_bugs": "Bugs",
    "button_ok": "OK",
    "window_width": 1024,
    "window_height": 800,
    "pkg_screenshot_size": 800,
    "pkg_icon_size": 80,
    "default_icon_size": 64
}

configure.verify_default_config(CONFIG_PATH,default_content=DEFAULT_CONTENT)

CONFIG=configure.load_config(CONFIG_PATH)


################################################################################

def get_author(author, author_email):
    author = (author or "").strip()
    author_email = (author_email or "").strip()

    # Caso author_email contenha "Some name <email>"
    parsed_name, parsed_email = parseaddr(author_email)

    # Prioriza o author explícito; se estiver vazio, usa o nome extraído
    author = author or parsed_name

    # Prioriza o email extraído; se não existir, mantém o valor original
    author_email = parsed_email or author_email

    return author, author_email

################################################################################

def _read_bashrc_pipx_home() -> str:
    """Read PIPX_HOME from an interactive Bash startup, once at app startup."""
    bashrc = Path.home() / ".bashrc"
    if not bashrc.is_file() or not shutil.which("bash"):
        return ""

    marker = "__PIPX_REPOSITORY_BROWSER_PIPX_HOME__="
    command = f'printf "\\n{marker}%s\\n" "${{PIPX_HOME-}}"'
    try:
        completed = subprocess.run(
            ["bash", "--noprofile", "-ic", command],
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(marker):
            return line[len(marker):].strip()
    return ""

def _resolve_pipx_environment() -> tuple[dict, str]:
    """Resolve pipx's home once and pass it to every pipx subprocess."""
    pipx_env = os.environ.copy()
    configured_home = str(CONFIG.get("pipx_home", "") or "").strip()
    pipx_home = os.path.expandvars(os.path.expanduser(configured_home)) if configured_home else ""
    pipx_home = pipx_home or pipx_env.get("PIPX_HOME", "").strip() or _read_bashrc_pipx_home()

    if pipx_home:
        pipx_home = os.path.expandvars(os.path.expanduser(pipx_home))
    else:
        try:
            completed = subprocess.run(
                ["pipx", "environment", "--value", "PIPX_HOME"],
                check=True,
                text=True,
                capture_output=True,
                timeout=10,
                env=pipx_env,
            )
            pipx_home = completed.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pipx_home = str(Path.home() / ".local" / "share" / "pipx")

    pipx_home = os.path.expandvars(os.path.expanduser(pipx_home))
    pipx_env["PIPX_HOME"] = pipx_home
    return pipx_env, pipx_home

PIPX_SUBPROCESS_ENV, PIPX_HOME = _resolve_pipx_environment()

# ---------------------------------------
REPOSITORIES_DIR = os.path.join( os.path.expanduser("~"),
                            ".config", 
                            about.__package__, 
                            "repositories" )


# ---------------------------------------
DEFAULT_REPOSITORY_URL = (
    "https://raw.githubusercontent.com/trucomanx-desktop/PipxRepositoryBrowser/"
    "refs/heads/main/src/pipx_repository_browser/data/TrucomanX.Repository.json"
)
DEFAULT_REPOSITORY_PATH = os.path.join(REPOSITORIES_DIR, "TrucomanX.Repository.json")


def _load_default_repository() -> dict:
    """Use the current upstream repository, falling back to the bundled copy offline."""
    try:
        request = Request(
            DEFAULT_REPOSITORY_URL,
            headers={"User-Agent": "PyQt5PackageBrowser/1.0"},
        )
        with urlopen(request, timeout=12) as response:
            content = json.loads(response.read().decode("utf-8"))
        if not isinstance(content, dict) or not isinstance(content.get("packages"), list):
            raise ValueError("Invalid repository JSON structure")
        return content
    except Exception:
        # Keep first launch usable without a network connection.
        with open(resource_path("data", "TrucomanX.Repository.json"), "r", encoding="utf-8") as f:
            return json.load(f)


DEFAULT_REPOSITORY_CONTENT = _load_default_repository()
repository_files = list(Path(REPOSITORIES_DIR).glob("*.json")) if os.path.isdir(REPOSITORIES_DIR) else []
if not repository_files or os.path.exists(DEFAULT_REPOSITORY_PATH):
    repository_content = configure.verify_default_config(
        DEFAULT_REPOSITORY_PATH,
        default_content=DEFAULT_REPOSITORY_CONTENT,
    )
    # verify_default_config merges dictionaries, but repository packages are a
    # list. Add upstream packages by name while retaining local entries/edits.
    local_packages = repository_content.get("packages", [])
    if isinstance(local_packages, list):
        known_names = {
            package.get("name")
            for package in local_packages
            if isinstance(package, dict) and package.get("name")
        }
        new_packages = [
            package
            for package in DEFAULT_REPOSITORY_CONTENT.get("packages", [])
            if isinstance(package, dict)
            and package.get("name")
            and package["name"] not in known_names
        ]
        if new_packages:
            repository_content["packages"].extend(new_packages)
            with open(DEFAULT_REPOSITORY_PATH, "w", encoding="utf-8") as f:
                json.dump(repository_content, f, ensure_ascii=False, indent=4)

# ---------------------------------------
INSTALLED_FILEPATH = os.path.join(  os.path.expanduser("~"),
                                    ".config", 
                                    about.__package__, 
                                    "installed.json" )

INSTALLED_FILEPATH = Path(INSTALLED_FILEPATH)

# ---------------------------------------


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


def pixmap_from_data(data: bytes, size: int = CONFIG["default_icon_size"]) -> QPixmap:
    if not data:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        return pixmap

    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        return QPixmap()

    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def normalize_package_name(package_name: str) -> str:
    return package_name.replace("_", "-").lower()


def pipx_path_value(value) -> str:
    if isinstance(value, dict) and value.get("__type__") == "Path":
        return str(value.get("__Path__") or "")
    return str(value) if isinstance(value, str) else ""


def load_pipx_installed_packages() -> dict:
    try:
        completed = subprocess.run(
            ["pipx", "list", "--json"],
            check=True,
            text=True,
            capture_output=True,
            timeout=20,
            env=PIPX_SUBPROCESS_ENV,
        )
        data = json.loads(completed.stdout or "{}")
    except Exception:
        return {}

    installed = {}
    for venv_name, venv_data in data.get("venvs", {}).items():
        metadata = venv_data.get("metadata", {}) if isinstance(venv_data, dict) else {}
        main_package = metadata.get("main_package", {}) if isinstance(metadata, dict) else {}
        package_name = main_package.get("package") or venv_name
        normalized_name = normalize_package_name(package_name)
        app_names = main_package.get("apps", []) or []
        app_paths = main_package.get("app_paths", []) or []
        executable_paths = {
            name: path
            for name, raw_path in zip(app_names, app_paths)
            if (path := pipx_path_value(raw_path))
        }
        installed[normalized_name] = {
            "name": package_name,
            "version": main_package.get("package_version", ""),
            "executables": sorted(app_names),
            "executable_paths": executable_paths,
        }
    return installed


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
    categories: List[str] = field(default_factory=lambda: [CONFIG["category_default"]])
    enabled: bool = True
    repository: str = ""
    source_file: str = ""
    icon_data: bytes = b""
    screenshot_data: List[bytes] = field(default_factory=list)
    pypi_data: dict = field(default_factory=dict)

    def summary(self) -> str:
        info = self.pypi_data.get("info", {}) if self.pypi_data else {}
        return info.get("summary") or CONFIG["package_summary_unavailable"]


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
        installed = load_pipx_installed_packages()
        save_installed_packages(installed)
        repository_total = max(len(files), 1)
        for index, file_path in enumerate(files, start=1):
            self.signals.progress.emit(index, repository_total, CONFIG["progress_reading_repository"].format(repository=file_path.name))
            try:
                repository = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            repo_name = repository.get("name", file_path.stem)
            for item in repository.get("packages", []):
                if not item.get("name") or item.get("enabled", True) is False:
                    continue
                categories = item.get("categories") or [CONFIG["category_default"]]
                if isinstance(categories, str):
                    categories = [categories]
                packages.append(
                    RepositoryPackage(
                        name=item["name"],
                        icon=item.get("icon", ""),
                        screenshots=item.get("screenshots", []) or [],
                        categories=categories or [CONFIG["category_default"]],
                        enabled=item.get("enabled", True),
                        repository=repo_name,
                        source_file=str(file_path),
                    )
                )

        asset_total = max(len(packages), 1)
        for index, package in enumerate(packages, start=1):
            self.signals.progress.emit(index, asset_total, CONFIG["progress_loading_package_data"].format(package=package.name))
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
            completed = subprocess.run(command, check=True, text=True, capture_output=True, env=PIPX_SUBPROCESS_ENV)
            message = completed.stdout or completed.stderr or CONFIG["command_success_fallback"]
            installed = load_pipx_installed_packages()
            save_installed_packages(installed)
            self.signals.command_finished.emit(self.package_name, True, message)
        except Exception as exc:
            self.signals.command_finished.emit(self.package_name, False, str(exc))


class CategoryListWidget(QListWidget):
    package_dropped = pyqtSignal(object, str, str)

    def __init__(self, category: str):
        super().__init__()
        self.category = category
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event) -> None:
        source = event.source()
        if not isinstance(source, CategoryListWidget) or source is self:
            event.ignore()
            return

        item = source.currentItem()
        package = item.data(Qt.UserRole) if item else None
        if package is None or self.category in package.categories:
            event.ignore()
            return

        self.package_dropped.emit(package, source.category, self.category)
        # The handler updates the repository and rebuilds the lists itself.
        # CopyAction prevents Qt from also deleting the item from its source list.
        event.setDropAction(Qt.CopyAction)
        event.accept()


class CategorySection(QWidget):
    def __init__(self, category: str):
        super().__init__()
        self.category = category
        self.button = QToolButton(text=CONFIG["category_expanded"].format(category=category), checkable=True, checked=True)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.clicked.connect(self.toggle)
        self.list_widget = CategoryListWidget(category)
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setIconSize(QSize(CONFIG["default_icon_size"], CONFIG["default_icon_size"]))
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
        self.button.setText((CONFIG["category_expanded"] if expanded else CONFIG["category_collapsed"]).format(category=self.category))
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
        
        self.setWindowTitle(about.__program_name__)
        self.resize(CONFIG["window_width"], CONFIG["window_height"])
        
        ## Icon
        # Get base directory for icons
        self.icon_path = resource_path("icons", "logo.png")
        self.setWindowIcon(QIcon(self.icon_path)) 

        
        self.thread_pool = QThreadPool.globalInstance()
        self.packages: List[RepositoryPackage] = []
        self.installed: Dict[str, dict] = {}
        self.sections: Dict[str, CategorySection] = {}
        self.current_package: Optional[RepositoryPackage] = None
        self.screenshots: List[QPixmap] = []
        self.screenshot_index = 0

        self._create_toolbar()
        self._build_ui()
        self.statusBar().showMessage(CONFIG["status_pipx_home"].format(path=PIPX_HOME))
        self.load_repositories()

    def _build_ui(self) -> None:
        root = QWidget()
        main = QVBoxLayout(root)
        self.search = QLineEdit(placeholderText=CONFIG["search_placeholder"])
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
        
        self.back_button = QPushButton(CONFIG["button_back"])
        self.back_button.setIcon(QIcon(resource_path("icons", "arrow-left-svgrepo-com.svg")))
        self.back_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.list_page))
        
        self.install_button = QPushButton(CONFIG["button_install"])
        self.install_button.setIcon(QIcon(resource_path("icons", "button_add_green.svg")))
        self.install_button.clicked.connect(self.install_or_uninstall)
        
        self.update_button = QPushButton(CONFIG["button_update"])
        self.update_button.setIcon(QIcon(resource_path("icons", "arrow-cw-svgrepo-com.svg")))
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

        self.launch_apps_section = QWidget()
        launch_section_layout = QVBoxLayout(self.launch_apps_section)
        launch_section_layout.setContentsMargins(0, 0, 0, 0)
        self.launch_apps_title = QLabel("<b>"+CONFIG["label_launch_apps"]+":</b>")
        self.launch_apps_container = QWidget()
        self.launch_apps_layout = QHBoxLayout(self.launch_apps_container)
        self.launch_apps_layout.setContentsMargins(0, 0, 0, 0)
        self.launch_apps_layout.setSpacing(6)
        self.launch_apps_scroll = QScrollArea()
        self.launch_apps_scroll.setWidgetResizable(True)
        self.launch_apps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.launch_apps_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.launch_apps_scroll.setFixedHeight(52)
        self.launch_apps_scroll.setWidget(self.launch_apps_container)
        launch_section_layout.addWidget(self.launch_apps_title)
        launch_section_layout.addWidget(self.launch_apps_scroll)
        self.launch_apps_section.setVisible(False)

        self.screenshot_label = QLabel(alignment=Qt.AlignCenter)
        self.screenshot_label.setMinimumHeight(260)
        shot_buttons = QHBoxLayout()
        previous_button = QPushButton(CONFIG["button_previous_screenshot"])
        previous_button.setToolTip(CONFIG["screenshot_previous_tooltip"])
        next_button = QPushButton(CONFIG["button_next_screenshot"])
        next_button.setToolTip(CONFIG["screenshot_next_tooltip"])
        previous_button.clicked.connect(lambda: self.change_screenshot(-1))
        next_button.clicked.connect(lambda: self.change_screenshot(1))
        shot_buttons.addStretch(); 
        shot_buttons.addWidget(previous_button); 
        shot_buttons.addWidget(next_button); 
        shot_buttons.addStretch()
        layout.addLayout(toolbar)
        layout.addLayout(header)
        layout.addWidget(self.summary_metadata)
        layout.addWidget(self.screenshot_label)
        layout.addLayout(shot_buttons)
        layout.addWidget(self.metadata)
        layout.addWidget(self.launch_apps_section)
        layout.addStretch()
        return page

    def load_repositories(self) -> None:
        self.refresh_action.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 1)
        worker = RepositoryLoader(Path(REPOSITORIES_DIR))
        worker.signals.progress.connect(lambda value, total, text: (self.progress.setRange(0, total), self.progress.setValue(value), self.progress.setFormat(text)))
        worker.signals.packages_loaded.connect(self.on_packages_loaded)
        self.thread_pool.start(worker)

    def on_packages_loaded(self, packages: list, installed: dict) -> None:
        self.packages = packages
        self.installed = installed
        self.progress.setVisible(False)
        self.refresh_action.setEnabled(True)
        self.populate_packages()

    def move_package_to_category(
        self, package: RepositoryPackage, source_category: str, destination_category: str
    ) -> None:
        if source_category not in package.categories or destination_category in package.categories:
            return

        updated_categories = [
            destination_category if category == source_category else category
            for category in package.categories
        ]

        source_file = Path(package.source_file)
        try:
            repository_data = json.loads(source_file.read_text(encoding="utf-8"))
            source_item = next(
                item for item in repository_data.get("packages", [])
                if item.get("name") == package.name
            )
            source_item["categories"] = updated_categories
            temporary_file = source_file.with_name(source_file.name + ".tmp")
            temporary_file.write_text(
                json.dumps(repository_data, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_file, source_file)
        except Exception as exc:
            self.statusBar().showMessage(
                CONFIG["error_save_category"].format(error=exc), 10000
            )
            return

        package.categories = updated_categories
        self.populate_packages()
        self.statusBar().showMessage(
            CONFIG["status_category_saved"].format(
                package=package.name, category=destination_category
            ),
            5000,
        )

    def installed_package(self, package_name: str) -> dict:
        return self.installed.get(normalize_package_name(package_name), {})

    def is_installed(self, package_name: str) -> bool:
        return bool(self.installed_package(package_name))

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
            section.list_widget.package_dropped.connect(self.move_package_to_category)
            self.sections[category] = section
            self.category_layout.insertWidget(self.category_layout.count() - 1, section)

            for package in sorted(packages_by_category[category], key=lambda p: p.name.lower()):
                item = QListWidgetItem(QIcon(pixmap_from_data(package.icon_data)), package.name)
                item.setData(Qt.UserRole, package)
                item.setToolTip(CONFIG["package_tooltip"].format(summary=package.summary()))
                if self.is_installed(package.name):
                    item.setText(CONFIG["package_installed_marker"].format(name=package.name))
                    item.setBackground(QColor("#dff7e8"))
                    item.setToolTip(CONFIG["package_installed_tooltip"].format(summary=package.summary()))
                section.list_widget.addItem(item)
            section.adjust_height()

    def open_package(self, item: QListWidgetItem) -> None:
        package = item.data(Qt.UserRole)
        self.current_package = package
        self.stack.setCurrentWidget(self.detail_page)
        self.title.setText(package.name)
        self.summary_metadata.setText(CONFIG["text_loading_metadata"])
        self.metadata.clear()
        self.screenshot_label.clear()
        worker = PackageInfoLoader(package)
        worker.signals.package_info_loaded.connect(self.on_package_info_loaded)
        self.thread_pool.start(worker)

    def on_package_info_loaded(self, package: RepositoryPackage, data: dict, icon: bytes, screenshots: list) -> None:
        info = data.get("info", {}) if data else {}
        #print(info)
        
        # Name
        name = info.get("name") or package.name
        self.title.setText(name)
        self.detail_icon.setPixmap(pixmap_from_data(icon, CONFIG["pkg_icon_size"]))
        
        # Screenshots
        self.screenshots = []
        for image in screenshots:
            if not image:
                continue
            pixmap = pixmap_from_data(image, CONFIG["pkg_screenshot_size"])
            if not pixmap.isNull():
                self.screenshots.append(pixmap)
        self.screenshot_index = 0
        self.show_screenshot()
        
        # Installed?
        installed_data = self.installed_package(package.name)
        installed_text = CONFIG["text_installed_version"].format(version=installed_data.get('version') or installed_version(package.name) or CONFIG["text_installed_version_unknown"]) if installed_data else CONFIG["text_not_installed"]
        
        # project urls
        project_urls = info.get("project_urls") or {}
        urls = "<br>".join(f"&nbsp;&nbsp;{key}: <a href='{value}'>{value}</a>" for key, value in project_urls.items()) or CONFIG["metadata_value_unavailable"]
        
        # Downloads
        project_downs = info.get("downloads") or {}
        downs = "; ".join(f"&nbsp;&nbsp;{key}: {value}" for key, value in project_downs.items()) or "-"
        
        # Home page
        home_page = info.get("home_page") or info.get("package_url") or  ""
        
        
        author, author_email = get_author(info.get('author'), info.get('author_email'))
        
        self.summary_metadata.setText(
            f"<p><b>{CONFIG['label_summary']}:</b> {info.get('summary') or CONFIG['metadata_value_unavailable']}</p>"
            f"<p><b>{CONFIG['label_version']}:</b> {info.get('version') or CONFIG['metadata_value_unavailable']}</p>"
        )
        self.metadata.setText(
            f"<p><b>{CONFIG['label_author']}:</b> {author or CONFIG['metadata_value_unavailable']}</p>"
            f"<p><b>{CONFIG['label_email']}:</b> {author_email or CONFIG['metadata_value_unavailable']}</p>"
            f"<p><b>{CONFIG['label_license']}:</b> {info.get('license') or CONFIG['metadata_value_unavailable']}</p>"
            f"<p><b>{CONFIG['label_homepage']}:</b> <a href='{home_page or '#'}'>{home_page or CONFIG['metadata_value_unavailable']}</a></p>"
            f"<p><b>{CONFIG['label_project_urls']}:</b><br>{urls}</p>"
            #f"<p><b>project_downs:</b><br>{downs}</p>"
            f"<p><b>{installed_text}</b></p>"
        )
        self.summary_metadata.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.metadata.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard | Qt.LinksAccessibleByMouse
        )
        self.summary_metadata.setOpenExternalLinks(True)
        self.metadata.setOpenExternalLinks(True)
        self.install_button.setText(CONFIG["button_uninstall"] if installed_data else CONFIG["button_install"])
        self.install_button.setIcon(QIcon(resource_path("icons", "button_remove_red.svg")) if installed_data else QIcon(resource_path("icons", "button_add_green.svg")))
        self.update_button.setEnabled(bool(installed_data))
        self.populate_launch_apps(installed_data)

    def populate_launch_apps(self, installed_data: dict) -> None:
        while self.launch_apps_layout.count():
            item = self.launch_apps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        executable_paths = installed_data.get("executable_paths", {})
        for app_name in installed_data.get("executables", []):
            app_path = executable_paths.get(app_name) or shutil.which(
                app_name, path=PIPX_SUBPROCESS_ENV.get("PATH", "")
            )
            if not app_path:
                continue
            button = QPushButton(app_name)
            button.setIcon(QIcon(resource_path("icons", "system-run.svg")))
            button.setToolTip(CONFIG["launch_app_tooltip"].format(app=app_name))
            button.clicked.connect(
                lambda checked=False, name=app_name, path=app_path:
                    self.launch_pipx_app(name, path)
            )
            self.launch_apps_layout.addWidget(button)

        has_launchable_apps = self.launch_apps_layout.count() > 0
        if has_launchable_apps:
            self.launch_apps_layout.insertStretch(0, 1)
            self.launch_apps_layout.addStretch(1)
        self.launch_apps_section.setVisible(has_launchable_apps)

    def launch_pipx_app(self, app_name: str, app_path: str) -> None:
        try:
            subprocess.Popen(
                [str(app_path)],
                env=PIPX_SUBPROCESS_ENV,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            self.statusBar().showMessage(
                CONFIG["error_launch_app"].format(app=app_name, error=exc), 10000
            )

    def show_screenshot(self) -> None:
        if not self.screenshots:
            self.screenshot_label.setPixmap(QPixmap())
            self.screenshot_label.setText(CONFIG["text_no_screenshots"])
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
            self.run_pipx("uninstall" if self.is_installed(self.current_package.name) else "install")

    def run_pipx(self, action: str) -> None:
        if not self.current_package:
            return
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        worker = PipxCommand(action, self.current_package.name)
        worker.signals.command_finished.connect(self.on_command_finished)
        self.thread_pool.start(worker)

    def show_command_output(self, ok: bool, message: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(CONFIG["dialog_pipx_title"] if ok else CONFIG["dialog_pipx_error_title"])
        dialog.resize(720, 420)

        layout = QVBoxLayout(dialog)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setLineWrapMode(QPlainTextEdit.NoWrap)
        output.setPlainText(message if ok else CONFIG["dialog_error_message"].format(message=message))
        output.setFont(QFont("Monospace"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)

        layout.addWidget(output)
        layout.addWidget(buttons)
        dialog.exec_()

    def on_command_finished(self, package_name: str, ok: bool, message: str) -> None:
        self.installed = load_pipx_installed_packages()
        save_installed_packages(self.installed)
        self.install_button.setEnabled(True)
        self.update_button.setEnabled(self.is_installed(package_name))
        self.install_button.setText(CONFIG["button_uninstall"] if self.is_installed(package_name) else CONFIG["button_install"])
        self.populate_packages()
        self.show_command_output(ok, message)

    def _create_toolbar(self):
        self.toolbar = self.addToolBar(CONFIG["toolbar_name"])
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)


        #
        self.directory_action = QAction(
            QIcon(resource_path("icons", "folder-drag-accept.png")),
            CONFIG["toolbar_directory"],
            self
        )
        self.directory_action.setToolTip(CONFIG["toolbar_directory_tooltip"])
        self.directory_action.triggered.connect(self.open_repository_directory)
        self.toolbar.addAction(self.directory_action)

        # Refresh repository and package metadata
        self.refresh_action = QAction(
            QIcon(resource_path("icons", "arrow-cw-svgrepo-com.svg")),
            CONFIG["toolbar_refresh"], 
            self
        )
        self.refresh_action.setToolTip(CONFIG["toolbar_refresh_tooltip"])
        self.refresh_action.triggered.connect(self.load_repositories)
        self.toolbar.addAction(self.refresh_action)
        

        # Adicionar o espaçador
        self.toolbar_spacer = QWidget()
        self.toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toolbar.addWidget(self.toolbar_spacer)
        

        
        #
        self.configure_action = QAction(QIcon(resource_path("icons", "text-configure.png")),
                                        CONFIG["toolbar_configure"], 
                                        self)
        self.configure_action.setToolTip(CONFIG["toolbar_configure_tooltip"])
        self.configure_action.triggered.connect(self.open_configure_editor)
        self.toolbar.addAction(self.configure_action)
        
        #
        self.about_action = QAction(QIcon(resource_path("icons", "status_help.png")),
                                    CONFIG["toolbar_about"], 
                                    self)
        self.about_action.setToolTip(CONFIG["toolbar_about_tooltip"])
        self.about_action.triggered.connect(self.open_about)
        self.toolbar.addAction(self.about_action)
        
        # Coffee
        self.coffee_action = QAction(   QIcon(resource_path("icons", "emote-love.png")),
                                        CONFIG["toolbar_coffee"], 
                                        self)
        self.coffee_action.setToolTip(CONFIG["toolbar_coffee_tooltip"])
        self.coffee_action.triggered.connect(self.on_coffee_action_click)
        self.toolbar.addAction(self.coffee_action)

        # Conectar ao sinal de mudança de orientação
        self.toolbar.orientationChanged.connect(self.on_update_spacer_policy)
        self.on_update_spacer_policy()

    def on_update_spacer_policy(self):
        """Atualiza a política do espaçador baseado na orientação da toolbar"""
        if self.toolbar.orientation() == Qt.Horizontal:
            # Horizontal: expande na largura
            self.toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            # Vertical: expande na altura
            self.toolbar_spacer.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def _open_file_in_text_editor(self, filepath):
        if os.name == 'nt':  # Windows
            os.startfile(filepath)
        elif os.name == 'posix':  # Linux/macOS
            subprocess.run(['xdg-open', filepath])
        
    def open_configure_editor(self):
        self._open_file_in_text_editor(CONFIG_PATH)

    def open_about(self):
        data={
            "version": about.__version__,
            "package": about.__package__,
            "program_name": about.__program_name__,
            "author": about.__author__,
            "email": about.__email__,
            "description": about.__description__,
            "url_source": about.__url_source__,
            "url_doc": about.__url_doc__,
            "url_funding": about.__url_funding__,
            "url_bugs": about.__url_bugs__
        }
        show_about_window(data,self.icon_path)

    def on_coffee_action_click(self):
        QDesktopServices.openUrl(QUrl("https://ko-fi.com/trucomanx"))
        
    def open_repository_directory(self):
        self._open_directory(REPOSITORIES_DIR)
        
    def _open_directory(self, directory):
        if os.name == "nt":  # Windows
            os.startfile(directory)
        elif sys.platform == "darwin":  # macOS
            subprocess.run(["open", directory])
        else:  # Linux
            subprocess.run(["xdg-open", directory])

def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
       
    icon_path=resource_path("icons", "logo.png")
    extras="" 
    
    create_desktop_directory()    
    create_desktop_menu()
    create_desktop_file(os.path.join("~",".local","share","applications"), 
                        program_name=about.__program_name__,
                        extras=extras,
                        icon_path=icon_path)
    
    for n in range(len(sys.argv)):
        if sys.argv[n] == "--autostart":
            create_desktop_directory(overwrite = True)
            create_desktop_menu(overwrite = True)
            create_desktop_file(os.path.join("~",".config","autostart"), 
                                overwrite=True, 
                                program_name=about.__program_name__,
                                extras=extras,
                                icon_path=icon_path)
            return
        if sys.argv[n] == "--applications":
            create_desktop_directory(overwrite = True)
            create_desktop_menu(overwrite = True)
            create_desktop_file(os.path.join("~",".local","share","applications"), 
                                overwrite=True, 
                                program_name=about.__program_name__,
                                extras=extras,
                                icon_path=icon_path)
            return
    
    app = QApplication(sys.argv)
    app.setApplicationName(about.__package__) 
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
