import keyboard
from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyManager(QObject):
    """Manages global hotkeys using the `keyboard` library.

    Signals are emitted from keyboard's background thread; Qt's
    auto-connection will queue them safely to the GUI thread.
    """

    show_window_triggered = pyqtSignal(int)       # carries target HWND
    translate_clipboard_triggered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered: dict[str, any] = {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def setup(self, show_hotkey: str, clip_hotkey: str):
        """Register both hotkeys from config strings (e.g. 'alt+t')."""
        self.unregister_all()
        self._add(show_hotkey, self._on_show_window)
        self._add(clip_hotkey, self._on_translate_clipboard)

    def unregister_all(self):
        for hk in list(self._registered):
            self._remove(hk)

    def update_hotkeys(self, show_hotkey: str, clip_hotkey: str):
        self.setup(show_hotkey, clip_hotkey)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _add(self, hotkey: str, callback):
        if not hotkey:
            return
        try:
            keyboard.add_hotkey(hotkey, callback, suppress=True)
            self._registered[hotkey] = callback
        except Exception as e:
            print(f"[HotkeyManager] 无法注册热键 '{hotkey}': {e}")

    def _remove(self, hotkey: str):
        try:
            keyboard.remove_hotkey(hotkey)
        except Exception:
            pass
        self._registered.pop(hotkey, None)

    def _on_show_window(self):
        hwnd = self._get_foreground_hwnd()
        self.show_window_triggered.emit(hwnd)

    def _on_translate_clipboard(self):
        self.translate_clipboard_triggered.emit()

    @staticmethod
    def _get_foreground_hwnd() -> int:
        try:
            import win32gui
            return win32gui.GetForegroundWindow()
        except ImportError:
            return 0
