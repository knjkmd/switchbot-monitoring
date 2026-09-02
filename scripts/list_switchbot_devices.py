# scripts/list_switchbot_devices.py

import base64
import hashlib
import hmac
import os
import time
import uuid

import requests


def authentication_headers(token: str, secret: str) -> dict[str, str]:
    nonce = str(uuid.uuid4())
    timestamp = str(int(time.time() * 1000))
    message = f"{token}{timestamp}{nonce}"

    signature = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return {
        "Authorization": token,
        "sign": signature,
        "t": timestamp,
        "nonce": nonce,
        "Content-Type": "application/json; charset=utf-8",
    }


def main() -> None:
    token = os.environ["SWITCHBOT_TOKEN"]
    secret = os.environ["SWITCHBOT_SECRET"]

    response = requests.get(
        "https://api.switch-bot.com/v1.1/devices",
        headers=authentication_headers(token, secret),
        timeout=10,
    )
    response.raise_for_status()

    body = response.json().get("body", {})

    print("--- Physical Devices ---")
    for device in body.get("deviceList", []):
        print(
            f"Name: {device.get('deviceName')} | "
            f"Type: {device.get('deviceType')} | "
            f"ID: {device.get('deviceId')}"
        )

    print("\n--- Infrared Remotes ---")
    for remote in body.get("infraredRemoteList", []):
        print(
            f"Name: {remote.get('deviceName')} | "
            f"Type: {remote.get('remoteType')} | "
            f"ID: {remote.get('deviceId')}"
        )


if __name__ == "__main__":
    main()