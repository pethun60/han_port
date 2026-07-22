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


def usb_reader_thread():
    print('usb_reader_thread started')  # confirm the thread is even running
    while True:
        payload = usb.read(usb.in_waiting or 1)
        if len(payload) > 0:
            usb_queue.put(payload)


def send_continuous():
    buf = b''

    while True:
        try:
            raw = usb_queue.get(timeout=1)   # from the QUEUE, not usb.read()
        except queue.Empty:
            continue

        buf += raw

        while b'\r\n' in buf:
            line, buf = buf.split(b'\r\n', 1)
            payload = line + b'\r\n'

            print('send payload ', payload)
            lora.write(payload)
            time.sleep(len(payload) / LORA_BYTES_PER_SEC)


if __name__ == '__main__':
    threading.Thread(target=usb_reader_thread, daemon=True).start()

    try:
        time.sleep(1)
        print('Starting continuous HAN port transmission (husbyHome)...')
        send_continuous()
    except KeyboardInterrupt:
        print('\nStopped.')
    except Exception:
        traceback.print_exc()
