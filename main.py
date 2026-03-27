"""
电商AI翻译输入法 — 主入口

启动方式:
    python main.py
    或双击 run.bat

依赖安装:
    pip install -r requirements.txt
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from config_manager import ConfigManager
from translator import Translator
from hotkey_manager import HotkeyManager
from floating_window import FloatingWindow


# ---------------------------------------------------------------------------
# Tray icon — generated dynamically, no external asset needed
# ---------------------------------------------------------------------------
def _make_tray_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QColor("#cba6f7"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 60, 60)

    painter.setPen(QColor("#1e1e2e"))
    font = QFont("Microsoft YaHei UI", 24, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "译")
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Application orchestrator
# ---------------------------------------------------------------------------
class TranslatorApp:

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("AI翻译输入法")

        self._cfg = ConfigManager()
        self._cfg.load()

        self._translator = Translator(self._cfg)
        self._window = FloatingWindow(self._cfg, self._translator)
        self._hotkeys = HotkeyManager()

        self._setup_tray()
        self._setup_hotkeys()
        self._check_first_run()

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(_make_tray_icon(), self.app)
        self.tray.setToolTip("AI翻译输入法\n左键单击呼出窗口")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                padding: 4px;
            }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: #cba6f7; color: #1e1e2e; }
            QMenu::separator { height: 1px; background-color: #45475a; margin: 4px 0; }
        """)

        open_action = QAction("打开翻译窗口  (Alt+T)", self.app)
        open_action.triggered.connect(self._window.show_window)
        menu.addAction(open_action)

        settings_action = QAction("设置", self.app)
        settings_action.triggered.connect(self._window.show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("退出", self.app)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._window.isVisible():
                self._window.hide_window()
            else:
                self._window.show_window()

    # ------------------------------------------------------------------
    # Global hotkeys
    # ------------------------------------------------------------------
    def _setup_hotkeys(self):
        show_hk = self._cfg.get("hotkeys", "show_window", default="alt+t")
        clip_hk = self._cfg.get("hotkeys", "translate_clipboard", default="alt+c")

        self._hotkeys.show_window_triggered.connect(self._window.on_hotkey_show)
        self._hotkeys.translate_clipboard_triggered.connect(
            self._window.on_hotkey_translate_clipboard
        )
        self._hotkeys.setup(show_hk, clip_hk)

    def refresh_hotkeys(self):
        """Re-read config and re-register hotkeys (called after settings save)."""
        self._hotkeys.unregister_all()
        self._setup_hotkeys()

    # ------------------------------------------------------------------
    # First-run notice
    # ------------------------------------------------------------------
    def _check_first_run(self):
        if not self._cfg.get("api", "api_key", default=""):
            self.tray.showMessage(
                "AI翻译输入法",
                "欢迎使用！请右键托盘图标 → 设置，填写 API Key 后即可开始翻译。",
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------
    def _quit(self):
        self._hotkeys.unregister_all()
        self.tray.hide()
        self.app.quit()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self) -> int:
        return self.app.exec()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = TranslatorApp()
    sys.exit(app.run())
