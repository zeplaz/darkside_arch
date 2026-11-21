"""Topmost, click-through status overlay for the DLL runtime (raw Win32/GDI).

Draws a small translucent green status line over the game showing the injection
state (``DSH INJECTED ✓ · watching N identities · CHECK …``). Windows only.

Used by the host::

    python -m runtime.dll --overlay          # TEST (no Archipelago)

The overlay is driven by the DLL's IPC traffic (hello / log / open), so it only
lights up once ``darkside_arch.dll`` is actually injected into the game process.
Run the game in **borderless / windowed** mode if the overlay does not appear
over an exclusive-fullscreen surface.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- constants -------------------------------------------------------------
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
LWA_ALPHA = 0x00000002
SW_SHOWNOACTIVATE = 4

WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1

DT_LEFT = 0x0000
DT_TOP = 0x0000
DT_NOCLIP = 0x0100
DT_SINGLELINE = 0x0020
DT_VCENTER = 0x0004
TRANSPARENT = 1
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
FW_BOLD = 700
CLEARTYPE_QUALITY = 5
DEFAULT_CHARSET = 1

# --- structs ---------------------------------------------------------------
class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

# --- prototypes ------------------------------------------------------------
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = wintypes.LPARAM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.InvalidateRect.restype = wintypes.BOOL
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = wintypes.LPARAM
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL

gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.SetTextColor.restype = wintypes.COLORREF
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
user32.DrawTextW.restype = ctypes.c_int
gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

# --- window registry -------------------------------------------------------
_windows: dict[int, "Overlay"] = {}
_instances: list = []  # keep the WNDPROC callback alive


@WNDPROC
def _wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_NCHITTEST:
        return HTTRANSPARENT  # click-through
    if msg == WM_PAINT:
        ov = _windows.get(int(hwnd))
        if ov is not None:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            try:
                _paint(hdc, ov._text_locked())
            finally:
                user32.EndPaint(hwnd, ctypes.byref(ps))
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _paint(hdc, text: str) -> None:
    rect = wintypes.RECT(0, 0, 640, 26)
    gdi32.SetBkMode(hdc, TRANSPARENT)
    gdi32.SetTextColor(hdc, 0x14FF39)  # neon green (0x00BBGGRR)
    font = gdi32.CreateFontW(
        -14, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, "Consolas"
    )
    old = gdi32.SelectObject(hdc, font)
    try:
        user32.DrawTextW(hdc, text, -1, ctypes.byref(rect), DT_LEFT | DT_TOP | DT_NOCLIP | DT_SINGLELINE | DT_VCENTER)
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(font)


class Overlay:
    """A tiny always-on-top status line. Thread-safe ``set_text``."""

    def __init__(self, text: str = "DSH …"):
        self._lock = threading.Lock()
        self._text = text
        self._hwnd = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dsh-overlay", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _text_locked(self) -> str:
        with self._lock:
            return self._text

    def set_text(self, text: str) -> None:
        with self._lock:
            self._text = text
        hwnd = self._hwnd
        if hwnd is not None:
            user32.InvalidateRect(hwnd, None, True)

    def close(self) -> None:
        hwnd = self._hwnd
        if hwnd is not None:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        class_name = "DshOverlayWindow"
        wc = WNDCLASSW()
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = ctypes.cast(_wnd_proc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.hCursor = None
        wc.hbrBackground = gdi32.CreateSolidBrush(0x000000)  # black, made translucent below
        wc.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            class_name,
            "DSH",
            WS_POPUP,
            16, 16, 640, 26,
            None, None, hinst, None,
        )
        if not hwnd:
            self._ready.set()
            return
        self._hwnd = hwnd
        _windows[int(hwnd)] = self
        user32.SetLayeredWindowAttributes(hwnd, 0, 170, LWA_ALPHA)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        _windows.pop(int(hwnd), None)
        user32.DestroyWindow(hwnd)


def main() -> int:
    """Standalone smoke test: show a status line for a few seconds."""
    import time

    ov = Overlay("DSH INJECTED ✓")
    for msg in [
        "DSH INJECTED ✓",
        "DSH INJECTED ✓ · watching 2 identities",
        "DSH INJECTED ✓ · scanning 2 identities",
        "DSH INJECTED ✓ · CHECK Seraphim Hotel Life Chest 1",
    ]:
        ov.set_text(msg)
        time.sleep(1.2)
    ov.close()
    time.sleep(0.5)
    print("[overlay] smoke test done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
