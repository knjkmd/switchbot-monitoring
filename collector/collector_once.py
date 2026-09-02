"""
SwitchBot Thermometer Collector

Fetches temperature and humidity data from the SwitchBot API
and pushes metrics to Prometheus Pushgateway.

Designed to run as a Kubernetes CronJob.
"""

import json
import logging
import os
import time
import urllib.error
import requests
from typing import Dict, List, Tuple
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway


# ----------------------------------------------------------------------
# Logging Configuration
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
def load_config() -> dict:
    """Load credentials and the device list from the environment."""
    try:
        devices_file = os.environ.get("DEVICES_FILE")
        if devices_file:
            with open(devices_file, encoding="utf-8") as file:
                devices = json.load(file)
        else:
            # Keep single-device configuration available for local testing.
            devices = [{
                "device_id": os.environ["DEVICE_ID"],
                "location": os.environ["LOCATION"],
            }]

        if not isinstance(devices, list) or not devices:
            raise ValueError("Device configuration must be a non-empty JSON list")

        for device in devices:
            if not isinstance(device, dict):
                raise ValueError("Every device entry must be a JSON object")
            if not device.get("device_id") or not device.get("location"):
                raise ValueError(
                    "Every device requires non-empty device_id and location values"
                )

        return {
            "token": os.environ["SWITCHBOT_TOKEN"],
            "devices": devices,
            "pushgateway": os.environ.get(
                "PUSHGATEWAY_URL",
                "http://pushgateway:9091"
            ),
            "job_name": "switchbot_thermometers",
        }
    except KeyError as e:
        logger.error(f"Missing required environment variable: {e}")
        raise
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.error(f"Invalid device configuration: {e}")
        raise


# ----------------------------------------------------------------------
# SwitchBot API
# ----------------------------------------------------------------------
def fetch_switchbot_status(token: str, device_id: str) -> Tuple[float, float]:
    """
    Call SwitchBot API and return (temperature, humidity).
    """
    logger.info(f"Fetching data for device {device_id}")

    url = f"https://api.switch-bot.com/v1.1/devices/{device_id}/status"

    try:
        response = requests.get(
            url,
            headers={"Authorization": token},
            timeout=10,
        )
        response.raise_for_status()

        body = response.json()["body"]
        temperature = body["temperature"]
        humidity = body["humidity"]

        logger.info(
            f"Retrieved data | Temp: {temperature}°C | Humidity: {humidity}%"
        )

        return temperature, humidity

    except requests.exceptions.RequestException as e:
        logger.error(f"SwitchBot API request failed: {e}")
        raise
    except (KeyError, ValueError) as e:
        logger.error(f"Invalid API response format: {e}")
        raise


# ----------------------------------------------------------------------
# Prometheus Push
# ----------------------------------------------------------------------
def push_metrics(
    pushgateway: str,
    job_name: str,
    devices: List[dict],
    readings: Dict[str, Tuple[float, float]],
) -> None:
    """Push one registry containing the results for all configured devices."""

    registry = CollectorRegistry()

    temperature_gauge = Gauge(
        "switchbot_temperature_celsius",
        "Temperature from SwitchBot thermometer",
        ["device_id", "location"],
        registry=registry,
    )

    humidity_gauge = Gauge(
        "switchbot_humidity_percent",
        "Humidity from SwitchBot thermometer",
        ["device_id", "location"],
        registry=registry,
    )

    collection_success_gauge = Gauge(
        "switchbot_collection_success",
        "Whether the latest collection attempt succeeded (1) or failed (0)",
        ["device_id", "location"],
        registry=registry,
    )

    last_success_gauge = Gauge(
        "switchbot_last_success_unixtime",
        "Unix timestamp of the latest successful collection in this run",
        ["device_id", "location"],
        registry=registry,
    )

    collected_at = time.time()
    for device in devices:
        device_id = device["device_id"]
        location = device["location"]
        labels = {"device_id": device_id, "location": location}
        reading = readings.get(device_id)

        if reading is None:
            collection_success_gauge.labels(**labels).set(0)
            continue

        temperature, humidity = reading
        temperature_gauge.labels(**labels).set(temperature)
        humidity_gauge.labels(**labels).set(humidity)
        collection_success_gauge.labels(**labels).set(1)
        last_success_gauge.labels(**labels).set(collected_at)

    try:
        logger.info(f"Pushing metrics to {pushgateway}")
        push_to_gateway(
            pushgateway,
            job=job_name,
            registry=registry,
        )
        logger.info("Metrics pushed successfully")

    except (OSError, urllib.error.URLError) as e:
        logger.error(f"Failed to push metrics: {e}")
        raise


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    config = load_config()
    readings = {}

    for device in config["devices"]:
        device_id = device["device_id"]
        location = device["location"]
        try:
            readings[device_id] = fetch_switchbot_status(
                config["token"],
                device_id,
            )
        except Exception:
            logger.exception(
                "Collection failed | device=%s | location=%s",
                device_id,
                location,
            )

    push_metrics(
        config["pushgateway"],
        config["job_name"],
        config["devices"],
        readings,
    )

    if not readings:
        raise RuntimeError("Collection failed for every configured device")


if __name__ == "__main__":
    main()
