# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A two-Raspberry-Pi pipeline that reads Swedish electricity-meter HAN-port telegrams over
serial, relays them over a LoRa radio link, and publishes the parsed values to an MQTT
broker (with Home Assistant MQTT discovery). This repo is the **dev/source copy**; the
production copies run directly on the two Pis and are not deployed via `git pull` — see
"Deploying to the Pis" below.

Protocol details (telegram framing, CRC, OBIS codes) are documented in
`docs/HAN_port_protocol_reference.md` — read that before touching parsing logic.

## Architecture

Two physically separate Raspberry Pi Zero boards, connected only by LoRa radio (no
shared network in the data path):

- **rpizero3** (transmit side, next to the electricity meter): reads HAN telegrams from
  `/dev/ttyUSB0` (115200 8N1) and forwards each line as a separate LoRa packet over
  `/dev/ttyS0` via the SX126x LoRa HAT. Serial reads happen on a background thread into a
  `queue.Queue`, decoupling USB reads from LoRa send timing.
- **rpizero4** (receive side, has WiFi/internet): receives LoRa packets, reassembles them
  into full telegrams, verifies the CRC16/IBM checksum, parses the OBIS-style data lines,
  drives a small I2C SSD1306 OLED status display, and publishes each value to an MQTT
  broker (`thunholm.homelinux.com`) with retained Home Assistant discovery configs.

### Active production scripts vs. legacy/demo scripts

Each of the two roles has one active script and one legacy vendor-demo script left in the
repo for reference — **don't assume both are equally relevant**:

| Role | Active (runs in production) | Legacy/demo (not run) |
|---|---|---|
| Transmit (rpizero3) | `Lora_transmit_han.py` | `new_main.py` (interactive keyboard-driven vendor sample; has the same USB-reader-thread/queue pattern bolted on but keeps the unused menu loop) |
| Receive (rpizero4) | `lora_receiver_chsum_oled_v2.py` | `main_mod.py` (interactive keyboard-driven vendor sample, no MQTT/OLED/telegram parsing) |

Verify which script is actually running before assuming behavior — check the `screen`
session (see below), not just file names.

### LoRa driver: two versions, not interchangeable

- `sx126x.py` — original vendor driver. `receive()` only prints incoming data and returns
  `None`; it does not hand back parsed packets. Fine on the transmit side (which never
  calls `receive()`), broken for anything that needs to consume received data.
  `get_settings()` is also buggy (references bare `M1`/`lora_air_speed_dic` instead of
  `self.M1`/`self.lora_air_speed_dic`).
- `sx126x_mod.py` — patched version. `receive()` maintains a persistent `_rx_buffer`
  across calls and returns a list of complete payload chunks (framing: 3-byte header +
  payload ending in `\r\n` + optional trailing RSSI byte), correctly handling packets that
  arrive faster than `receive()` is polled, or split across reads. This is what
  `lora_receiver_chsum_oled_v2.py` and `main_mod.py` import as `sx126x`.

When editing driver logic, edit `sx126x_mod.py`, not `sx126x.py`, unless the change is
specifically for the transmit-only path.

### Telegram parsing (`lora_receiver_chsum_oled_v2.py`)

- `extract_frame()` locates the telegram between `/` and `!`, and reads the following
  4 hex chars as the CRC16 field.
- `process_payload()` currently maps data to fields by **fixed line index** (e.g. line 23
  → L1 voltage) rather than by OBIS code. This is fragile if a meter/firmware ever
  omits or reorders lines — parsing by OBIS code would be more robust if this ever breaks.
- `SENSOR_DEFS` controls both the MQTT topic naming and the Home Assistant discovery
  payloads; `SITE_ID`/`SITE_NAME` must be changed per physical installation site (it
  namespaces MQTT topics so multiple sites don't collide on the same broker).
- MQTT client uses paho-mqtt v2's callback API (`CallbackAPIVersion.VERSION2`) — if you
  see the old-style `on_connect(client, userdata, flags, rc)` signature anywhere, that's
  the outdated v1 form and won't work against this paho-mqtt version.
- MQTT credentials are hardcoded in plaintext in this file (`MQTT_USER`/`MQTT_PASS`).

## Working with the hardware

There is no local build/lint/test tooling in this repo (no test suite, no linter config,
no requirements.txt) — changes are validated by deploying to the actual Pi hardware and
observing the live `screen` session output, since the code depends on physical
GPIO/serial/I2C hardware that can't be simulated.

### Reaching the Pis

SSH via Tailscale hostnames (not `.local`/mDNS, which is unreliable): `ssh peter@rpizero3`,
`ssh peter@rpizero4`. Passwordless key auth is already set up for the `peter` user; the
`pi` user is password-only and unusable non-interactively. `sudo` requires a password on
both boards (no NOPASSWD configured) — actions needing `sudo` (e.g. shutdown) must be run
interactively by a human, not scripted over SSH.

### Deploying a change

Production files live at
`~/Lora_hat/SX126X_LoRa_HAT_Code/raspberrypi/python/` on each Pi. After editing locally,
`scp` the changed file(s) to the matching path on the matching Pi (transmit changes →
rpizero3, receive changes → sx126x_mod.py or the receiver script on rpizero4).

### Running / restarting

Each Pi runs its active script inside a detached `screen` session named `lora_hat`:

```
screen -r lora_hat          # attach and view live output
# Ctrl-C to stop the running script, then re-launch, e.g. on rpizero4:
source /home/peter/Lora_hat/myvenv/bin/activate
python3 lora_receiver_chsum_oled_v2.py
```

Non-interactively (e.g. from a script), you can dump the session's current screen
contents without attaching: `screen -S lora_hat -X hardcopy -h /tmp/dump.txt`.

The receiver's venv (`/home/peter/Lora_hat/myvenv`) on rpizero4 has the extra packages
(`libscrc`, `paho-mqtt`, `adafruit-blinka`, `adafruit-ssd1306`) that the system Python
lacks — always activate it before running the receiver script.

## Reference docs
     - docs/HAN_port_protocol_reference.md — Swedish HAN port telegram/OBIS protocol reference
