"""
SwitchBot Thermometer Collector

Fetches temperature and humidity data from the SwitchBot API
and pushes metrics to Prometheus Pushgateway.

Designed to run as a Kubernetes CronJob.
"""

import os
import time
import random
import logging
import requests
from typing import Tuple
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
    """Load configuration from environment variables."""
    try:
        return {
            "token": os.environ["SWITCHBOT_TOKEN"],
            "device_id": os.environ["DEVICE_ID"],
            "location": os.environ["LOCATION"],
            "pushgateway": os.environ.get(
                "PUSHGATEWAY_URL",
                "http://pushgateway:9091"
            ),
            "job_name": "switchbot_thermometer",
        }
    except KeyError as e:
        logger.error(f"Missing required environment variable: {e}")
        raise


# ----------------------------------------------------------------------
# SwitchBot API
# ----------------------------------------------------------------------
def fetch_switchbot_status(token: str, device_id: str) -> Tuple[float, float]:
    """
    Call SwitchBot API and return (temperature, humidity).
    """
    logger.info(f"Fetching data for device {device_id}")

    # Random delay to avoid burst API calls
    time.sleep(random.randint(0, 30))

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
    device_id: str,
    location: str,
    temperature: float,
    humidity: float,
) -> None:
    """Push metrics to Prometheus Pushgateway."""

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

    temperature_gauge.labels(
        device_id=device_id,
        location=location
    ).set(temperature)

    humidity_gauge.labels(
        device_id=device_id,
        location=location
    ).set(humidity)

    try:
        logger.info(f"Pushing metrics to {pushgateway}")
        push_to_gateway(
            pushgateway,
            job=job_name,
            grouping_key={
                "device_id": device_id,
                "location": location,
            },
            registry=registry,
        )
        logger.info("Metrics pushed successfully")

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to push metrics: {e}")
        raise


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    config = load_config()

    temperature, humidity = fetch_switchbot_status(
        config["token"],
        config["device_id"],
    )

    push_metrics(
        config["pushgateway"],
        config["job_name"],
        config["device_id"],
        config["location"],
        temperature,
        humidity,
    )


if __name__ == "__main__":
    main()