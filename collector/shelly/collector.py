"""Collect Shelly H&T Gen3 full-status MQTT notifications as JSON lines."""

import json
import logging
import math
import os
import signal
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
# MQTT wildcards must occupy an entire topic level; filter the prefix locally.
MQTT_TOPIC = "+/events/rpc"


def parse_message(topic: str, payload: bytes, received_at: datetime) -> dict | None:
    """Ignore other devices/methods; reject malformed full-status messages."""
    levels = topic.split("/")
    if (len(levels) != 3 or levels[1:] != ["events", "rpc"]
            or not levels[0].startswith("shellyhtg3-")
            or levels[0] == "shellyhtg3-"):
        return None

    body = json.loads(payload)
    if not isinstance(body, dict):
        raise ValueError("Notification must be a JSON object")
    if body.get("method") != "NotifyFullStatus":
        return None

    params = body["params"]
    record = {
        "device": levels[0],
        "temperature_c": params["temperature:0"]["tC"],
        "humidity_pct": params["humidity:0"]["rh"],
        "wifi_rssi": params["wifi"]["rssi"],
        "device_ts": params["ts"],
    }
    for key, value in record.items():
        if key != "device" and (isinstance(value, bool)
                or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError(f"{key} must be a finite number")
    record["collector_received_at"] = received_at.astimezone(timezone.utc).isoformat()
    return record


def on_message(client, userdata, message) -> None:
    received_at = datetime.now(timezone.utc)
    try:
        record = parse_message(message.topic, message.payload, received_at)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        logger.warning("Skipping invalid notification on %s: %s", message.topic, exc)
        return
    if record is not None:
        print(json.dumps(record, allow_nan=False, separators=(",", ":")), flush=True)
        if userdata is not None:
            userdata.submit(record)


def on_connect(client, userdata, flags, reason_code, properties) -> None:
    if reason_code.is_failure:
        logger.error("MQTT connection rejected: %s", reason_code)
        return
    result, _ = client.subscribe(MQTT_TOPIC, qos=1)
    if result != 0:
        raise RuntimeError(f"MQTT subscription failed: {result}")
    logger.info("Connected; subscribing to %s", MQTT_TOPIC)


def on_subscribe(client, userdata, mid, reason_codes, properties) -> None:
    if any(code.is_failure for code in reason_codes):
        raise RuntimeError(f"Broker rejected MQTT subscription: {reason_codes}")


def main() -> None:
    import paho.mqtt.client as mqtt
    from metrics import MetricsPublisher

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    locations = {}
    if os.environ.get("DEVICES_FILE"):
        with open(os.environ["DEVICES_FILE"], encoding="utf-8") as file:
            devices = json.load(file)
        if not isinstance(devices, list):
            raise ValueError("Device configuration must be a JSON list")
        for device in devices:
            if (not isinstance(device, dict)
                    or not isinstance(device.get("device_id"), str)
                    or not device["device_id"].startswith("shellyhtg3-")
                    or not isinstance(device.get("location"), str)
                    or not device["location"]):
                raise ValueError("Each device needs a shellyhtg3- device_id and location")
            if device["device_id"] in locations:
                raise ValueError("Duplicate device_id in device configuration")
            locations[device["device_id"]] = device["location"]
    publisher = MetricsPublisher(os.environ.get(
        "PUSHGATEWAY_URL", "http://pushgateway.monitoring.svc:9091"), locations)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=publisher)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.enable_logger(logger)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    signal.signal(signal.SIGTERM, lambda *_: client.disconnect())
    signal.signal(signal.SIGINT, lambda *_: client.disconnect())
    client.connect_async(os.environ.get("MQTT_HOST", "mosquitto"),
                         int(os.environ.get("MQTT_PORT", "1883")), keepalive=60)
    try:
        publisher.start()
        client.loop_forever(retry_first_connection=True)
    finally:
        client.disconnect()
        publisher.stop()


if __name__ == "__main__":
    main()
