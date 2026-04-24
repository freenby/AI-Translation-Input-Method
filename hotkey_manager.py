"""Global hotkey manager.

Uses the native Win32 ``RegisterHotKey`` API instead of an installed
low-level keyboard hook.  This matters for robustness:

* ``RegisterHotKey`` never touches the system-wide keyboard event stream
  -- it is a pure message-dispatch mechanism.  When the hotkey conflicts
  with another application the kernel simply returns
  ``ERROR_HOTKEY_ALREADY_REGISTERED`` (1409).  It cannot leave modifier
  keys in a "stuck" state the way a low-level hook can.
* If the process crashes or exits, Windows automatically releases any
  hotkeys it had registered -- there is nothing the user has to reboot
  to recover from.
* There is no Python callback inside the kernel's keyboard filter chain,
  so our process can never trigger ``LowLevelHooksTimeout`` and be
  silently disabled.

The previous implementation used the ``keyboard`` library with
``suppress=True``, which installs a ``WH_KEYBOARD_LL`` hook that
intercepts *every* keystroke and replays the non-matching ones via
``keybd_event``.  When another application had also installed such a
hook on the same shortcut, the two replay paths would fight, modifier
key press/release events would get out of sync, and the only reliable
recovery was to reboot.  That is exactly the bug this module fixes.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Win32 bindings
# ---------------------------------------------------------------------------
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes   = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
_user32.RegisterHotKey.restype    = wt.BOOL
_user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype  = wt.BOOL
_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype  = wt.HWND
_user32.AllowSetForegroundWindow.argtypes = [wt.DWORD]
_user32.AllowSetForegroundWindow.restype  = wt.BOOL
_user32.SetForegroundWindow.argtypes = [wt.HWND]
_user32.SetForegroundWindow.restype  = wt.BOOL
_user32.BringWindowToTop.argtypes = [wt.HWND]
_user32.BringWindowToTop.restype  = wt.BOOL
_user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
_user32.ShowWindow.restype  = wt.BOOL
_user32.IsIconic.argtypes = [wt.HWND]
_user32.IsIconic.restype  = wt.BOOL
_user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
_user32.AttachThreadInput.restype  = wt.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowThreadProcessId.restype  = wt.DWORD
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype  = wt.DWORD

SW_SHOW    = 5
SW_RESTORE = 9

MOD_ALT      = 0x0001
MOD_CONTROL  = 0x0002
MOD_SHIFT    = 0x0004
MOD_WIN      = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

ERROR_HOTKEY_ALREADY_REGISTERED = 1409


# ---------------------------------------------------------------------------
# Hotkey-string parsing
# ---------------------------------------------------------------------------
_MOD_ALIASES = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN, "super": MOD_WIN, "meta": MOD_WIN,
}

# Named keys -> Windows virtual-key codes.  Includes the names Qt's
# QKeySequence.toString() produces (after lowercasing), so combinations
# captured by HotkeyRecorder round-trip correctly.
_VK_ALIASES: dict[str, int] = {
    "backspace": 0x08, "back": 0x08,
    "tab": 0x09,
    "enter": 0x0D, "return": 0x0D,
    "pause": 0x13, "capslock": 0x14,
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdown": 0x22, "pgdn": 0x22,
    "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "prtsc": 0x2C, "sysrq": 0x2C,
    "insert": 0x2D, "ins": 0x2D,
    "delete": 0x2E, "del": 0x2E,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    "numlock": 0x90, "scrolllock": 0x91,
}
for _i in range(10):
    _VK_ALIASES[str(_i)] = 0x30 + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    _VK_ALIASES[_c] = 0x41 + (ord(_c) - ord("a"))
for _i in range(1, 25):
    _VK_ALIASES[f"f{_i}"] = 0x6F + _i    # F1=0x70, F2=0x71, ...


def _parse_hotkey(text: str) -> tuple[int | None, int | None]:
    """Parse 'ctrl+f1' / 'ctrl+shift+f1' -> (mods_mask, vk_code)."""
    if not text:
        return None, None
    mods = 0
    vk: int | None = None
    for raw in text.split("+"):
        token = raw.strip().lower()
        if not token:
            continue
        if token in _MOD_ALIASES:
            mods |= _MOD_ALIASES[token]
        elif token in _VK_ALIASES:
            if vk is not None:
                return None, None           # two non-modifier keys
            vk = _VK_ALIASES[token]
        else:
            return None, None
    if vk is None:
        return None, None
    return mods, vk


# ---------------------------------------------------------------------------
# Native event filter helper
# ---------------------------------------------------------------------------
# IMPORTANT: This filter must inherit from QAbstractNativeEventFilter *only*.
# Combining it with QObject on a single Python class is a known PyQt6 pitfall
# -- sip cannot simultaneously expose both Qt base classes through the same
# instance pointer, so ``installNativeEventFilter(self)`` registers a pointer
# that Qt's C++ side cannot dispatch back into, and the filter is silently
# never invoked even though ``installNativeEventFilter`` returns cleanly.
# Keeping the filter in its own dedicated class works around this reliably.
class _HotkeyNativeFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: "HotkeyManager"):
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, eventType, message):
        return self._manager._on_native_event(eventType, message)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class HotkeyManager(QObject):
    """Register global hotkeys via RegisterHotKey and deliver them as Qt signals."""

    show_window_triggered         = pyqtSignal(int)   # foreground HWND
    translate_clipboard_triggered = pyqtSignal()
    registration_failed           = pyqtSignal(str, str)  # (hotkey, reason)

    # Arbitrary IDs -- only need to be unique within this process.
    _ID_SHOW = 0xB001
    _ID_CLIP = 0xB002

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered: dict[int, str] = {}   # hotkey_id -> human string
        self._target_hwnd: int = 0              # window to force-foreground on hotkey

        # The filter object must outlive the manager; keep it as an attribute
        # so Python doesn't garbage-collect it out from under Qt.
        self._filter = _HotkeyNativeFilter(self)
        app = QApplication.instance()
        if app is None:
            raise RuntimeError(
                "HotkeyManager must be created after QApplication is constructed"
            )
        app.installNativeEventFilter(self._filter)

    def set_target_hwnd(self, hwnd: int):
        """Register the HWND we should forcibly bring to the foreground the
        moment a hotkey fires.  Calling this is optional but highly
        recommended: it lets us grab foreground *synchronously inside* the
        WM_HOTKEY handler, while Windows still considers us the "most
        recent input recipient".  If we wait for Qt's signal machinery and
        a QTimer to fire, that permission has often already expired --
        which is exactly what produces the "sometimes the hotkey does
        nothing" symptom.
        """
        self._target_hwnd = int(hwnd) if hwnd else 0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def setup(self, show_hotkey: str, clip_hotkey: str):
        """Register both hotkeys.  Safe to call repeatedly."""
        self.unregister_all()
        self._register(self._ID_SHOW, show_hotkey)
        self._register(self._ID_CLIP, clip_hotkey)

    def update_hotkeys(self, show_hotkey: str, clip_hotkey: str):
        self.setup(show_hotkey, clip_hotkey)

    def unregister_all(self):
        for hid in list(self._registered):
            try:
                _user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
            self._registered.pop(hid, None)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def _register(self, hid: int, hotkey: str):
        if not hotkey:
            return
        mods, vk = _parse_hotkey(hotkey)
        if vk is None:
            msg = "无法识别的热键格式"
            print(f"[HotkeyManager] {msg}: {hotkey!r}")
            self.registration_failed.emit(hotkey, msg)
            return

        # RegisterHotKey does not need a window -- passing NULL binds the
        # hotkey to the *thread* that registers it, and WM_HOTKEY is then
        # posted to that thread's queue.  Qt's main event loop pumps
        # thread messages and hands them to installed native event
        # filters, so this reaches nativeEventFilter below.
        ok = _user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
        if not ok:
            err = ctypes.get_last_error()
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                reason = "该热键已被其他程序占用，请在设置中换一个组合"
            else:
                reason = f"Windows 错误码 {err}"
            print(f"[HotkeyManager] 注册热键 '{hotkey}' 失败: {reason}")
            self.registration_failed.emit(hotkey, reason)
            return

        self._registered[hid] = hotkey

    # ------------------------------------------------------------------
    # Native event dispatch -- called by _HotkeyNativeFilter for every
    # native Windows message that passes through Qt's event dispatcher.
    # ------------------------------------------------------------------
    def _on_native_event(self, eventType, message):
        # PyQt6 delivers eventType as ``bytes`` or ``QByteArray`` depending
        # on the release; accept both so we never silently miss a hotkey.
        if isinstance(eventType, bytes):
            et = eventType
        else:
            try:
                et = bytes(eventType)
            except Exception:
                return False, 0
        if et not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0

        try:
            msg = wt.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message != WM_HOTKEY:
            return False, 0

        hid = int(msg.wParam)
        if hid not in (self._ID_SHOW, self._ID_CLIP):
            return False, 0

        # Capture the foreground window BEFORE we steal focus, so callers
        # can still record the user's original chat window as a paste target.
        try:
            fg_hwnd = int(_user32.GetForegroundWindow())
        except Exception:
            fg_hwnd = 0

        # Grant any (including ourselves) permission to set foreground,
        # then pull our own window up synchronously.  Doing this *here*,
        # inside the WM_HOTKEY dispatch, is the key to reliability: the
        # "last user input was addressed to this process" permission
        # granted by the hotkey is still valid at this exact moment.
        self._pre_activate()
        self._force_target_foreground()

        if hid == self._ID_SHOW:
            self.show_window_triggered.emit(fg_hwnd)
        else:
            self.translate_clipboard_triggered.emit()
        return True, 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _pre_activate():
        """Lift the focus-stealing lock for our process."""
        try:
            ASFW_ANY = wt.DWORD(0xFFFFFFFF)
            _user32.AllowSetForegroundWindow(ASFW_ANY)
        except Exception:
            pass

    def _force_target_foreground(self):
        """Bring ``self._target_hwnd`` to the foreground, using the
        AttachThreadInput trick to bypass focus-stealing prevention."""
        hwnd = self._target_hwnd
        if not hwnd:
            return
        try:
            our_tid = _kernel32.GetCurrentThreadId()
            fg_hwnd = int(_user32.GetForegroundWindow())
            attached = False
            fg_tid = wt.DWORD(0)
            if fg_hwnd and fg_hwnd != hwnd:
                fg_tid_val = _user32.GetWindowThreadProcessId(fg_hwnd, None)
                if fg_tid_val and fg_tid_val != our_tid:
                    attached = bool(_user32.AttachThreadInput(
                        fg_tid_val, our_tid, True,
                    ))
                    fg_tid = wt.DWORD(fg_tid_val)
            # Restore a minimised window before trying to raise it.
            if _user32.IsIconic(hwnd):
                _user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                _user32.ShowWindow(hwnd, SW_SHOW)
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
            if attached:
                _user32.AttachThreadInput(fg_tid.value, our_tid, False)
        except Exception:
            pass
