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
import os
import sys
import time

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Diagnostic logger -- writes to both stdout and a file next to the script,
# so we can capture hotkey behaviour even when launched without a console.
# ---------------------------------------------------------------------------
def _log_path() -> str:
    base = os.path.dirname(os.path.abspath(sys.argv[0] or __file__))
    return os.path.join(base, "hotkey_debug.log")


_LOG_FILE_PATH = _log_path()
try:
    with open(_LOG_FILE_PATH, "a", encoding="utf-8") as _f:
        _f.write(f"\n===== Session start {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} =====\n")
except Exception:
    pass


def _dbg(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}.{int(time.time()*1000)%1000:03d}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(_LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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
_user32.IsWindow.argtypes = [wt.HWND]
_user32.IsWindow.restype  = wt.BOOL
_user32.IsWindowVisible.argtypes = [wt.HWND]
_user32.IsWindowVisible.restype  = wt.BOOL
_user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
_user32.AttachThreadInput.restype  = wt.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowThreadProcessId.restype  = wt.DWORD
# Patch A: message-only window for hotkey reception.
_user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
_user32.CreateWindowExW.restype = wt.HWND
_user32.DestroyWindow.argtypes = [wt.HWND]
_user32.DestroyWindow.restype  = wt.BOOL

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype  = wt.DWORD
_kernel32.GetCurrentProcess.argtypes = []
_kernel32.GetCurrentProcess.restype  = wt.HANDLE
# Patch B: SetProcessInformation -- only present on Win10 1809+.  We
# resolve it lazily because older systems don't expose the symbol at all.
try:
    _kernel32.SetProcessInformation.argtypes = [
        wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
    ]
    _kernel32.SetProcessInformation.restype = wt.BOOL
    _HAS_SET_PROCESS_INFO = True
except AttributeError:
    _HAS_SET_PROCESS_INFO = False


# Message-only window sentinel parent (HWND_MESSAGE = -3).
_HWND_MESSAGE = wt.HWND(-3)


# PROCESS_INFORMATION_CLASS::ProcessPowerThrottling
_PROCESS_POWER_THROTTLING = 4
_PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
_PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x00000001


class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version",     wt.ULONG),
        ("ControlMask", wt.ULONG),
        ("StateMask",   wt.ULONG),
    ]

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
# Patch A helper: create a hidden message-only window so that WM_HOTKEY is
# delivered as a *window message* rather than a *thread message*.  This
# matters on packaged GUI exes (console=False) running on Windows 11:
#
#   * RegisterHotKey(NULL, ...) posts WM_HOTKEY via PostThreadMessage to the
#     calling thread's queue.  Thread messages do NOT wake a process that
#     EcoQoS / Power Throttling has put into a low-power wait, so after the
#     window has been hidden for a while the hotkey appears to do nothing.
#
#   * RegisterHotKey(real_hwnd, ...) posts WM_HOTKEY via PostMessage to the
#     window's queue.  Window messages DO wake throttled processes, just
#     like a tray-icon click does.
#
# The window has no WndProc of its own -- Qt's main GetMessage loop pulls
# WM_HOTKEY out and our installed QAbstractNativeEventFilter intercepts it
# exactly the same way it always has.
# ---------------------------------------------------------------------------
def _create_message_window() -> int:
    """Create an invisible HWND_MESSAGE child to receive WM_HOTKEY.

    Returns the HWND as int, or 0 if creation failed (in which case the
    caller falls back to the thread-bound NULL-HWND path).
    """
    try:
        hwnd = _user32.CreateWindowExW(
            0,                # ex style
            "STATIC",         # predefined window class -- no need to register
            None,             # window name
            0,                # style
            0, 0, 0, 0,       # x, y, w, h
            _HWND_MESSAGE,    # parent: HWND_MESSAGE (-3) => message-only
            None, None, None,
        )
        if hwnd:
            _dbg(f"[INIT] message-only window created hwnd=0x{int(hwnd):X}")
            return int(hwnd)
        err = ctypes.get_last_error()
        _dbg(f"[INIT] CreateWindowExW(HWND_MESSAGE) failed err={err}")
    except Exception as e:
        _dbg(f"[INIT] _create_message_window exception: {e!r}")
    return 0


