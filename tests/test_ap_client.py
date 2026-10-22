import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from ds_client.ap_catalog import ApCatalog, CatalogEntry
from ds_client.ap_client import ApRuntime
from ds_client.ap_config import ApConfig, save_config
from ds_client.ap_protocol import encode_packets, parse_network_item
from ds_client.ap_state import ApState


def _catalog() -> ApCatalog:
    return ApCatalog(
        locations={
            "Crossroads Currency Chest Down Stairs": CatalogEntry(
                "Crossroads Currency Chest Down Stairs", 172
            )
        },
        items={
            "Beholder Key": CatalogEntry("Beholder Key", 59, "keys"),
            "Armageddon Blade Shards": CatalogEntry(
                "Armageddon Blade Shards", 133, "primary_weapons"
            ),
            "Armageddon Blade": CatalogEntry(
                "Armageddon Blade", 132, "primary_weapons"
            ),
        },
    )


class ClientIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_ws_and_wss_uri_and_replay_skip(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cfg_path = root / "ap_config.json"
        cfg = ApConfig(
            host="localhost",
            port=38281,
            slot="War",
            password="",
            game="Darksiders",
            use_wss=False,
            tags=("Darksiders",),
            request_goal=False,
            uuid="test-uuid",
            path=cfg_path,
            mtime=0.0,
        )
        save_config(cfg, cfg_path)
        self.assertTrue(cfg.uri().startswith("ws://"))
        wss = ApConfig(**{**cfg.__dict__, "use_wss": True})
        self.assertTrue(wss.uri().startswith("wss://"))

        try:
            import websockets
        except ImportError:
            self.skipTest("websockets not installed")

        received_connect = asyncio.Event()
        replayed = asyncio.Event()
        items = [
            {"item": 59, "location": 1, "player": 1, "flags": 0, "class": "NetworkItem"}
        ]

        async def handler(ws, *args) -> None:
            await ws.send(
                encode_packets(
                    [
                        {
                            "cmd": "RoomInfo",
                            "seed_name": "seed-a",
                            "version": {
                                "major": 0,
                                "minor": 6,
                                "build": 7,
                                "class": "Version",
                            },
                            "tags": ["AP"],
                            "password": False,
                            "permissions": {},
                            "hint_cost": 0,
                            "location_check_points": 0,
                            "games": ["Darksiders"],
                            "datapackage_checksums": {},
                        }
                    ]
                )
            )
            raw = await ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            pkt = json.loads(raw)[0]
            self.assertEqual(pkt["cmd"], "Connect")
            self.assertEqual(pkt["name"], "War")
            received_connect.set()
            await ws.send(
                encode_packets(
                    [
                        {
                            "cmd": "Connected",
                            "team": 0,
                            "slot": 1,
                            "players": [],
                            "missing_locations": [],
                            "checked_locations": [],
                            "slot_info": {},
                            "hint_points": 0,
                        },
                        {"cmd": "ReceivedItems", "index": 0, "items": items},
                    ]
                )
            )
            await asyncio.sleep(0.2)
            await ws.send(
                encode_packets(
                    [{"cmd": "ReceivedItems", "index": 0, "items": items}]
                )
            )
            replayed.set()
            await asyncio.sleep(1.5)

        server = await websockets.serve(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        save_config(
            ApConfig(**{**cfg.__dict__, "port": port, "host": "127.0.0.1"}),
            cfg_path,
        )
        state = ApState(root / "ap_state.db")
        runtime = ApRuntime(state, _catalog(), config_path=cfg_path)
        runtime.start()
        try:
            await asyncio.wait_for(received_connect.wait(), timeout=8)
            await asyncio.wait_for(replayed.wait(), timeout=8)
            deadline = time.time() + 4
            while time.time() < deadline and state.item_count("seed-a", 0, 1, 59) < 1:
                await asyncio.sleep(0.05)
            self.assertEqual(state.item_count("seed-a", 0, 1, 59), 1)
            self.assertEqual(state.last_ingested_index("seed-a", 0, 1), 1)
            idxs: list[int] = []
            while not runtime.apply_queue.empty():
                idxs.append(runtime.apply_queue.get_nowait().idx)
            self.assertEqual(set(idxs), {0})
        finally:
            runtime.stop()
            state.close()
            server.close()
            await server.wait_closed()

    def test_parse_network_item_index(self) -> None:
        item = parse_network_item({"item": 1, "location": 2, "player": 3}, index=9)
        self.assertEqual(item.index, 9)


if __name__ == "__main__":
    unittest.main()
