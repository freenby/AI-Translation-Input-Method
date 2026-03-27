import pyperclip
import os
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QComboBox,
    QPushButton, QLabel, QFrame, QListWidget, QListWidgetItem,
    QMenu, QApplication,
)

from config_manager import ConfigManager, LANGUAGES
from translator import Translator, TranslationError

# ---------------------------------------------------------------------------
# Dark theme stylesheet (Catppuccin-inspired)
# ---------------------------------------------------------------------------
STYLE = """
/* Root window — solid background so no Layered Window needed */
QWidget#FloatingWindow {
    background-color: #1e1e2e;
}
/* Inner card with border */
QFrame#FloatingWindow {
    background-color: #1e1e2e;
    border-radius: 10px;
    border: 1px solid #45475a;
}
QLabel {
    color: #cdd6f4;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
QLabel#title {
    font-size: 14px;
    font-weight: bold;
    color: #cba6f7;
}
QLabel#section {
    font-size: 11px;
    color: #6c7086;
}
QLabel#status {
    font-size: 11px;
    color: #a6adc8;
}
QTextEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 8px;
    font-size: 14px;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    selection-background-color: #585b70;
}
QTextEdit:focus {
    border: 1px solid #cba6f7;
}
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
    min-width: 90px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #585b70;
    border: 1px solid #45475a;
}
QPushButton {
    background-color: #cba6f7;
    color: #1e1e2e;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: bold;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
QPushButton:hover { background-color: #d5b8ff; }
QPushButton:pressed { background-color: #b48ef0; }
QPushButton#secondary {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    font-weight: normal;
}
QPushButton#secondary:hover { background-color: #45475a; }
QPushButton#icon_btn {
    background-color: transparent;
    color: #6c7086;
    border: none;
    padding: 6px 10px;
    font-size: 16px;
    font-weight: normal;
    min-width: 32px;
    min-height: 32px;
}
QPushButton#icon_btn:hover { color: #cdd6f4; background-color: #313244; border-radius: 6px; }
QFrame#divider {
    color: #45475a;
}
QListWidget {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 8px;
    font-size: 13px;
}
QListWidget::item:selected { background-color: #585b70; }
QListWidget::item:hover { background-color: #45475a; }
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
# Phrase picker popup
# ---------------------------------------------------------------------------
class PhrasePicker(QListWidget):
    phrase_selected = pyqtSignal(str)

    def __init__(self, phrases: list, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        for p in phrases:
            item = QListWidgetItem(p["name"])
            item.setData(Qt.ItemDataRole.UserRole, p["content"])
            self.addItem(item)
        self.itemClicked.connect(self._on_click)

    def _on_click(self, item: QListWidgetItem):
        self.phrase_selected.emit(item.data(Qt.ItemDataRole.UserRole))
        self.hide()


# ---------------------------------------------------------------------------
# Main floating translation window
# ---------------------------------------------------------------------------
class FloatingWindow(QWidget):

    def __init__(self, config: ConfigManager, translator: Translator, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._translator = translator
        self._target_hwnd: int = 0
        self._target_name: str = ""
        self._target_cursor_pos: tuple[int, int] | None = None
        self._drag_pos: QPoint | None = None
        self._translation_thread: TranslationThread | None = None
        self._settings_dialog = None

        self._build_ui()
        self._apply_saved_position()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setObjectName("FloatingWindow")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # WA_TranslucentBackground turns the window into a Layered Window on
        # Windows, which blocks mouse events on the whole surface.
        # Use a solid background on the widget itself instead.
        self.setMinimumWidth(480)
        self.setStyleSheet(STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Card — same dark background, just no transparency trick needed
        card = QFrame()
        card.setObjectName("FloatingWindow")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 14)
        card_layout.setSpacing(8)
        root.addWidget(card)

        # Title bar
        card_layout.addLayout(self._build_title_bar())

        # Divider
        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet("background-color: #45475a;")
        card_layout.addWidget(div)

        # Input section
        in_lbl = QLabel("输入  (Enter 翻译 / Shift+Enter 换行)")
        in_lbl.setObjectName("section")
        card_layout.addWidget(in_lbl)

        self.input_edit = InputTextEdit()
        self.input_edit.setPlaceholderText("在这里输入要翻译的内容…")
        self.input_edit.setFixedHeight(120)
        self.input_edit.enter_pressed.connect(self.do_translate)
        card_layout.addWidget(self.input_edit)

        # Output section
        out_lbl = QLabel("翻译结果")
        out_lbl.setObjectName("section")
        card_layout.addWidget(out_lbl)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("翻译结果显示在这里…")
        self.output_edit.setFixedHeight(120)
        card_layout.addWidget(self.output_edit)

        # Status + action buttons
        card_layout.addLayout(self._build_bottom_bar())

        # Keyboard shortcuts
        QShortcut(QKeySequence("Escape"), self, self.hide_window)

    def _build_title_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        title = QLabel("⚡ AI翻译")
        title.setObjectName("title")
        bar.addWidget(title)

        bar.addStretch()

        # Source language
        self.src_combo = QComboBox()
        for lang in LANGUAGES:
            self.src_combo.addItem(lang)
        saved_src = self._cfg.get("languages", "input", default="中文")
        self.src_combo.setCurrentText(saved_src)
        bar.addWidget(self.src_combo)

        arrow = QLabel("→")
        arrow.setStyleSheet("color: #6c7086; font-size: 14px;")
        bar.addWidget(arrow)

        # Target language
        self.tgt_combo = QComboBox()
        for lang in LANGUAGES:
            self.tgt_combo.addItem(lang)
        saved_tgt = self._cfg.get("languages", "output", default="英语")
        self.tgt_combo.setCurrentText(saved_tgt)
        bar.addWidget(self.tgt_combo)

        bar.addSpacing(8)

        # Settings & close — saved as instance attrs to prevent GC
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

    def _build_bottom_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("status")
        bar.addWidget(self.status_label)

        bar.addStretch()

        # Phrase picker button
        phrase_btn = QPushButton("话术")
        phrase_btn.setObjectName("secondary")
        phrase_btn.setToolTip("插入常用话术")
        phrase_btn.clicked.connect(self._show_phrase_picker)
        bar.addWidget(phrase_btn)

        self.translate_btn = QPushButton("翻译 ↵")
        self.translate_btn.setToolTip("翻译 (Enter)")
        self.translate_btn.clicked.connect(self.do_translate)
        bar.addWidget(self.translate_btn)

        copy_btn = QPushButton("复制")
        copy_btn.setObjectName("secondary")
        copy_btn.setToolTip("复制翻译结果")
        copy_btn.clicked.connect(self._copy_result)
        bar.addWidget(copy_btn)

        paste_btn = QPushButton("粘贴到聊天框")
        paste_btn.setToolTip("翻译结果粘贴回原窗口")
        paste_btn.clicked.connect(self._paste_to_target)
        bar.addWidget(paste_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("secondary")
        clear_btn.clicked.connect(self._clear_all)
        bar.addWidget(clear_btn)

        return bar

    # ------------------------------------------------------------------
    # Public slots (called from HotkeyManager signals)
    # ------------------------------------------------------------------

    def on_hotkey_show(self, hwnd: int):
        """Called when show_window hotkey fires."""
        # Do not overwrite target with our own window/dialog handle.
        if hwnd and not self._is_our_window(hwnd):
            self._record_target(hwnd)
        self.show_window()

    def on_hotkey_translate_clipboard(self):
        """Called when translate_clipboard hotkey fires."""
        try:
            text = pyperclip.paste()
        except Exception:
            text = ""
        if not text.strip():
            self._set_status("剪贴板为空", error=True)
            return
        src = self.src_combo.currentText()
        tgt = self.tgt_combo.currentText()
        self.input_edit.setPlainText(text)
        self.show_window()
        self.do_translate()

    def show_window(self):
        """Show and focus the floating window in a stable, Qt-first way."""
        # Safety reset: if any previous operation left click-through enabled,
        # restore normal interaction before showing the window again.
        self._set_mouse_passthrough(False)
        # Clear minimized state explicitly to avoid "visible but non-interactive".
        state = self.windowState() & ~Qt.WindowState.WindowMinimized
        self.setWindowState(state)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._focus_input)

    def _focus_input(self):
        self.activateWindow()
        self.input_edit.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def hide_window(self):
        self._set_mouse_passthrough(False)
        pos = self.pos()
        self._cfg.set(pos.x(), "ui", "window_x")
        self._cfg.set(pos.y(), "ui", "window_y")
        self.hide()

    def show_settings(self):
        # Always keep window interactive before opening another dialog.
        self._set_mouse_passthrough(False)
        if self._settings_dialog is not None:
            try:
                self._settings_dialog.raise_()
                self._settings_dialog.activateWindow()
            except Exception:
                pass
            return

        try:
            from settings_dialog import SettingsDialog
            dlg = SettingsDialog(self._cfg, parent=self)
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
            self._settings_dialog = dlg
            dlg.exec()
            self._reload_language_combos()
        except Exception as e:
            self._set_status(f"设置窗口打开失败: {e}", error=True)
        finally:
            self._settings_dialog = None

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
        self._set_status("翻译完成 ✓")
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("翻译 ↵")

    def _on_translation_error(self, msg: str):
        self.output_edit.setPlainText(f"⚠ {msg}")
        self._set_status("翻译失败", error=True)
        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("翻译 ↵")

    # ------------------------------------------------------------------
    # Clipboard / paste
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
            self._set_status("未记录有效聊天窗口，请先在聊天框按 Alt+T 再粘贴", error=True)
            return
        pyperclip.copy(text)
        self._set_status("正在粘贴到聊天框…")
        QTimer.singleShot(80, self._do_paste)

    def _do_paste(self):
        self._set_mouse_passthrough(False)
        if self._target_hwnd:
            try:
                self._set_foreground_window(self._target_hwnd)
                QTimer.singleShot(80, self._focus_target_and_paste)
                return
            except Exception:
                pass
        self._send_paste()

    def _focus_target_and_paste(self):
        """Restore focus to user's original input position before Ctrl+V."""
        used_passthrough = False
        try:
            import pyautogui
            if self._target_cursor_pos:
                x, y = self._target_cursor_pos
                # Only enable click-through when the recorded click point is
                # actually covered by this floating window.
                if self.frameGeometry().contains(x, y):
                    self._set_mouse_passthrough(True)
                    used_passthrough = True
                pyautogui.click(x, y)
        except Exception:
            pass
        QTimer.singleShot(50, lambda: self._send_paste(used_passthrough))

    def _send_paste(self, restore_mouse_passthrough: bool = True):
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "v")
            self._set_status("已粘贴到聊天框 ✓")
        except Exception as e:
            self._set_status(f"粘贴失败: {e}", error=True)
        finally:
            if restore_mouse_passthrough:
                self._set_mouse_passthrough(False)

    # ------------------------------------------------------------------
    # Phrase picker
    # ------------------------------------------------------------------

    def _show_phrase_picker(self):
        phrases = self._cfg.get("phrases", default=[])
        if not phrases:
            self._set_status("暂无话术，请在设置中添加")
            return
        # Keep a reference to avoid popup being GC-collected immediately.
        self._phrase_picker = PhrasePicker(phrases, parent=self)
        self._phrase_picker.phrase_selected.connect(self._insert_phrase)
        btn_pos = self.mapToGlobal(self.translate_btn.pos())
        self._phrase_picker.move(btn_pos)
        self._phrase_picker.resize(240, min(30 * len(phrases) + 8, 240))
        self._phrase_picker.show()

    def _insert_phrase(self, content: str):
        self.input_edit.setPlainText(content)
        self.input_edit.setFocus()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record_target(self, hwnd: int):
        self._target_hwnd = hwnd
        name = self._get_window_title(hwnd)
        self._target_name = name
        self._target_cursor_pos = self._get_cursor_pos()
        lbl = f"目标: {name}" if name else "就绪"
        self._set_status(lbl)

    @staticmethod
    def _get_window_title(hwnd: int) -> str:
        if not hwnd:
            return ""
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
            try:
                import pyautogui
                pos = pyautogui.position()
                return int(pos.x), int(pos.y)
            except Exception:
                return None

    def _set_status(self, msg: str, error: bool = False):
        self.status_label.setText(msg)
        color = "#f38ba8" if error else "#a6adc8"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _clear_all(self):
        self.input_edit.clear()
        self.output_edit.clear()
        self._set_status("就绪")

    def _reload_language_combos(self):
        saved_src = self._cfg.get("languages", "input", default="中文")
        saved_tgt = self._cfg.get("languages", "output", default="英语")
        self.src_combo.setCurrentText(saved_src)
        self.tgt_combo.setCurrentText(saved_tgt)

    def _set_mouse_passthrough(self, enabled: bool):
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)

    @staticmethod
    def _is_our_window(hwnd: int) -> bool:
        """Whether hwnd belongs to current process (our own app windows)."""
        if not hwnd:
            return False
        try:
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid == os.getpid()
        except Exception:
            return False

    @staticmethod
    def _set_foreground_window(hwnd: int):
        """Safely bring a target window to foreground without key simulation."""
        if not hwnd:
            return
        import ctypes
        import win32gui
        import win32process

        fg_hwnd = win32gui.GetForegroundWindow()
        if not fg_hwnd or fg_hwnd == hwnd:
            win32gui.SetForegroundWindow(hwnd)
            return

        fg_tid, _ = win32process.GetWindowThreadProcessId(fg_hwnd)
        tgt_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
        attached = False
        try:
            if fg_tid != tgt_tid:
                ctypes.windll.user32.AttachThreadInput(fg_tid, tgt_tid, True)
                attached = True
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                ctypes.windll.user32.AttachThreadInput(fg_tid, tgt_tid, False)

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

    # ------------------------------------------------------------------
    # Dragging (title bar area, top 50px)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 50:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)