# ---------------------------------------------------------------------------
# Patch B helper: opt this process out of Win11 Power Throttling / EcoQoS.
#
# By default, Windows 11 marks any GUI process whose top-level windows have
# all been hidden for a few minutes as a "background" process and reduces
# its scheduling priority + thread-message wakeup responsiveness.  For a
# global-hotkey utility this is fatal: we *want* to be ready to react the
# instant the user presses Ctrl+F1, even if our window has been hidden for
# hours.  Setting StateMask=0 with ControlMask=EXECUTION_SPEED tells the
# OS "explicitly do not throttle execution speed for this process".
#
# The API (SetProcessInformation + ProcessPowerThrottling) was introduced
# in Windows 10 1809; we silently no-op on older systems.
# ---------------------------------------------------------------------------
def _disable_power_throttling() -> bool:
    if not _HAS_SET_PROCESS_INFO:
        _dbg("[POWER] SetProcessInformation not available, skipping")
        return False
    try:
        state = _PROCESS_POWER_THROTTLING_STATE()
        state.Version     = _PROCESS_POWER_THROTTLING_CURRENT_VERSION
        state.ControlMask = _PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        state.StateMask   = 0   # 0 + control-bit set => OPT-OUT of throttling
        ok = _kernel32.SetProcessInformation(
            _kernel32.GetCurrentProcess(),
            _PROCESS_POWER_THROTTLING,
            ctypes.byref(state),
            ctypes.sizeof(state),
        )
        if ok:
            _dbg("[POWER] SetProcessInformation: EcoQoS opt-out OK")
        else:
            err = ctypes.get_last_error()
            _dbg(f"[POWER] SetProcessInformation failed err={err}")
        return bool(ok)
    except Exception as e:
        _dbg(f"[POWER] _disable_power_throttling exception: {e!r}")
        return False


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

        # Patch B: opt out of Win11 EcoQoS BEFORE registering any hotkeys.
        # Doing this once at startup is enough -- the policy persists for
        # the lifetime of the process.
        _disable_power_throttling()

        # Patch A: create a hidden message-only window and register hotkeys
        # against it, so WM_HOTKEY is delivered as a window message (which
        # wakes the message pump even under EcoQoS) rather than a thread
        # message (which does not).  If creation fails for any reason we
        # transparently fall back to the original NULL-HWND behaviour.
        self._msg_hwnd: int = _create_message_window()

        # The filter object must outlive the manager; keep it as an attribute
        # so Python doesn't garbage-collect it out from under Qt.
        self._filter = _HotkeyNativeFilter(self)
        app = QApplication.instance()
        if app is None:
            raise RuntimeError(
                "HotkeyManager must be created after QApplication is constructed"
            )
        app.installNativeEventFilter(self._filter)

        # Diagnostic heartbeat -- if this keeps logging while Ctrl+F1 stops
        # working, we know the Qt event loop is alive and the failure is in
        # WM_HOTKEY dispatch (PostThreadMessage path), not a frozen UI thread.
        from PyQt6.QtCore import QTimer
        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(self._on_heartbeat)
        self._heartbeat.start(30_000)
        _dbg(
            f"[INIT] HotkeyManager constructed msg_hwnd=0x{self._msg_hwnd:X}, "
            f"heartbeat started (30s)"
        )

    def _on_heartbeat(self):
        try:
            tid = _kernel32.GetCurrentThreadId()
            fg = int(_user32.GetForegroundWindow())
            tgt = self._target_hwnd
            tgt_alive = bool(_user32.IsWindow(tgt)) if tgt else False
            tgt_iconic = bool(_user32.IsIconic(tgt)) if tgt and tgt_alive else False
            tgt_visible = bool(_user32.IsWindowVisible(tgt)) if tgt and tgt_alive else False
            _dbg(
                f"[HEARTBEAT] tid={tid} fg=0x{fg:X} target=0x{tgt:X} "
                f"alive={tgt_alive} iconic={tgt_iconic} visible={tgt_visible} "
                f"registered={list(self._registered.values())}"
            )
        except Exception as e:
            _dbg(f"[HEARTBEAT] exception: {e!r}")

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
        _dbg(f"[INIT] set_target_hwnd(0x{self._target_hwnd:X})")

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
        # Pass the same HWND we registered against -- mismatched HWNDs cause
        # UnregisterHotKey to silently fail and leak the registration.
        owner = self._msg_hwnd if self._msg_hwnd else None
        for hid in list(self._registered):
            try:
                _user32.UnregisterHotKey(owner, hid)
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

        # Patch A: prefer registering against our message-only window so
        # that WM_HOTKEY is delivered as a window message (survives EcoQoS).
        # Fall back to the legacy thread-bound NULL path only if the message
        # window could not be created (e.g. resource exhaustion).
        owner = self._msg_hwnd if self._msg_hwnd else None
        ok = _user32.RegisterHotKey(owner, hid, mods | MOD_NOREPEAT, vk)
        _dbg(
            f"[INIT] RegisterHotKey id=0x{hid:04X} hotkey={hotkey!r} "
            f"mods=0x{mods:X} vk=0x{vk:X} owner_hwnd="
            f"{'0x%X' % self._msg_hwnd if self._msg_hwnd else 'NULL'} ok={bool(ok)}"
        )
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
        _dbg(f"[NATIVE] WM_HOTKEY received: hid=0x{hid:04X} et={et!r} target_hwnd=0x{self._target_hwnd:X}")
        if hid not in (self._ID_SHOW, self._ID_CLIP):
            _dbg(f"[NATIVE] hid not ours, ignoring")
            return False, 0

        # Capture the foreground window BEFORE we steal focus, so callers
        # can still record the user's original chat window as a paste target.
        try:
            fg_hwnd = int(_user32.GetForegroundWindow())
        except Exception:
            fg_hwnd = 0
        _dbg(f"[NATIVE] foreground before activation: 0x{fg_hwnd:X}")

        # Grant any (including ourselves) permission to set foreground,
        # then pull our own window up synchronously.  Doing this *here*,
        # inside the WM_HOTKEY dispatch, is the key to reliability: the
        # "last user input was addressed to this process" permission
        # granted by the hotkey is still valid at this exact moment.
        self._pre_activate()
        self._force_target_foreground()

        if hid == self._ID_SHOW:
            _dbg(f"[NATIVE] emitting show_window_triggered(0x{fg_hwnd:X})")
            self.show_window_triggered.emit(fg_hwnd)
        else:
            _dbg(f"[NATIVE] emitting translate_clipboard_triggered")
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
            _dbg(f"[FORCE_FG] no target hwnd cached, skipping")
            return
        try:
            is_window = bool(_user32.IsWindow(hwnd)) if hasattr(_user32, "IsWindow") else True
        except Exception:
            is_window = True
        try:
            iconic_before = bool(_user32.IsIconic(hwnd))
        except Exception:
            iconic_before = False
        _dbg(f"[FORCE_FG] target hwnd=0x{hwnd:X} IsWindow={is_window} IsIconic={iconic_before}")

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
                    _dbg(f"[FORCE_FG] AttachThreadInput fg_tid={fg_tid_val} our_tid={our_tid} attached={attached}")
            # Restore a minimised window before trying to raise it.
            if iconic_before:
                ok_show = _user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                ok_show = _user32.ShowWindow(hwnd, SW_SHOW)
            ok_bring = _user32.BringWindowToTop(hwnd)
            ok_setfg = _user32.SetForegroundWindow(hwnd)
            err_setfg = ctypes.get_last_error() if not ok_setfg else 0
            try:
                fg_after = int(_user32.GetForegroundWindow())
            except Exception:
                fg_after = 0
            _dbg(
                f"[FORCE_FG] ShowWindow={bool(ok_show)} BringWindowToTop={bool(ok_bring)} "
                f"SetForegroundWindow={bool(ok_setfg)} err={err_setfg} fg_after=0x{fg_after:X} "
                f"matches_target={fg_after == hwnd}"
            )
            if attached:
                _user32.AttachThreadInput(fg_tid.value, our_tid, False)
        except Exception as e:
            _dbg(f"[FORCE_FG] exception: {e!r}")
