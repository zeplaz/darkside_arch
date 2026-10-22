"""Async Archipelago websocket loop. Independent of the RAM watcher thread."""

from __future__ import annotations

import asyncio
import queue
import ssl
import threading
from typing import Any, Optional

import websockets

from ds_client.ap_apply import maybe_synthetic_blade
from ds_client.ap_catalog import ApCatalog
from ds_client.ap_config import ApConfig, load_config, patch_config
from ds_client.ap_protocol import (
    ClientStatus,
    NetworkItem,
    connect_packet,
    decode_packets,
    encode_packets,
    location_checks_packet,
    parse_network_item,
    status_update_packet,
    sync_packet,
)
from ds_client.ap_state import ApState, ReceivedRow

STARTING_BACKOFF_S = 1.0
MAX_BACKOFF_S = 60.0


class ApRuntime:
    """Thread-safe façade used by the sync watcher / EventBus."""

    def __init__(
        self,
        state: ApState,
        catalog: ApCatalog,
        *,
        config_path=None,
        apply_queue: Optional[queue.SimpleQueue] = None,
    ) -> None:
        self.state = state
        self.catalog = catalog
        self.config_path = config_path
        self.apply_queue: queue.SimpleQueue = apply_queue or queue.SimpleQueue()
        self._outbox: queue.SimpleQueue = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._identity: Optional[tuple[str, int, int]] = None
        self._pending_locations: list[int] = []  # checks seen before the first Connected
        self._goal_pending = False  # goal reached before the first Connected
        self._lock = threading.Lock()

    @property
    def identity(self) -> Optional[tuple[str, int, int]]:
        with self._lock:
            return self._identity

    def set_identity(self, seed_name: str, team: int, slot: int) -> None:
        with self._lock:
            self._identity = (seed_name, team, slot)

    def take_pending(self) -> tuple[list[int], bool]:
        with self._lock:
            ids, goal = list(self._pending_locations), self._goal_pending
            self._pending_locations.clear()
            self._goal_pending = False
            return ids, goal

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="ap-client", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _thread_main(self) -> None:
        asyncio.run(self._amain())

    async def _amain(self) -> None:
        client = ApClient(self)
        await client.run_forever(self._stop)

    def submit_location_checks(self, location_ids: list[int]) -> None:
        """Persist the checks, then queue them. Connected always resends the full
        list, so a packet lost to a dropped socket is recovered on reconnect."""
        ids = [int(x) for x in location_ids]
        if not ids:
            return
        with self._lock:
            ident = self._identity
            if ident is None:
                self._pending_locations.extend(ids)
                return
        new_ids = self.state.add_checked_locations(*ident, ids)
        if new_ids:
            self._outbox.put(location_checks_packet(new_ids))

    def submit_goal(self) -> None:
        """Record the goal as reached; Connected resends it on every reconnect."""
        with self._lock:
            ident = self._identity
            if ident is None:
                self._goal_pending = True
                return
        if self.state.goal_sent(*ident):
            return
        self.state.set_goal_sent(*ident, True)
        self._outbox.put(status_update_packet(ClientStatus.CLIENT_GOAL))
        print("[AP] goal reached; sending CLIENT_GOAL")

    def drain_outbox(self) -> list[dict[str, Any]]:
        packets: list[dict[str, Any]] = []
        while True:
            try:
                packets.append(self._outbox.get_nowait())
            except queue.Empty:
                return packets

    def enqueue_apply(self, row: ReceivedRow) -> None:
        self.apply_queue.put(row)

    def enqueue_pending_from_db(self) -> None:
        ident = self.identity
        if ident is None:
            return
        for row in self.state.pending_applies(*ident):
            self.apply_queue.put(row)
        blade = maybe_synthetic_blade(self.state, self.catalog, *ident)
        if blade is not None:
            self.apply_queue.put(blade)


