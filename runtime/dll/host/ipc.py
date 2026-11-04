"""IPC with the Rust DLL: TCP loopback (duplex) line-delimited JSON.

Default: ``127.0.0.1:27111``. Named pipe kept as an optional inbound-only fallback.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable, Optional, Sequence

PIPE_NAME = r"\\.\pipe\darkside_arch"
TCP_HOST = "127.0.0.1"
TCP_PORT = 27111

OnMessage = Callable[[str], None]


class IpcServer:
    """Accept one DLL client at a time; push a watch list on connect."""

    def __init__(
        self,
        *,
        on_message: OnMessage,
        stop: threading.Event,
        watches: Sequence[dict[str, Any]],
        host: str = TCP_HOST,
        port: int = TCP_PORT,
    ) -> None:
        self._on_message = on_message
        self._stop = stop
        self._watches = list(watches)
        self._host = host
        self._port = port
        self._client_lock = threading.Lock()
        self._client: Optional[socket.socket] = None

    def set_watches(self, watches: Sequence[dict[str, Any]]) -> None:
        self._watches = list(watches)
        self._send_watches()

    def _send_watches(self) -> None:
        payload = json.dumps({"op": "watches", "items": self._watches}, separators=(",", ":"))
        with self._client_lock:
            sock = self._client
            if sock is None:
                return
            try:
                sock.sendall((payload + "\n").encode("utf-8"))
            except OSError as exc:
                print(f"[dll/ipc] send watches failed: {exc}")

    def send_json(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        with self._client_lock:
            sock = self._client
            if sock is None:
                return
            try:
                sock.sendall(line.encode("utf-8"))
            except OSError as exc:
                print(f"[dll/ipc] send failed: {exc}")

    def serve_forever(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.listen(1)
        sock.settimeout(1.0)
        print(f"[dll/ipc] listening tcp://{self._host}:{self._port}")
        try:
            while not self._stop.is_set():
                try:
                    conn, addr = sock.accept()
                except socket.timeout:
                    continue
                print(f"[dll/ipc] client {addr}")
                with self._client_lock:
                    self._client = conn
                conn.settimeout(1.0)
                self._send_watches()
                buf = b""
                try:
                    while not self._stop.is_set():
                        try:
                            chunk = conn.recv(4096)
                        except socket.timeout:
                            continue
                        except OSError:
                            break
                        if not chunk:
                            break
                        buf += chunk
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            text = raw.decode("utf-8", errors="replace").strip()
                            if text:
                                self._on_message(text)
                finally:
                    with self._client_lock:
                        if self._client is conn:
                            self._client = None
                    try:
                        conn.close()
                    except OSError:
                        pass
                    print("[dll/ipc] client disconnected")
        finally:
            sock.close()
