#!/usr/bin/env python3
"""
mqtt_mailbox.py - Generic MQTT Mailbox client.
Zero external dependencies (uses only the Python 3 standard library).
Can be used as a CLI tool from terminal/bash or imported as a Python module.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import socket
import struct
import sys
import uuid
from typing import Any


def load_dotenv(env_path: str | Path | None = None, *, override: bool = False) -> Path | None:
    """
    Loads environment variables from a .env file using only the standard library.
    Search order if env_path is not provided:
      1. $MQTT_ENV_FILE
      2. ./.env (current working directory)
      3. <script_dir>/.env (directory where mqtt_mailbox.py resides)
      4. ~/.config/mqtt_mailbox/.env
    """
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    elif os.environ.get("MQTT_ENV_FILE"):
        candidates.append(Path(os.environ["MQTT_ENV_FILE"]).expanduser())
    else:
        candidates.extend(
            [
                Path.cwd() / ".env",
                Path(__file__).resolve().parent / ".env",
                Path.home() / ".config" / "mqtt_mailbox" / ".env",
            ]
        )

    for path in candidates:
        if not path.is_file():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                else:
                    # Strip inline comments for unquoted values
                    val = val.split(" #", 1)[0].strip()
                if key and (override or key not in os.environ):
                    os.environ[key] = val
            return path
        except OSError:
            continue
    return None


# Load .env before reading default configuration
load_dotenv()

DEFAULT_HOST = os.environ.get("MQTT_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
DEFAULT_USER = os.environ.get("MQTT_USER", "")
DEFAULT_PASS = os.environ.get("MQTT_PASS", "")
DEFAULT_BASE_TOPIC = os.environ.get("MQTT_TOPIC", "mailbox")


def get_local_ip(target_host: str = DEFAULT_HOST) -> str:
    """Gets the local IP address used to reach the MQTT server."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target_host, 1883))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def get_mac_address() -> str:
    """Gets the current device's MAC address in XX:XX:XX:XX:XX:XX format."""
    node = uuid.getnode()
    return ":".join(f"{(node >> ele) & 0xFF:02X}" for ele in range(40, -1, -8))