class ApClient:
    def __init__(self, runtime: ApRuntime) -> None:
        self.runtime = runtime
        self._ws: Any = None
        self._seed_name = ""
        self._connected = False  # True after this socket's Connected packet
        self._backoff = STARTING_BACKOFF_S

    async def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                cfg = (
                    load_config(self.runtime.config_path)
                    if self.runtime.config_path
                    else load_config()
                )
                if not cfg.slot:
                    await _sleep_or_stop(stop, 1.0)
                    continue
                await self._session(cfg, stop)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[AP] connection error: {exc}")
            if stop.is_set():
                return
            delay = self._backoff
            print(f"[AP] reconnect in {delay:.0f}s")
            await _sleep_or_stop(stop, delay)
            self._backoff = min(self._backoff * 2.0, MAX_BACKOFF_S)

    async def _session(self, cfg: ApConfig, stop: threading.Event) -> None:
        uri = cfg.uri()
        ssl_ctx: Optional[ssl.SSLContext] = None
        if cfg.use_wss:
            ssl_ctx = ssl.create_default_context()
        print(f"[AP] connecting {uri} as {cfg.slot!r}")
        async with websockets.connect(
            uri,
            ssl=ssl_ctx,
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
        ) as ws:
            self._ws = ws
            self._connected = False
            while not stop.is_set():
                if _config_identity_changed(cfg):
                    print("[AP] config changed; reconnecting with new host/port/slot")
                    return
                await self._flush_outbox()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    print("[AP] socket closed")
                    return
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                for packet in decode_packets(raw):
                    await self._handle(packet, cfg)

    async def _flush_outbox(self) -> None:
        # Nothing may go out before the server accepts our Connect.
        if self._connected:
            packets = self.runtime.drain_outbox()
            if packets:
                await self._send(packets)

    async def _send(self, packets: list[dict[str, Any]]) -> None:
        if self._ws is None:
            return
        await self._ws.send(encode_packets(packets))

    async def _handle(self, packet: dict[str, Any], cfg: ApConfig) -> None:
        cmd = packet.get("cmd")
        if cmd == "RoomInfo":
            self._seed_name = str(packet.get("seed_name") or "")
            print(
                f"[AP] RoomInfo seed={self._seed_name!r} version={packet.get('version')}"
            )
            await self._send(
                [
                    connect_packet(
                        slot=cfg.slot,
                        password=cfg.password,
                        uuid=cfg.uuid,
                        game=cfg.game,
                        tags=cfg.tags,
                    )
                ]
            )
            return
        if cmd == "ConnectionRefused":
            # Wrong slot / password / game: close and back off instead of idling.
            raise ConnectionError(f"ConnectionRefused {packet.get('errors') or []}")
        if cmd == "Connected":
            await self._on_connected(packet, cfg)
            return
        if cmd == "ReceivedItems":
            await self._on_received_items(packet)
            return
        if cmd == "PrintJSON":
            _log_print_json(packet)
            return
        if cmd == "InvalidPacket":
            print(f"[AP] InvalidPacket {packet.get('type')}: {packet.get('text')}")

    async def _on_connected(self, packet: dict[str, Any], cfg: ApConfig) -> None:
        seed = self._seed_name or str(packet.get("seed_name") or "")
        team = int(packet.get("team") or 0)
        slot = int(packet.get("slot") or 0)
        self.runtime.set_identity(seed, team, slot)
        state = self.runtime.state
        state.bind_server(seed, team, slot, cfg.host, cfg.port)
        pending, goal_pending = self.runtime.take_pending()
        server_checked = [int(x) for x in packet.get("checked_locations") or []]
        state.add_checked_locations(seed, team, slot, pending + server_checked)
        if goal_pending or cfg.request_goal:
            state.set_goal_sent(seed, team, slot, True)
        msgs: list[dict[str, Any]] = []
        checked = state.checked_locations(seed, team, slot)
        if checked:
            msgs.append(location_checks_packet(checked))
        if state.goal_sent(seed, team, slot):
            msgs.append(status_update_packet(ClientStatus.CLIENT_GOAL))
        if msgs:
            await self._send(msgs)
        self.runtime.drain_outbox()  # everything queued is covered by the resend above
        self._connected = True
        self._backoff = STARTING_BACKOFF_S
        self.runtime.enqueue_pending_from_db()
        print(f"[AP] Connected team={team} slot={slot} seed={seed!r}")
        if cfg.request_goal:
            patch_config(cfg.path, request_goal=False)

    async def _on_received_items(self, packet: dict[str, Any]) -> None:
        ident = self.runtime.identity
        if ident is None:
            print("[AP] ReceivedItems before Connected; ignoring")
            return
        start_index = int(packet.get("index") or 0)
        raw_items = packet.get("items") or []
        items: list[NetworkItem] = [
            parse_network_item(obj, index=start_index + i)
            for i, obj in enumerate(raw_items)
        ]
        last = self.runtime.state.last_ingested_index(*ident)
        if start_index > last:
            # Missed a batch: ask for the full list (index 0) and drop this one.
            print(f"[AP] item index gap (got {start_index}, have {last}); sending Sync")
            await self._send([sync_packet()])
            return
        pending = self.runtime.state.ingest_received(
            ident[0], ident[1], ident[2], start_index, items
        )
        skipped = len(items) - len(pending)
        if skipped:
            print(f"[AP] skipped {skipped} already-ingested item(s) (resync)")
        for row in pending:
            self.runtime.enqueue_apply(row)
        blade = maybe_synthetic_blade(self.runtime.state, self.runtime.catalog, *ident)
        if blade is not None:
            self.runtime.enqueue_apply(blade)


def _config_identity_changed(cfg: ApConfig) -> bool:
    path = cfg.path
    if not path.exists():
        return False
    if path.stat().st_mtime <= cfg.mtime:
        return False
    fresh = load_config(path)
    return fresh.identity() != cfg.identity()


def _log_print_json(packet: dict[str, Any]) -> None:
    parts = packet.get("data") or []
    text = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
    if text:
        print(f"[AP] {text}")


async def _sleep_or_stop(stop: threading.Event, seconds: float) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while not stop.is_set() and loop.time() < end:
        await asyncio.sleep(0.2)
