import os
import requests
import logging
from datetime import datetime, timezone
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
import random, time

# ---- Logging Configuration ----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ---- Config from env (K8s-friendly) ----
SWITCHBOT_TOKEN = os.environ["SWITCHBOT_TOKEN"]
DEVICE_ID = os.environ["DEVICE_ID"]
LOCATION = os.environ["LOCATION"]

MONGODB_URI = os.environ.get(
    "MONGODB_URI",
    "mongodb://mongodb:27017"
)

PUSHGATEWAY = os.environ.get(
    "PUSHGATEWAY_URL",
    "http://pushgateway:9091"
)

JOB_NAME = "switchbot_thermometer"

# ---- Call SwitchBot API ----
try:
    time.sleep(random.randint(0, 30))  # Random delay to avoid simultaneous API calls
    logging.info(f"Calling SwitchBot API for device {DEVICE_ID}")
    resp = requests.get(
        f"https://api.switch-bot.com/v1.1/devices/{DEVICE_ID}/status",
        headers={"Authorization": SWITCHBOT_TOKEN},
        timeout=10,
    )
    resp.raise_for_status()
    
    body = resp.json()["body"]
    
    temperature = body["temperature"]
    humidity = body["humidity"]
    #battery = body["battery"]
    
#    logging.info(f"Successfully retrieved SwitchBot data - Temp: {temperature}°C, Humidity: {humidity}%, Battery: {battery}%")
    logging.info(f"Successfully retrieved SwitchBot data - Temp: {temperature}°C, Humidity: {humidity}%")
except requests.exceptions.Timeout:
    logging.error("SwitchBot API call timed out after 10 seconds")
    raise
except requests.exceptions.HTTPError as e:
    logging.error(f"SwitchBot API returned HTTP error: {e.response.status_code} - {e.response.text}")
    raise
except requests.exceptions.RequestException as e:
    logging.error(f"SwitchBot API request failed: {e}")
    raise
except (KeyError, ValueError) as e:
    logging.error(f"Failed to parse SwitchBot API response: {e}")
    raise

# ---- Push metrics (one-shot) ----
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

# battery_gauge = Gauge(
#     "switchbot_battery_percent",
#     "Battery level",
#     ["device_id", "location"],
#     registry=registry,
# )

temperature_gauge.labels(device_id=DEVICE_ID, location=LOCATION).set(temperature)
humidity_gauge.labels(device_id=DEVICE_ID, location=LOCATION).set(humidity)
#battery_gauge.labels(device_id=DEVICE_ID, location=LOCATION).set(battery)

# ---- Push metrics to Pushgateway ----
try:
    logging.info(f"Pushing metrics to Pushgateway at {PUSHGATEWAY}")
    push_to_gateway(
        PUSHGATEWAY,
        job=JOB_NAME,
        grouping_key={
           "device_id": DEVICE_ID,
            "location": LOCATION
        },
        registry=registry,
    )
    logging.info("Successfully pushed metrics to Pushgateway")
except requests.exceptions.Timeout:
    logging.error(f"Pushgateway connection timed out at {PUSHGATEWAY}")
    raise
except requests.exceptions.ConnectionError as e:
    logging.error(f"Failed to connect to Pushgateway at {PUSHGATEWAY}: {e}")
    raise
except requests.exceptions.RequestException as e:
    logging.error(f"Pushgateway request failed: {e}")
    raise
except Exception as e:
    logging.error(f"Unexpected error while pushing to Pushgateway: {e}")
    raise

