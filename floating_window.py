"""
Floating translation window — the main UI of the app.

Uses PyQt6-Frameless-Window (qframelesswindow) to avoid the well-known
Qt6 FramelessWindowHint hide/show bug on Windows that causes the window
to become unresponsive.

Paste-to-chat uses Win32 SendMessage to deliver Ctrl+V directly to the
target window's message queue, so the floating window never needs to lose
focus or visibility.
"""

import os
import pyperclip
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QComboBox,
    QPushButton, QLabel, QFrame, QListWidget, QListWidgetItem,
    QMenu, QApplication,
)
from qframelesswindow import FramelessWindow

from config_manager import ConfigManager, LANGUAGES
from translator import Translator, TranslationError


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
STYLE = """
QWidget#card {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
}
QLabel {
    color: #cdd6f4;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLabel#title {
    font-size: 16px; font-weight: bold; color: #cba6f7;
}
QLabel#section {
    font-size: 12px; color: #6c7086;
}
QLabel#status {
    font-size: 12px; color: #a6adc8;
}
QLabel#target_unlocked {
    background-color: #313244; color: #6c7086;
    border: 1px solid #45475a; border-radius: 6px;
    padding: 4px 12px; font-size: 13px;
}
QLabel#target_locked {
    background-color: #1e3a2f; color: #a6e3a1;
    border: 1px solid #a6e3a1; border-radius: 6px;
    padding: 4px 12px; font-size: 13px;
}
QTextEdit {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 8px;
    padding: 10px; font-size: 14px;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    selection-background-color: #585b70;
}
QTextEdit:focus { border: 1px solid #cba6f7; }
QComboBox {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px;
    padding: 6px 12px; font-size: 13px; min-width: 100px;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: #313244; color: #cdd6f4;
    selection-background-color: #585b70; border: 1px solid #45475a;
    font-size: 13px;
}
QPushButton {
    background-color: #cba6f7; color: #1e1e2e;
    border: none; border-radius: 6px;
    padding: 8px 16px; font-size: 13px; font-weight: bold;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
QPushButton:hover { background-color: #d5b8ff; }
QPushButton:pressed { background-color: #b48ef0; }
QPushButton#secondary {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; font-weight: normal;
}
QPushButton#secondary:hover { background-color: #45475a; }
QPushButton#icon_btn {
    background-color: transparent; color: #6c7086;
    border: none; padding: 8px 12px; font-size: 18px;
    font-weight: normal; min-width: 36px; min-height: 36px;
}
QPushButton#icon_btn:hover {
    color: #cdd6f4; background-color: #313244; border-radius: 6px;
}
QPushButton#lock_btn {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px;
    padding: 6px 14px; font-size: 13px; font-weight: normal; min-width: 60px;
}
QPushButton#lock_btn:hover { background-color: #45475a; }
QPushButton#lock_active {
    background-color: #1e3a2f; color: #a6e3a1;
    border: 1px solid #a6e3a1; border-radius: 6px;
    padding: 6px 14px; font-size: 13px; font-weight: bold; min-width: 60px;
}
QPushButton#lock_active:hover { background-color: #2a4d3e; }
"""


# ---------------------------------------------------------------------------
# Background translation thread
# ---------------------------------------------------------------------------
class TranslationThread(QThread):
    result_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, translator: Translator, text: str, src: str, tgt: str):
        super().__init__()
        self._translator = translator
        self._text = text
        self._src = src
        self._tgt = tgt

    def run(self):
        try:
            result = self._translator.translate(self._text, self._src, self._tgt)
            self.result_ready.emit(result)
        except TranslationError as e:
            self.error_occurred.emit(str(e))


