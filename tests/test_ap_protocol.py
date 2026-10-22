import unittest

from ds_client.ap_protocol import (
    ClientStatus,
    connect_packet,
    decode_packets,
    encode_packets,
    location_checks_packet,
    parse_network_item,
    status_update_packet,
)


class ProtocolTests(unittest.TestCase):
    def test_roundtrip_array(self) -> None:
        packets = [
            location_checks_packet([1, 2]),
            status_update_packet(ClientStatus.CLIENT_GOAL),
        ]
        raw = encode_packets(packets)
        back = decode_packets(raw)
        self.assertEqual(back[0]["cmd"], "LocationChecks")
        self.assertEqual(back[0]["locations"], [1, 2])
        self.assertEqual(back[1]["status"], 30)

    def test_single_object_payload(self) -> None:
        raw = '{"cmd":"RoomInfo","seed_name":"seed"}'
        packets = decode_packets(raw)
        self.assertEqual(packets[0]["seed_name"], "seed")

    def test_connect_packet(self) -> None:
        pkt = connect_packet(slot="War", uuid="abc")
        self.assertEqual(pkt["cmd"], "Connect")
        self.assertEqual(pkt["name"], "War")
        self.assertEqual(pkt["game"], "Darksiders")
        self.assertEqual(pkt["items_handling"], 0b111)
        self.assertEqual(pkt["version"]["class"], "Version")

    def test_parse_item_dict_and_tuple(self) -> None:
        a = parse_network_item(
            {"item": 133, "location": 0, "player": 2, "flags": 1}, index=4
        )
        self.assertEqual(a.item, 133)
        self.assertEqual(a.index, 4)
        b = parse_network_item((59, 10, 1, 0), index=0)
        self.assertEqual(b.item, 59)
        self.assertEqual(b.location, 10)


if __name__ == "__main__":
    unittest.main()
