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
    QMenu, QApplication, QSizeGrip,
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

    settings_saved = pyqtSignal()

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
        self._drag_pos: QPoint | None = None
        self._last_foreground_hwnd: int = 0  # 记录之前的前台窗口
        self._last_cursor_pos: tuple[int, int] | None = None  # 记录之前的光标位置

        self._build_ui()
        self._apply_saved_position()

        # 定时检查前台窗口和鼠标点击
        self._check_foreground_timer = QTimer(self)
        self._check_foreground_timer.timeout.connect(self._check_foreground_window)
        self._check_foreground_timer.start(50)  # 每50ms检查一次，更准确捕获点击

    # ------------------------------------------------------------------
    # Track foreground window and mouse clicks
    # ------------------------------------------------------------------

    def _check_foreground_window(self):
        """定期检查前台窗口和鼠标点击，记录最后点击位置"""
        try:
            import win32gui
            import win32api
            import ctypes

            hwnd = win32gui.GetForegroundWindow()

            # 如果前台窗口不是我们的窗口
            if hwnd and not self._is_our_window(hwnd):
                # 检测鼠标左键是否被按下
                user32 = ctypes.windll.user32
                if user32.GetAsyncKeyState(0x01) & 0x8000:  # VK_LBUTTON
                    # 鼠标左键按下时，记录窗口和光标位置
                    self._last_foreground_hwnd = hwnd
                    self._last_cursor_pos = win32api.GetCursorPos()
                elif hwnd != self._last_foreground_hwnd:
                    # 窗口切换时也记录
                    self._last_foreground_hwnd = hwnd
                    self._last_cursor_pos = win32api.GetCursorPos()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Window dragging (title bar area only)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 只在窗口顶部 80px 区域允许拖动（标题栏+语言栏）
            if event.position().y() < 80:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumSize(400, 300)
        self.resize(560, 420)  # 默认大小
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
        self.input_edit.setMinimumHeight(80)
        self.input_edit.enter_pressed.connect(self.do_translate)
        card_layout.addWidget(self.input_edit, 1)  # stretch factor 1

        out_lbl = QLabel("翻译结果")
        out_lbl.setObjectName("section")
        card_layout.addWidget(out_lbl)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("翻译结果显示在这里…")
        self.output_edit.setMinimumHeight(80)
        card_layout.addWidget(self.output_edit, 1)  # stretch factor 1

        card_layout.addLayout(self._build_bottom_bar())

        QShortcut(QKeySequence("Escape"), self, self.hide_window)

    def _build_title_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        title = QLabel("⚡ AI翻译输入法")
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

        bar.addSpacing(10)

        # 可点击的箭头按钮，用于切换源语言和目标语言
        swap_btn = QPushButton("⇄")
        swap_btn.setToolTip("点击切换源语言和目标语言")
        swap_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #cba6f7;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #313244;
                border-color: #cba6f7;
            }
            QPushButton:pressed {
                background-color: #45475a;
            }
        """)
        swap_btn.clicked.connect(self._swap_languages)
        bar.addWidget(swap_btn)

        bar.addSpacing(10)

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

    def _swap_languages(self):
        """切换源语言和目标语言"""
        src = self.src_combo.currentText()
        tgt = self.tgt_combo.currentText()
        self.src_combo.setCurrentText(tgt)
        self.tgt_combo.setCurrentText(src)
        self._set_status(f"已切换: {tgt} → {src}")

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

        bar.addSpacing(20)

        # 右下角调整大小区域（带提示）
        resize_container = QWidget()
        resize_layout = QHBoxLayout(resize_container)
        resize_layout.setContentsMargins(0, 0, 0, 0)
        resize_layout.setSpacing(4)

        resize_hint = QLabel("↘ 拖拽调整")
        resize_hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        resize_layout.addWidget(resize_hint)

        size_grip = QSizeGrip(self)
        size_grip.setFixedSize(16, 16)
        size_grip.setStyleSheet("""
            QSizeGrip {
                background: transparent;
                image: none;
            }
        """)
        resize_layout.addWidget(size_grip)

        bar.addWidget(resize_container)

        return bar

    # ------------------------------------------------------------------
    # Show / hide / settings
    # ------------------------------------------------------------------

    def show_window(self):
        # If the window was previously hidden (SW_HIDE), Windows occasionally
        # refuses the immediately-following SetForegroundWindow.  Waking it
        # out of a minimised/hidden state first gives Windows a chance to
        # mark the HWND as "restorable" before we grab foreground.
        try:
            from hotkey_manager import _dbg
            _dbg(
                f"[SHOW_WINDOW] enter isVisible={self.isVisible()} "
                f"isMinimized={self.isMinimized()} isActiveWindow={self.isActiveWindow()} "
                f"current_winId=0x{int(self.winId()):X}"
            )
        except Exception:
            pass
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self.input_edit.setFocus()
        try:
            from hotkey_manager import _dbg
            _dbg(
                f"[SHOW_WINDOW] after show isVisible={self.isVisible()} "
                f"isMinimized={self.isMinimized()} isActiveWindow={self.isActiveWindow()}"
            )
        except Exception:
            pass

        # Grab foreground SYNCHRONOUSLY -- we are still inside the WM_HOTKEY
        # dispatch context and therefore still hold the temporary "last input
        # event" permission Windows hands to the receiving process.  Waiting
        # 100ms used to let that permission expire, producing the "sometimes
        # the hotkey does nothing" symptom users reported.
        self._ensure_focus()
        # Fallback retry once Qt has finished any deferred show/layout work.
        QTimer.singleShot(80, self._ensure_focus)

    def _ensure_focus(self):
        """Force our window to foreground, bypassing focus-stealing prevention.

        Uses AttachThreadInput to temporarily merge input queues with the
        current foreground thread, which lets SetForegroundWindow succeed
        even when Windows would otherwise block it.  Safe to call multiple
        times -- if we are already the foreground window, most calls reduce
        to a no-op.
        """
        import ctypes
        import win32gui
        import win32process
        try:
            user32 = ctypes.windll.user32
            our_hwnd = int(self.winId())
            fg_hwnd = win32gui.GetForegroundWindow()
            our_tid = user32.GetCurrentThreadId()

            attached = False
            fg_tid = 0
            if fg_hwnd and fg_hwnd != our_hwnd:
                try:
                    fg_tid, _ = win32process.GetWindowThreadProcessId(fg_hwnd)
                except Exception:
                    fg_tid = 0
                if fg_tid and fg_tid != our_tid:
                    attached = bool(user32.AttachThreadInput(fg_tid, our_tid, True))

            user32.AllowSetForegroundWindow(ctypes.c_uint32(-1))
            user32.ShowWindow(our_hwnd, 5)          # SW_SHOW
            user32.BringWindowToTop(our_hwnd)
            user32.SetForegroundWindow(our_hwnd)
            user32.SetActiveWindow(our_hwnd)
            user32.SetFocus(our_hwnd)

            if attached:
                user32.AttachThreadInput(fg_tid, our_tid, False)
        except Exception:
            pass
        self.activateWindow()
        self.input_edit.setFocus()

    def hide_window(self):
        pos = self.pos()
        size = self.size()
        self._cfg.set(pos.x(), "ui", "window_x")
        self._cfg.set(pos.y(), "ui", "window_y")
        self._cfg.set(size.width(), "ui", "window_w")
        self._cfg.set(size.height(), "ui", "window_h")
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
        self.settings_saved.emit()

    # ------------------------------------------------------------------
    # Hotkey slots
    # ------------------------------------------------------------------

    def on_hotkey_show(self, hwnd: int):
        try:
            from hotkey_manager import _dbg
            _dbg(f"[ON_HOTKEY_SHOW] received fg_hwnd=0x{hwnd:X}")
        except Exception:
            pass
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
            self._set_status("未记录有效目标窗口，请先在聊天框按 Ctrl+F1", error=True)
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

        # 读取自动发送设置
        auto_send = self._cfg.get("behavior", "auto_send", default=True)
        send_key = self._cfg.get("behavior", "send_key", default="enter")

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
            time.sleep(0.15)

            # Step 5: Auto-send if enabled.
            if auto_send:
                time.sleep(0.1)
                if send_key == "ctrl+enter":
                    pyautogui.hotkey("ctrl", "enter")
                else:
                    pyautogui.press("enter")
                time.sleep(0.1)

            # Step 6: Restore TOPMOST and re-activate floating window.
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
        if self._target_locked:
            # 已锁定 -> 解锁
            self._target_locked = False
            self._target_hwnd = 0
            self._target_name = ""
            self._target_cursor_pos = None
            self._update_target_indicator()
            self._set_status("已解锁，请先点击聊天窗口，再点击「锁定」")
        else:
            # 未锁定 -> 锁定之前记录的窗口
            self._lock_previous_window()

    def _lock_previous_window(self):
        """锁定用户之前点击的窗口"""
        import win32gui
        import win32api

        try:
            if self._last_foreground_hwnd and not self._is_our_window(self._last_foreground_hwnd):
                hwnd = self._last_foreground_hwnd
                self._target_hwnd = hwnd
                self._target_name = self._get_window_title(hwnd)

                # 使用记录的光标位置，如果没有则使用窗口中心
                if self._last_cursor_pos:
                    self._target_cursor_pos = self._last_cursor_pos
                else:
                    # 获取窗口矩形，使用中心点
                    rect = win32gui.GetWindowRect(hwnd)
                    cx = (rect[0] + rect[2]) // 2
                    cy = (rect[1] + rect[3]) // 2
                    self._target_cursor_pos = (cx, cy)

                self._target_locked = True
                self._update_target_indicator()
                self._set_status(f"已锁定: {self._target_name}（如输入位置不对，请用 Ctrl+F1 重新锁定）")
            else:
                self._set_status("请先点击聊天窗口，再点击「锁定」", error=True)
        except Exception as e:
            self._set_status(f"锁定失败: {e}", error=True)

    def _update_target_indicator(self):
        name = (self._target_name or "").strip()
        if len(name) > 30:
            name = name[:30] + "…"
        if self._target_locked and self._target_hwnd:
            self.target_label.setText(f"🔒 {name}")
            self.target_label.setObjectName("target_locked")
            self.lock_btn.setText("解锁")
            self.lock_btn.setObjectName("lock_active")
        else:
            self.target_label.setText("点击锁定选择窗口")
            self.target_label.setObjectName("target_unlocked")
            self.lock_btn.setText("🎯 锁定")
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
        w = self._cfg.get("ui", "window_w", default=-1)
        h = self._cfg.get("ui", "window_h", default=-1)

        # 恢复大小
        if w > 0 and h > 0:
            self.resize(max(400, w), max(300, h))

        # 恢复位置
        if x >= 0 and y >= 0:
            self.move(x, y)
        else:
            screen = QApplication.primaryScreen().geometry()
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2,
            )