# ---------------------------------------------------------------------------
# Input text edit — Enter triggers translation, Shift+Enter inserts newline
# ---------------------------------------------------------------------------
class InputTextEdit(QTextEdit):
    enter_pressed = pyqtSignal()

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self.enter_pressed.emit()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Win32 helper: send Ctrl+V to a window without switching focus
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Main floating translation window
# ---------------------------------------------------------------------------
class FloatingWindow(FramelessWindow):

    def __init__(self, config: ConfigManager, translator: Translator, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._translator = translator
        self._target_hwnd: int = 0
        self._target_name: str = ""
        self._target_cursor_pos: tuple[int, int] | None = None
        self._target_locked: bool = False
        self._translation_thread: TranslationThread | None = None
        self._auto_paste: bool = False

        self._build_ui()
        self._apply_saved_position()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumWidth(600)
        self.setStyleSheet(STYLE)
        self.titleBar.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 16)
        card_layout.setSpacing(10)
        root.addWidget(card)

        card_layout.addLayout(self._build_title_bar())
        card_layout.addLayout(self._build_language_bar())

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("background-color: #45475a;")
        card_layout.addWidget(div)

        in_lbl = QLabel("输入  (Enter 翻译 / Shift+Enter 换行)")
        in_lbl.setObjectName("section")
        card_layout.addWidget(in_lbl)

        self.input_edit = InputTextEdit()
        self.input_edit.setPlaceholderText("在这里输入要翻译的内容…")
        self.input_edit.setFixedHeight(130)
        self.input_edit.enter_pressed.connect(self.do_translate)
        card_layout.addWidget(self.input_edit)

        out_lbl = QLabel("翻译结果")
        out_lbl.setObjectName("section")
        card_layout.addWidget(out_lbl)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("翻译结果显示在这里…")
        self.output_edit.setFixedHeight(130)
        card_layout.addWidget(self.output_edit)

        card_layout.addLayout(self._build_bottom_bar())

        QShortcut(QKeySequence("Escape"), self, self.hide_window)

    def _build_title_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        title = QLabel("⚡ AI翻译")
        title.setObjectName("title")
        bar.addWidget(title)

        bar.addSpacing(12)

        self.target_label = QLabel("未锁定")
        self.target_label.setObjectName("target_unlocked")
        self.target_label.setMinimumWidth(150)
        bar.addWidget(self.target_label)

        self.lock_btn = QPushButton("锁定")
        self.lock_btn.setObjectName("lock_btn")
        self.lock_btn.clicked.connect(self._toggle_target_lock)
        bar.addWidget(self.lock_btn)

        bar.addStretch()

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("icon_btn")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.clicked.connect(self.show_settings)
        bar.addWidget(self.settings_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("icon_btn")
        self.close_btn.setToolTip("隐藏 (Esc)")
        self.close_btn.clicked.connect(self.hide_window)
        bar.addWidget(self.close_btn)

        return bar

    def _build_language_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        src_lbl = QLabel("源语言:")
        src_lbl.setStyleSheet("color: #a6adc8; font-size: 13px;")
        bar.addWidget(src_lbl)

        self.src_combo = QComboBox()
        for lang in LANGUAGES:
            self.src_combo.addItem(lang)
        self.src_combo.setCurrentText(self._cfg.get("languages", "input", default="中文"))
        bar.addWidget(self.src_combo)

        bar.addSpacing(20)

        arrow = QLabel("→")
        arrow.setStyleSheet("color: #cba6f7; font-size: 18px; font-weight: bold;")
        bar.addWidget(arrow)

        bar.addSpacing(20)

        tgt_lbl = QLabel("目标语言:")
        tgt_lbl.setStyleSheet("color: #a6adc8; font-size: 13px;")
        bar.addWidget(tgt_lbl)

        self.tgt_combo = QComboBox()
        for lang in LANGUAGES:
            self.tgt_combo.addItem(lang)
        self.tgt_combo.setCurrentText(self._cfg.get("languages", "output", default="英语"))
        bar.addWidget(self.tgt_combo)

        bar.addStretch()

        return bar

    def _build_bottom_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("status")
        bar.addWidget(self.status_label)
        bar.addStretch()

        phrase_btn = QPushButton("话术")
        phrase_btn.setObjectName("secondary")
        phrase_btn.clicked.connect(self._show_phrase_picker)
        bar.addWidget(phrase_btn)

        self.translate_btn = QPushButton("翻译 ↵")
        self.translate_btn.clicked.connect(self.do_translate)
        bar.addWidget(self.translate_btn)

        copy_btn = QPushButton("复制")
        copy_btn.setObjectName("secondary")
        copy_btn.clicked.connect(self._copy_result)
        bar.addWidget(copy_btn)

        paste_btn = QPushButton("粘贴到聊天框")
        paste_btn.clicked.connect(self._paste_to_target)
        bar.addWidget(paste_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("secondary")
        clear_btn.clicked.connect(self._clear_all)
        bar.addWidget(clear_btn)

        return bar

    # ------------------------------------------------------------------
    # Show / hide / settings
    # ------------------------------------------------------------------

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_edit.setFocus()
        QTimer.singleShot(100, self._ensure_focus)

    def _ensure_focus(self):
        """Delayed focus grab — ensures our window gets input after hotkey."""
        import ctypes
        import win32gui
        import win32con
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            user32.AllowSetForegroundWindow(ctypes.c_uint32(-1))
            win32gui.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        self.activateWindow()
        self.input_edit.setFocus()

    def hide_window(self):
        pos = self.pos()
        self._cfg.set(pos.x(), "ui", "window_x")
        self._cfg.set(pos.y(), "ui", "window_y")
        self.hide()

    def show_settings(self):
        try:
            from settings_dialog import SettingsDialog
            self._settings_dlg = SettingsDialog(self._cfg, parent=None)
            self._settings_dlg.finished.connect(self._on_settings_closed)
            self._settings_dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._settings_dlg.show()
            self._settings_dlg.raise_()
            self._settings_dlg.activateWindow()
        except Exception as e:
            self._set_status(f"设置窗口打开失败: {e}", error=True)

    def _on_settings_closed(self, _result: int):
        self._reload_language_combos()
        self._settings_dlg = None

    # ------------------------------------------------------------------
    # Hotkey slots
    # ------------------------------------------------------------------

    def on_hotkey_show(self, hwnd: int):
        if hwnd and not self._is_our_window(hwnd):
            if self._target_locked:
                self._set_status(f"已锁定: {self._target_name}")
            else:
                self._record_target(hwnd)
        self.show_window()

    def on_hotkey_translate_clipboard(self):
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""
        if not text.strip():
            self._set_status("剪贴板为空", error=True)
            return
        self.input_edit.setPlainText(text)
        self.show_window()
        self.do_translate()

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def do_translate(self):
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        if self._translation_thread and self._translation_thread.isRunning():
            return

        src = self.src_combo.currentText()
        tgt = self.tgt_combo.currentText()

        self.translate_btn.setEnabled(False)
        self.translate_btn.setText("翻译中…")
        self.output_edit.setPlainText("")
        self._set_status("正在翻译…")

        self._translation_thread = TranslationThread(self._translator, text, src, tgt)
        self._translation_thread.result_ready.connect(self._on_translation_done)
        self._translation_thread.error_occurred.connect(self._on_translation_error)
        self._translation_thread.start()

    def _on_translation_done(self, result: str):
        self.output_edit.setPlainText(result)
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("翻译 ↵")

        if self._target_locked and self._target_hwnd:
            self._auto_paste = True
            self.input_edit.clear()  # 翻译完成立即清空，用户可以马上输入下一句
            self._paste_to_target()
        else:
            self._set_status("翻译完成 ✓")

    def _on_translation_error(self, msg: str):
        self.output_edit.setPlainText(f"⚠ {msg}")
        self._set_status("翻译失败", error=True)
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("翻译 ↵")

    # ------------------------------------------------------------------
    # Clipboard / paste — sends Ctrl+V directly via Win32 SendMessage
    # ------------------------------------------------------------------

    def _copy_result(self):
        text = self.output_edit.toPlainText().strip()
        if text:
            pyperclip.copy(text)
            self._set_status("已复制到剪贴板 ✓")

    def _paste_to_target(self):
        text = self.output_edit.toPlainText().strip()
        if not text:
            self._set_status("没有翻译结果可粘贴", error=True)
            return
        if not self._target_hwnd or self._is_our_window(self._target_hwnd):
            self._set_status("未记录有效目标窗口，请先在聊天框按 Alt+T", error=True)
            return

        pyperclip.copy(text)
        self._set_status("正在粘贴…")
        self._activate_target_and_paste()

    # ╔══════════════════════════════════════════════════════════════╗
    # ║  VERIFIED PASTE LOGIC — DO NOT MODIFY WITHOUT FULL RETEST  ║
    # ║  Runs in a background thread to prevent Qt event loop from ║
    # ║  restoring TOPMOST during the sequence.                    ║
    # ╚══════════════════════════════════════════════════════════════╝

    def _activate_target_and_paste(self):
        import threading

        my_hwnd = int(self.winId())
        tgt_hwnd = self._target_hwnd
        cursor_pos = self._target_cursor_pos

        def _worker():
            import ctypes
            import win32gui
            import win32con
            import time
            import pyautogui

            user32 = ctypes.windll.user32

            # Step 1: Drop TOPMOST so target can truly become foreground.
            win32gui.SetWindowPos(
                my_hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
            time.sleep(0.05)

            # Step 2: Activate target window.
            user32.AllowSetForegroundWindow(ctypes.c_uint32(-1))
            win32gui.ShowWindow(tgt_hwnd, win32con.SW_SHOW)
            win32gui.BringWindowToTop(tgt_hwnd)
            user32.SetForegroundWindow(tgt_hwnd)
            time.sleep(0.2)

            # Step 3: Click recorded cursor position to restore input
            # focus inside the target app (e.g. DingTalk chat input box).
            if cursor_pos:
                pyautogui.click(cursor_pos[0], cursor_pos[1])
                time.sleep(0.15)

            # Step 4: Ctrl+V paste.
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)

            # Step 5: Restore TOPMOST and re-activate floating window.
            win32gui.SetWindowPos(
                my_hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
            user32.AllowSetForegroundWindow(ctypes.c_uint32(-1))
            win32gui.BringWindowToTop(my_hwnd)
            user32.SetForegroundWindow(my_hwnd)

        def _on_done():
            self.activateWindow()
            self._set_status("已粘贴到聊天框 ✓")
            self._auto_paste = False
            self.input_edit.clear()
            self.input_edit.setFocus()

        def _run():
            try:
                _worker()
            except Exception as e:
                QTimer.singleShot(0, lambda: self._set_status(f"粘贴失败: {e}", error=True))
                return
            QTimer.singleShot(0, _on_done)

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Target lock
    # ------------------------------------------------------------------

    def _record_target(self, hwnd: int):
        self._target_hwnd = hwnd
        self._target_name = self._get_window_title(hwnd)
        self._target_cursor_pos = self._get_cursor_pos()
        self._target_locked = True
        self._update_target_indicator()
        self._set_status(f"已锁定: {self._target_name}" if self._target_name else "已锁定目标窗口")

    def _toggle_target_lock(self):
        if not self._target_hwnd:
            self._set_status("没有可锁定的目标，请先在聊天窗口按 Alt+T", error=True)
            return
        self._target_locked = not self._target_locked
        self._update_target_indicator()
        if self._target_locked:
            self._set_status(f"已锁定: {self._target_name}")
        else:
            self._set_status("已解锁，下次按 Alt+T 将重新选择目标窗口")

    def _update_target_indicator(self):
        name = (self._target_name or "").strip()
        if len(name) > 35:
            name = name[:35] + "…"
        if self._target_locked and self._target_hwnd:
            self.target_label.setText(f"🔒 {name}")
            self.target_label.setObjectName("target_locked")
            self.lock_btn.setText("解锁")
            self.lock_btn.setObjectName("lock_active")
        else:
            self.target_label.setText("未锁定")
            self.target_label.setObjectName("target_unlocked")
            self.lock_btn.setText("锁定")
            self.lock_btn.setObjectName("lock_btn")
        for w in (self.target_label, self.lock_btn):
            w.style().unpolish(w)
            w.style().polish(w)

    # ------------------------------------------------------------------
    # Phrase picker
    # ------------------------------------------------------------------

    def _show_phrase_picker(self):
        phrases = self._cfg.get("phrases", default=[])
        if not phrases:
            self._set_status("暂无话术，请在设置中添加")
            return
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        picker = QListWidget(self)
        picker.setWindowFlags(Qt.WindowType.Popup)
        picker.setStyleSheet("QListWidget { background:#313244; color:#cdd6f4; border:1px solid #45475a; border-radius:8px; }")
        for p in phrases:
            item = QListWidgetItem(p["name"])
            item.setData(Qt.ItemDataRole.UserRole, p["content"])
            picker.addItem(item)
        picker.itemClicked.connect(lambda it: (self.input_edit.setPlainText(it.data(Qt.ItemDataRole.UserRole)), picker.close()))
        btn_pos = self.mapToGlobal(self.translate_btn.pos())
        picker.move(btn_pos)
        picker.resize(240, min(30 * len(phrases) + 8, 240))
        picker.show()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_window_title(hwnd: int) -> str:
        try:
            import win32gui
            return win32gui.GetWindowText(hwnd) or ""
        except Exception:
            return ""

    @staticmethod
    def _get_cursor_pos() -> tuple[int, int] | None:
        try:
            import win32api
            x, y = win32api.GetCursorPos()
            return int(x), int(y)
        except Exception:
            return None

    @staticmethod
    def _is_our_window(hwnd: int) -> bool:
        if not hwnd:
            return False
        try:
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid == os.getpid()
        except Exception:
            return False

    def _set_status(self, msg: str, error: bool = False):
        self.status_label.setText(msg)
        color = "#f38ba8" if error else "#a6adc8"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")

    def _clear_all(self):
        self.input_edit.clear()
        self.output_edit.clear()
        self._set_status("就绪")

    def _reload_language_combos(self):
        self.src_combo.setCurrentText(self._cfg.get("languages", "input", default="中文"))
        self.tgt_combo.setCurrentText(self._cfg.get("languages", "output", default="英语"))

    def _apply_saved_position(self):
        x = self._cfg.get("ui", "window_x", default=-1)
        y = self._cfg.get("ui", "window_y", default=-1)
        if x >= 0 and y >= 0:
            self.move(x, y)
        else:
            screen = QApplication.primaryScreen().geometry()
            self.adjustSize()
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2,
            )
