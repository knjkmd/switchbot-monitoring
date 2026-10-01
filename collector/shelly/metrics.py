"""Publish latest Shelly readings without blocking the MQTT network loop."""

import logging
from datetime import datetime
from threading import Event, Lock, Thread

logger = logging.getLogger(__name__)


def push_reading(gateway, record, location):
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

    registry = CollectorRegistry()
    values = {
        "shelly_temperature_celsius": ("Shelly temperature in Celsius", record["temperature_c"]),
        "shelly_humidity_percent": ("Shelly relative humidity", record["humidity_pct"]),
        "shelly_wifi_rssi_dbm": ("Shelly Wi-Fi signal strength in dBm", record["wifi_rssi"]),
        "shelly_device_timestamp_seconds": ("Timestamp reported by Shelly", record["device_ts"]),
        "shelly_last_received_unixtime": (
            "Collector receipt time of the latest Shelly notification",
            datetime.fromisoformat(record["collector_received_at"]).timestamp()),
    }
    for name, (description, value) in values.items():
        Gauge(name, description, ["device_id", "location"], registry=registry).labels(
            device_id=record["device"], location=location).set(value)
    # One group per device prevents an update from removing other devices.
    push_to_gateway(gateway, job="shelly_thermometers", registry=registry,
                    grouping_key={"device_id": record["device"]}, timeout=5)


class MetricsPublisher:
    def __init__(self, gateway, locations=None):
        self.gateway = gateway
        self.locations = locations or {}
        self.pending = {}
        self.lock = Lock()
        self.stop_event = Event()
        self.thread = Thread(target=self.run, name="shelly-metrics", daemon=True)

    def submit(self, record):
        with self.lock:
            self.pending[record["device"]] = record

    def flush(self):
        with self.lock:
            snapshot = dict(self.pending)
        for device, record in snapshot.items():
            try:
                push_reading(self.gateway, record, self.locations.get(device, device))
            except OSError:
                logger.exception("Pushgateway push failed for %s; will retry", device)
                continue
            with self.lock:
                if self.pending.get(device) is record:
                    del self.pending[device]

    def run(self):
        while not self.stop_event.wait(5):
            self.flush()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=6)
