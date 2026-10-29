# MQTT Mailbox (`mqtt_mailbox.py`)

A lightweight, **zero-dependency** Python 3 MQTT client and CLI tool designed to send structured notifications, alerts, and telemetry payloads to an MQTT broker (such as Home Assistant / Mosquitto).

Built entirely using the Python 3 standard library (`socket`, `struct`, `json`, `argparse`) — no `pip install` or virtual environment required.

---

## Features

- **Zero External Dependencies**: Implements MQTT v3.1.1 `CONNECT` and `PUBLISH` packets directly over standard library TCP sockets.
- **Built-in `.env` Loader**: Automatically reads configuration from a `.env` file without requiring `python-dotenv`.
- **Dual Usage**: Works both as a standalone CLI script (for Bash, cron jobs, systemd hooks) and as an importable Python module.
- **Rich JSON Envelope**: Automatically attaches device metadata (hostname, local IP, MAC address, ISO-8601 timestamp, severity level, tags, and custom key-value data).

---

## Configuration

Copy the example configuration file and set your MQTT broker credentials:

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env`:

```dotenv
MQTT_HOST=192.168.1.20
MQTT_PORT=1883
MQTT_USER=your-mqtt-username
MQTT_PASS="your-mqtt-password"
MQTT_TOPIC=homeassistant/mailbox
```

### `.env` Lookup Order
When executed, `mqtt_mailbox.py` searches for a `.env` file in the following order:
1. Path specified via `--env-file` or the `$MQTT_ENV_FILE` environment variable.
2. `./.env` (current working directory).
3. `<script_directory>/.env` (next to `mqtt_mailbox.py`).
4. `~/.config/mqtt_mailbox/.env` (user-level config when installed globally in `/usr/local/bin`).

---

## CLI Usage

Make the script executable:

```bash
chmod +x mqtt_mailbox.py
```

### Basic Message
```bash
./mqtt_mailbox.py "System rebooted successfully"
```

### With Title, Severity Level, Tags, and Key-Value Telemetry
```bash
./mqtt_mailbox.py "Backup completed" \
  -t "Nightly Backup" \
  -l success \
  --tag cron --tag backup \
  -k size_mb=420 -k duration_s=18.4
```

### Reading from `stdin` (Pipes)
```bash
df -h / | ./mqtt_mailbox.py -t "Disk Usage Report" -l warning
```

### Silent Log (No Push Notification)
```bash
./mqtt_mailbox.py "Heartbeat check" --no-push -k cpu_temp=54.2
```

### CLI Options
```text
usage: mqtt_mailbox.py [-h] [-t TITLE] [-s SENDER]
                       [-l {info,success,warning,error,critical}] [-d DATA]
                       [-k KV] [--tag TAGS] [--no-push] [--env-file ENV_FILE]
                       [--host HOST] [--port PORT] [--user USER]
                       [--password PASSWORD] [--topic TOPIC]
                       [message]
```

---

## Python Module Usage

You can import `send_mailbox` in any Python script:

```python
from mqtt_mailbox import send_mailbox

send_mailbox(
    "Database snapshot finished",
    title="PostgreSQL Backup",
    level="success",
    tags=["db", "cron"],
    data={"size_mb": 512, "tables": 24},
)
```

---

## Payload Format

Messages are published to `<MQTT_TOPIC>/<sender>` as a JSON payload:

```json
{
  "sender": "raspberrypi",
  "title": "Nightly Backup",
  "message": "Backup completed",
  "level": "success",
  "ip": "192.168.1.50",
  "mac": "AA:BB:CC:DD:EE:FF",
  "tags": ["cron", "backup"],
  "data": {
    "size_mb": 420,
    "duration_s": 18.4
  },
  "notify": true,
  "sent_at": "2026-10-28T22:50:00-06:00"
}
```
