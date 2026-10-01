import contextlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from collector import MQTT_TOPIC, on_connect, on_message, on_subscribe, parse_message


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.topic = "shellyhtg3-000000000001/events/rpc"
        self.body = {
            "method": "NotifyFullStatus",
            "params": {
                "temperature:0": {"tC": 22.5},
                "humidity:0": {"rh": 48},
                "wifi": {"rssi": -62},
                "ts": 1790856000.5,
            },
        }
        self.now = datetime(2026, 10, 1, 14, tzinfo=timezone(timedelta(hours=2)))

    def parse(self):
        return parse_message(self.topic, json.dumps(self.body).encode(), self.now)

    def test_extracts_exact_fields_and_converts_to_utc(self):
        self.assertEqual(self.parse(), {
            "device": "shellyhtg3-000000000001",
            "temperature_c": 22.5,
            "humidity_pct": 48,
            "wifi_rssi": -62,
            "device_ts": 1790856000.5,
            "collector_received_at": "2026-10-01T12:00:00+00:00",
        })

    def test_ignores_other_methods(self):
        for method in ("NotifyStatus", "NotifyEvent", None):
            self.body = {"method": method}
            self.assertIsNone(self.parse())

    def test_ignores_unrelated_topics_before_decoding(self):
        for topic in ("shellyplus-abc/events/rpc", "shellyhtg3-/events/rpc",
                      "shellyhtg3-abc/status/rpc", "shellyhtg3-abc/events/rpc/extra"):
            self.assertIsNone(parse_message(topic, b"invalid", self.now))

    def test_invalid_payload_does_not_write_stdout_or_stop_callback(self):
        invalid = [b"invalid", b"\xff", b"[]", b"null",
                   b'{"method":"NotifyFullStatus"}']
        for params in (None, [], {}, {"temperature:0": None}):
            invalid.append(json.dumps({"method": "NotifyFullStatus", "params": params}).encode())
        for payload in invalid:
            with self.subTest(payload=payload), contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertLogs("collector", level="WARNING"):
                    on_message(None, None, SimpleNamespace(topic=self.topic, payload=payload))
                self.assertEqual(out.getvalue(), "")

    def test_rejects_missing_and_invalid_measurements(self):
        for value in (None, "22.5", True, float("nan"), float("inf")):
            self.body["params"]["temperature:0"]["tC"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse()
        del self.body["params"]["humidity:0"]
        with self.assertRaises(KeyError):
            self.parse()

    def test_callback_outputs_one_json_line(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            on_message(None, None, SimpleNamespace(
                topic=self.topic, payload=json.dumps(self.body).encode()))
        self.assertEqual(len(out.getvalue().splitlines()), 1)
        record = json.loads(out.getvalue())
        self.assertEqual(record["temperature_c"], 22.5)
        self.assertEqual(datetime.fromisoformat(record["collector_received_at"]).utcoffset(), timedelta(0))

    def test_subscribes_on_every_connection_including_reconnect(self):
        client = Mock()
        client.subscribe.return_value = (0, 1)
        for _ in range(2):
            on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
        self.assertEqual(client.subscribe.call_count, 2)
        client.subscribe.assert_called_with(MQTT_TOPIC, qos=1)

    def test_connection_and_subscription_failure(self):
        client = Mock()
        with self.assertLogs("collector", level="ERROR"):
            on_connect(client, None, None, SimpleNamespace(is_failure=True), None)
        client.subscribe.assert_not_called()
        client.subscribe.return_value = (4, None)
        with self.assertRaises(RuntimeError):
            on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
        with self.assertRaises(RuntimeError):
            on_subscribe(client, None, 1, [SimpleNamespace(is_failure=True)], None)


if __name__ == "__main__":
    unittest.main()
