"""Player AP connection config. Hot-reloaded; applied on the next Connect."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

CONFIG_FILE = Path("ap_config.json")
EXAMPLE_FILE = Path("ap_config.example.json")

_DEFAULTS = {
    "host": "localhost",
    "port": 38281,
    "slot": "",
    "password": "",
    "game": "Darksiders",
    "use_wss": False,
    "tags": ["Darksiders"],
    "request_goal": False,
    "uuid": "",
}


@dataclass(frozen=True)
class ApConfig:
    host: str
    port: int
    slot: str
    password: str
    game: str
    use_wss: bool
    tags: tuple[str, ...]
    request_goal: bool
    uuid: str
    path: Path
    mtime: float

    def uri(self) -> str:
        scheme = "wss" if self.use_wss else "ws"
        return f"{scheme}://{self.host}:{self.port}"

    def identity(self) -> tuple[str, int, str, str, bool]:
        return (self.host, self.port, self.slot, self.password, self.use_wss)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def default_use_wss(host: str) -> bool:
    """Website-hosted rooms (archipelago.gg:PORT) are TLS-only."""
    name = host.strip().lower().rstrip(".")
    return name == "archipelago.gg" or name.endswith(".archipelago.gg")


def parse_connect_target(raw: str) -> tuple[str, Optional[int], Optional[bool]]:
    """Parse host[:port], ws://, wss://, or archipelago:// into (host, port, use_wss).

    ``port`` is None when the text has none, so callers keep the saved port.
    ``use_wss`` is None when the scheme is omitted (or ``archipelago://``);
    callers then infer from host / saved config.
    """
    text = raw.strip()
    use_wss: Optional[bool] = None
    if text.startswith("archipelago://"):
        text = text[len("archipelago://") :]
    if text.startswith("wss://"):
        use_wss = True
        text = text[len("wss://") :]
    elif text.startswith("ws://"):
        use_wss = False
        text = text[len("ws://") :]
    if "/" in text:
        text = text.split("/", 1)[0]
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    host, port = text, None
    if ":" in text:
        host, port_s = text.rsplit(":", 1)
        port = int(port_s)
    return host, port, use_wss


def load_config(path: Path = CONFIG_FILE) -> ApConfig:
    """read_config, then create the file / fill in a uuid if either is missing."""
    cfg = read_config(path)
    if path.exists() and cfg.uuid:
        return cfg
    cfg = replace(cfg, uuid=cfg.uuid or str(uuid.uuid4()))
    save_config(cfg, path)
    return replace(cfg, mtime=path.stat().st_mtime)


def read_config(path: Path = CONFIG_FILE) -> ApConfig:
    """Parse the config (or the example, or defaults) without writing anything."""
    data: dict[str, Any] = dict(_DEFAULTS)
    mtime = 0.0
    if path.exists():
        mtime = path.stat().st_mtime
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{path} must be a JSON object")
        data.update(loaded)
    elif EXAMPLE_FILE.exists():
        loaded = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)

    # Accept "host:port" / "wss://host:port" pasted into the host field.
    host, host_port, host_wss = parse_connect_target(str(data.get("host") or "localhost"))
    host = host or "localhost"
    if host_wss is not None:
        use_wss = host_wss
    else:
        use_wss = _as_bool(data.get("use_wss", False)) or default_use_wss(host)
    tags_raw = data.get("tags") or _DEFAULTS["tags"]
    tags = tuple(str(t) for t in tags_raw)
    return ApConfig(
        host=host,
        port=host_port or int(data.get("port") or 38281),
        slot=str(data.get("slot") or "").strip(),
        password=str(data.get("password") or ""),
        game=str(data.get("game") or "Darksiders").strip() or "Darksiders",
        use_wss=use_wss,
        tags=tags or ("Darksiders",),
        request_goal=_as_bool(data.get("request_goal", False)),
        uuid=str(data.get("uuid") or "").strip(),
        path=path,
        mtime=mtime,
    )


def save_config(cfg: ApConfig, path: Optional[Path] = None) -> Path:
    dest = path or cfg.path
    payload = {
        "host": cfg.host,
        "port": cfg.port,
        "slot": cfg.slot,
        "password": cfg.password,
        "game": cfg.game,
        "use_wss": cfg.use_wss,
        "tags": list(cfg.tags),
        "request_goal": cfg.request_goal,
        "uuid": cfg.uuid,
    }
    # Write-then-rename: the AP thread may re-read this file at any moment.
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def patch_config(path: Path = CONFIG_FILE, **changes: Any) -> ApConfig:
    cfg = load_config(path)
    data = {**cfg.__dict__, **changes}
    data.pop("path", None)
    data.pop("mtime", None)
    updated = ApConfig(path=path, mtime=0.0, **data)
    save_config(updated, path)
    return load_config(path)
