#!/usr/bin/python
# -*- coding: UTF-8 -*-

#
#    Transmit-only version for the husbyHome site: reads DSMR telegram lines
#    from the HAN port (/dev/ttyUSB0) and forwards them, line by line, to a
#    Waveshare USB-to-LoRa dongle (/dev/ttyACM0) acting as a transparent
#    serial-over-radio bridge.
#
#    Unlike Lora_transmit_han.py (used on rpizero3), this site's LoRa link is
#    a USB dongle rather than the GPIO SX126x HAT, so there's no addressed
#    packet protocol or M0/M1 pin control here - whatever bytes go out on the
#    dongle's UART are simply radioed straight through to the receiving
#    dongle's UART. Reads are still done on a background thread into a
#    queue.Queue, decoupling USB reads from LoRa write timing, same as the
#    rpizero3 script.
#
#    Writes to the dongle are paced (see LORA_BYTES_PER_SEC below) rather
#    than fired as fast as they're read off the HAN port. The dongle's UART
#    runs at 115200 baud, but its actual over-the-air throughput is far
#    lower - writing a full ~900-byte telegram at full UART speed overflows
#    its internal buffer partway through, silently dropping the remainder
#    (confirmed on rpizero2: the same ~15 trailing OBIS lines were missing
#    from every single telegram cycle). Pacing keeps writes within what the
#    module can actually radio out before its buffer fills.
#
#    BATCHED VARIANT (2026-08-21): the original script (kept unmodified as
#    Lora_transmit_han_husbyHome.py) writes one radio transmission per HAN
#    line - ~29 separate over-the-air hops per telegram, reassembled by the
#    receiver purely by byte-stream concatenation, with no per-hop ACK/FEC.
#    That fans out even a small per-hop error rate into a much larger
#    telegram-level failure rate (observed: ~38% CRC failures in
#    lora.log/rpizero2, with visible garbled bytes inside otherwise-valid
#    telegrams). This variant batches several lines into each write (see
#    MAX_CHUNK_BYTES) to cut the number of independent hops per telegram by
#    roughly the same factor - same total paced throughput (still capped at
#    LORA_BYTES_PER_SEC on average, same ~6s per telegram), just fewer,
#    larger writes. MAX_CHUNK_BYTES is deliberately kept well below the
#    ~900-byte size that caused the original overflow bug, since that
#    failure mode (and the USB-LoRa stick lockups it was linked to - see
#    project notes) is the reason per-line pacing exists at all; this is a
#    middle ground, not a return to one big unpaced write.
#

import threading
import time
import serial
import traceback
import queue

usb_queue = queue.Queue()

usb = serial.Serial('/dev/ttyUSB0', 115200, timeout=0.1)
usb.reset_input_buffer()

lora = serial.Serial('/dev/ttyACM0', 115200, timeout=0.1)

# Conservative pacing target: a full ~900-byte telegram takes ~6s at this
# rate, comfortably under the meter's ~10s telegram interval while staying
# well below what overflowed the dongle's buffer at full UART speed.
LORA_BYTES_PER_SEC = 150

# Batch up to this many bytes (a handful of OBIS lines) into one write
# instead of writing every single line separately. Cuts the number of
# independent over-the-air hops per ~900-byte telegram from ~29 down to
# ~8-9, while each individual write stays far below the ~900-byte size that
# caused the original buffer-overflow bug - still paced at the same
# LORA_BYTES_PER_SEC rate, just in fewer, larger pieces.
MAX_CHUNK_BYTES = 100


def usb_reader_thread():
    print('usb_reader_thread started')  # confirm the thread is even running
    while True:
        payload = usb.read(usb.in_waiting or 1)
        if len(payload) > 0:
            usb_queue.put(payload)


def send_continuous():
    buf = b''
    chunk = b''

    while True:
        try:
            raw = usb_queue.get(timeout=1)   # from the QUEUE, not usb.read()
        except queue.Empty:
            continue

        buf += raw

        while b'\r\n' in buf:
            line, buf = buf.split(b'\r\n', 1)
            chunk += line + b'\r\n'

            if len(chunk) >= MAX_CHUNK_BYTES:
                print('send chunk ', chunk)
                lora.write(chunk)
                time.sleep(len(chunk) / LORA_BYTES_PER_SEC)
                chunk = b''

        # Flush whatever's left once we've drained every complete line
        # currently available, rather than holding it until the next batch
        # of USB reads arrives - in practice this flushes at each
        # telegram's trailing boundary (the final short lines/CRC).
        if chunk:
            print('send chunk (flush)', chunk)
            lora.write(chunk)
            time.sleep(len(chunk) / LORA_BYTES_PER_SEC)
            chunk = b''


if __name__ == '__main__':
    threading.Thread(target=usb_reader_thread, daemon=True).start()

    try:
        time.sleep(1)
        print('Starting continuous HAN port transmission (husbyHome, batched)...')
        send_continuous()
    except KeyboardInterrupt:
        print('\nStopped.')
    except Exception:
        traceback.print_exc()
