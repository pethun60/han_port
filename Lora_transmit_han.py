#!/usr/bin/python
# -*- coding: UTF-8 -*-

#
#    Transmit-only version: reads DSMR telegram lines from the HAN port
#    (/dev/ttyUSB0) and sends them over LoRa (/dev/ttyS0), one line per
#    packet, starting automatically as soon as the script runs.
#

import sx126x
import threading
import time
import serial
import traceback
import queue

usb_queue = queue.Queue()

usb = serial.Serial('/dev/ttyUSB0', 115200, timeout=0.1)
usb.reset_input_buffer()

#
#    Need to disable the serial login shell and have to enable serial interface
#    command `sudo raspi-config`
#
#    When the LoRaHAT is attached to RPi, the M0 and M1 jumpers of HAT should be removed.
#

#   serial_num
#       PiZero, Pi3B+, and Pi4B use "/dev/ttyS0"
#
#    Frequency is [850 to 930], or [410 to 493] MHz
#
#    address is 0 to 65535
#        under the same frequence,if set 65535,the node can receive
#        messages from another node of address is 0 to 65534 and similarly,
#        the address 0 to 65534 of node can receive messages while
#        the another note of address is 65535 sends.
#        otherwise two node must be same the address and frequence
#
#    The tramsmit power is {10, 13, 17, and 22} dBm
#
#    RSSI (receive signal strength indicator) is {True or False}
#        It will print the RSSI value when it receives each message
#

node = sx126x.sx126x(serial_num="/dev/ttyS0", freq=868, addr=65535, power=22, rssi=True, air_speed=19200, relay=False)


def usb_reader_thread():
    print('usb_reader_thread started')  # confirm the thread is even running
    while True:
        payload = usb.read(usb.in_waiting or 1)
        if len(payload) > 0:
            usb_queue.put(payload)


def send_continuous():
    dest_addr = 0
    freq = 868
    offset_frequence = freq - (850 if freq > 850 else 410)

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

            data = (
                bytes([dest_addr >> 8]) + bytes([dest_addr & 0xff]) + bytes([offset_frequence]) +
                bytes([node.addr >> 8]) + bytes([node.addr & 0xff]) + bytes([node.offset_freq]) +
                payload
            )
            print('send payload ', payload)
            node.send(data)
            time.sleep(0.05)


if __name__ == '__main__':
    threading.Thread(target=usb_reader_thread, daemon=True).start()

    try:
        time.sleep(1)
        print('Starting continuous HAN port transmission...')
        send_continuous()
    except KeyboardInterrupt:
        print('\nStopped.')
    except Exception:
        traceback.print_exc()
