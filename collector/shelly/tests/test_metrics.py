import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from collector import on_message
from metrics import MetricsPublisher, push_reading


def reading(device="shellyhtg3-000000000001", temperature=22.5):
    return {"device": device, "temperature_c": temperature, "humidity_pct": 48,
            "wifi_rssi": -62, "device_ts": 1790856000.5,
            "collector_received_at": "2026-10-01T12:00:00+00:00"}


class MetricsTests(unittest.TestCase):
    def test_real_client_encodes_http_put_and_prometheus_payload(self):
        opener = Mock()
        opener.open.return_value.code = 200
        with patch("prometheus_client.exposition.build_opener", return_value=opener):
            push_reading("http://gateway:9091", reading(), "LivingRoom")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.full_url,
                         "http://gateway:9091/metrics/job/shelly_thermometers/device_id/"
                         "shellyhtg3-000000000001")
        self.assertIn(b'shelly_temperature_celsius{device_id="shellyhtg3-000000000001",'
                      b'location="LivingRoom"} 22.5', request.data)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 5)

    def test_metric_values_labels_and_device_group(self):
        with patch("prometheus_client.push_to_gateway") as push:
            push_reading("http://gateway:9091", reading(), "LivingRoom")
        kwargs = push.call_args.kwargs
        self.assertEqual(kwargs["job"], "shelly_thermometers")
        self.assertEqual(kwargs["grouping_key"], {"device_id": reading()["device"]})
        self.assertEqual(kwargs["timeout"], 5)
        registry = kwargs["registry"]
        labels = {"device_id": reading()["device"], "location": "LivingRoom"}
        for name, value in {
            "shelly_temperature_celsius": 22.5, "shelly_humidity_percent": 48,
            "shelly_wifi_rssi_dbm": -62, "shelly_device_timestamp_seconds": 1790856000.5,
            "shelly_last_received_unixtime": 1790856000,
        }.items():
            self.assertEqual(registry.get_sample_value(name, labels), value)

    def test_retries_failures_and_preserves_other_devices(self):
        publisher = MetricsPublisher("gateway", {reading()["device"]: "LivingRoom"})
        publisher.submit(reading())
        publisher.submit(reading(temperature=25))
        publisher.submit(reading("shellyhtg3-000000000002"))
        with patch("metrics.push_reading", side_effect=[OSError("offline"), None]) as push:
            with self.assertLogs("metrics", level="ERROR"):
                publisher.flush()
        self.assertEqual(push.call_count, 2)
        self.assertEqual(push.call_args_list[0].args[1]["temperature_c"], 25)
        self.assertEqual(push.call_args_list[0].args[2], "LivingRoom")
        self.assertEqual(push.call_args_list[1].args[2], "shellyhtg3-000000000002")
        self.assertEqual(list(publisher.pending), [reading()["device"]])
        with patch("metrics.push_reading"):
            publisher.flush()
        self.assertEqual(publisher.pending, {})

    def test_reading_arriving_during_push_is_not_removed(self):
        publisher = MetricsPublisher("gateway")
        publisher.submit(reading())
        with patch("metrics.push_reading", side_effect=lambda *_: publisher.submit(reading(temperature=24))):
            publisher.flush()
        self.assertEqual(publisher.pending[reading()["device"]]["temperature_c"], 24)

    def test_callback_queues_only_accepted_readings_and_keeps_json(self):
        publisher = Mock()
        body = {"method": "NotifyFullStatus", "params": {
            "temperature:0": {"tC": 22.5}, "humidity:0": {"rh": 48},
            "wifi": {"rssi": -62}, "ts": 1790856000.5}}
        message = SimpleNamespace(topic=reading()["device"] + "/events/rpc",
                                  payload=json.dumps(body).encode())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            on_message(None, publisher, message)
        publisher.submit.assert_called_once_with(json.loads(out.getvalue()))
        body["method"] = "NotifyStatus"
        message.payload = json.dumps(body).encode()
        on_message(None, publisher, message)
        self.assertEqual(publisher.submit.call_count, 1)


if __name__ == "__main__":
    unittest.main()
