# Swedish HAN Port Protocol — Reference Notes

Reference material for the DSMR-style telegrams read from the HAN port adapter on
`/dev/ttyUSB0`, matching the framing/CRC logic already implemented in
`lora_receiver_chsum_oled.py`.

Sources: Energiföretagen Sverige's "Branschrekommendation för lokalt kundgränssnitt
för elmätare" (industry recommendation for the local customer interface on
electricity meters), and the community reference site hanporten.se, which documents
the same recommendation in more implementation-friendly form. Both build on
IEC 62056-21 Mode D (itself based on the Dutch "P1 Companion Standard").

## Physical / serial layer

- Connector: RJ12 in Sweden (RJ45 in Norway, which uses a different M-Bus-based
  variant — not applicable to a Swedish HAN port).
- Serial settings: **115200 baud, 8N1** (8 data bits, no parity, 1 stop bit).
  This deviates from the base IEC 62056-21 spec (7E1) — Sweden's port is fixed at
  115200 8N1 regardless of what any identification field in the telegram implies.
- The port is unidirectional (meter → device only); nothing needs to be written
  back to the meter.
- A `DATA REQUEST` line must be held high (+5V) for the meter to start sending on
  `DATA OUT`. Many HAN dongles tie this permanently high.
- Telegrams are pushed automatically, typically **every 10 seconds** — the meter
  does not need to be polled.

## Telegram structure

Each telegram is plain ASCII, line-based, terminated by `\r\n`:

```
/XXXZ<meter identity>\r\n
\r\n
<data line 1>\r\n
<data line 2>\r\n
...
!<CRC16, 4 hex chars>\r\n
```

- First line starts with `/`, followed by a 3-letter manufacturer flag ID, a
  baud-rate indicator character (not meaningful here since baud is fixed), and the
  meter's unique identity string.
- A blank line marks the start of the data block.
- One or more data lines follow (see below).
- The block ends with a line starting with `!`, immediately followed by a 4-hex-digit
  CRC16 checksum covering every byte from the leading `/` through the `!` inclusive.

This lines up with what `extract_frame()` already does: locate `/`, locate the
following `!`, and treat the next 4 bytes as the CRC field.

## CRC

The checksum is a standard **CRC-16/IBM (ARC)** — the same one `libscrc.ibm()`
computes, which is why the existing receiver code works. It is calculated over the
raw bytes from `/` up to and including `!`.

## Data line format

```
OBIS(value*unit)\r\n
```

- Value and unit are separated by `*`. Timestamps and a few other fields have no
  unit, so there's no `*` in the parentheses for those lines.
- **OBIS** (used by DLMS/COSEM) identifies what the line represents, in the form
  `A-B:C.D.E` (a trailing `.F` group exists in the full standard but Swedish meters
  omit it since it's unused):
  - `A` — medium (1 = electricity)
  - `B` — channel
  - `C` — measured quantity (e.g. which phase/power type)
  - `D` — how it's measured (instantaneous vs. cumulative)
  - `E` — tariff (day/night rate, etc.)

## Common OBIS codes (Swedish recommendation)

| OBIS        | Meaning                              | Example value      |
|-------------|---------------------------------------|---------------------|
| 0-0:1.0.0   | Date & time (`YYMMDDhhmmssX`)         | `210217184019W`    |
| 1-0:1.8.0   | Cumulative active energy, import      | `00006678.394*kWh` |
| 1-0:2.8.0   | Cumulative active energy, export      | `00000000.000*kWh` |
| 1-0:3.8.0   | Cumulative reactive energy, import    | `00000021.988*kvarh` |
| 1-0:4.8.0   | Cumulative reactive energy, export    | `00001020.971*kvarh` |
| 1-0:1.7.0   | Instantaneous active power, import (3-phase total) | `0001.727*kW` |
| 1-0:2.7.0   | Instantaneous active power, export (3-phase total) | `0000.000*kW` |
| 1-0:21.7.0  | L1 active power, import               | `0001.023*kW`       |
| 1-0:41.7.0  | L2 active power, import               | `0000.353*kW`       |
| 1-0:61.7.0  | L3 active power, import               | `0000.000*kW`       |
| 1-0:32.7.0  | L1 voltage (RMS)                      | `240.3*V`            |
| 1-0:52.7.0  | L2 voltage (RMS)                      | `240.1*V`            |
| 1-0:72.7.0  | L3 voltage (RMS)                      | `241.3*V`            |
| 1-0:31.7.0  | L1 current (RMS)                      | `004.2*A`             |
| 1-0:51.7.0  | L2 current (RMS)                      | `001.6*A`             |
| 1-0:71.7.0  | L3 current (RMS)                      | `001.7*A`             |

"Import" (Swedish: *uttag*) = power drawn from the grid; "export" (*inmatning*) =
power fed back into the grid (relevant if there's local solar generation).

Time in the timestamp field is Swedish standard time (UTC+1) — Swedish meters do not
adjust for daylight saving; a trailing `S`/`W` character flags summer/winter time and
can generally be ignored.

## Notes relevant to this project

- `process_payload()` in the receiver currently maps fixed line *indices* (e.g. line
  2 → datetime, line 3 → active_energy_out) rather than parsing OBIS codes directly.
  That's fragile if a meter ever omits a line or a firmware update reorders them —
  parsing by OBIS code instead of position would be more robust, at the cost of a
  bit more code.
- Payload sizes for a full 29-line telegram are comfortably under the 234-byte LoRa
  payload ceiling per line (each line is sent as one LoRa packet in the current
  transmitter), so no change needed there.

## Sources

- Energiföretagen Sverige, "Branschrekommendation för lokalt kundgränssnitt för
  elmätare" (v1.2 / v2.0)
- hanporten.se — community documentation of the Swedish HAN port protocol
  (CC BY-SA 4.0), by Utilitarian