def _mqtt_publish_raw(
    host: str,
    port: int,
    username: str,
    password: str,
    topic: str,
    payload: str | bytes,
    retain: bool = False,
    timeout: float = 5.0,
) -> None:
    """Publishes an MQTT v3.1.1 message using only standard library sockets."""

    def enc_str(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack("!H", len(b)) + b

    def enc_len(n: int) -> bytes:
        out = bytearray()
        while True:
            byte = n % 128
            n //= 128
            if n > 0:
                byte |= 0x80
            out.append(byte)
            if n == 0:
                break
        return bytes(out)

    client_id = f"mbox-{socket.gethostname()[:12]}-{os.getpid()}"
    conn_flags = 0x02  # CleanSession
    conn_payload = bytearray(enc_str(client_id))
    if username:
        conn_flags |= 0x80
        conn_payload.extend(enc_str(username))
        if password:
            conn_flags |= 0x40
            conn_payload.extend(enc_str(password))

    # Variable header: Protocol Name 'MQTT', Level 4 (v3.1.1), Connect Flags, KeepAlive 30s
    var_hdr = enc_str("MQTT") + bytes([4, conn_flags, 0, 30])
    conn_pkt = bytes([0x10]) + enc_len(len(var_hdr) + len(conn_payload)) + var_hdr + bytes(conn_payload)

    pub_hdr = 0x31 if retain else 0x30
    msg_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
    pub_body = enc_str(topic) + msg_bytes
    pub_pkt = bytes([pub_hdr]) + enc_len(len(pub_body)) + pub_body

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(conn_pkt)
        connack = sock.recv(4)
        if len(connack) < 4 or connack[3] != 0:
            code = connack[3] if len(connack) >= 4 else -1
            raise RuntimeError(f"MQTT authentication/connection error (CONNACK code={code})")
        sock.sendall(pub_pkt)
        sock.sendall(bytes([0xE0, 0x00]))  # DISCONNECT


def send_mailbox(
    message: str,
    *,
    title: str | None = None,
    sender: str | None = None,
    level: str = "info",
    tags: list[str] | None = None,
    data: dict[str, Any] | None = None,
    notify: bool = True,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    base_topic: str | None = None,
) -> dict[str, Any]:
    """
    Sends a message to the MQTT mailbox.
    Can be imported and called from any other Python script:
        from mqtt_mailbox import send_mailbox
        send_mailbox("Backup completed", title="Cron", level="success", data={"size_mb": 420})
    """
    resolved_host = host if host is not None else os.environ.get("MQTT_HOST", DEFAULT_HOST)
    resolved_port = port if port is not None else int(os.environ.get("MQTT_PORT", str(DEFAULT_PORT)))
    resolved_user = username if username is not None else os.environ.get("MQTT_USER", DEFAULT_USER)
    resolved_pass = password if password is not None else os.environ.get("MQTT_PASS", DEFAULT_PASS)
    resolved_topic = base_topic if base_topic is not None else os.environ.get("MQTT_TOPIC", DEFAULT_BASE_TOPIC)

    node_name = sender or socket.gethostname()
    local_ip = get_local_ip(resolved_host)
    mac_addr = get_mac_address()

    envelope = {
        "sender": node_name,
        "title": title or f"Message from {node_name}",
        "message": message,
        "level": level.lower(),
        "ip": local_ip,
        "mac": mac_addr,
        "tags": tags or [],
        "data": data or {},
        "notify": bool(notify),
        "sent_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(),
    }

    topic = f"{resolved_topic.rstrip('/')}/{node_name}"
    _mqtt_publish_raw(
        host=resolved_host,
        port=resolved_port,
        username=resolved_user,
        password=resolved_pass,
        topic=topic,
        payload=json.dumps(envelope, ensure_ascii=False),
        retain=False,
    )
    return envelope


def _parse_kv(items: list[str] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not items:
        return result
    for item in items:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        # Try to automatically parse numbers/booleans/JSON
        try:
            result[k.strip()] = json.loads(v)
        except Exception:
            result[k.strip()] = v
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sends messages and telemetry to an MQTT Mailbox."
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="Message content (if omitted, reads from stdin).",
    )
    parser.add_argument("-t", "--title", help="Message title.")
    parser.add_argument("-s", "--sender", help="Sender device/service name (default: hostname).")
    parser.add_argument(
        "-l",
        "--level",
        default="info",
        choices=["info", "success", "warning", "error", "critical"],
        help="Severity level (changes the push notification color).",
    )
    parser.add_argument(
        "-d",
        "--data",
        help="JSON string with additional data (e.g., '{\"temp\": 62.5, \"disk\": \"81%%\"}').",
    )
    parser.add_argument(
        "-k",
        "--kv",
        action="append",
        help="Additional key=value pair to attach to data (repeatable, e.g., -k temp=62.5 -k job='backup').",
    )
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        help="Optional tag (repeatable, e.g., --tag rpi --tag cron).",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Only save in history without triggering a push notification.",
    )
    parser.add_argument("--env-file", help="Path to a custom .env configuration file.")
    parser.add_argument("--host", help=f"MQTT broker IP/Host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, help=f"MQTT port (default: {DEFAULT_PORT})")
    parser.add_argument("--user", help="MQTT username")
    parser.add_argument("--password", help="MQTT password")
    parser.add_argument("--topic", help=f"Base MQTT topic (default: {DEFAULT_BASE_TOPIC})")

    args = parser.parse_args()

    if args.env_file:
        load_dotenv(args.env_file, override=True)

    msg = args.message
    if not msg:
        if not sys.stdin.isatty():
            msg = sys.stdin.read().strip()
        if not msg:
            parser.error("You must provide a message as an argument or via stdin.")

    extra_data: dict[str, Any] = {}
    if args.data:
        try:
            parsed = json.loads(args.data)
            if isinstance(parsed, dict):
                extra_data.update(parsed)
            else:
                extra_data["value"] = parsed
        except json.JSONDecodeError as e:
            parser.error(f"The --data argument is not valid JSON: {e}")

    extra_data.update(_parse_kv(args.kv))

    sent = send_mailbox(
        msg,
        title=args.title,
        sender=args.sender,
        level=args.level,
        tags=args.tags,
        data=extra_data,
        notify=not args.no_push,
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        base_topic=args.topic,
    )
    print(f"OK -> [{sent['sender']}] {sent['title']}: {sent['message']}")


if __name__ == "__main__":
    main()
