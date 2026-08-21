#!/usr/bin/python
# -*- coding: UTF-8 -*-

#
#    Test-only transmitter: builds a synthetic HAN telegram (valid
#    CRC16/IBM checksum, one OBIS line per value lora_receiver_chsum_oled_v2.py
#    understands) and sends it over LoRa (/dev/ttyS0), one line per packet,
#    the same way Lora_transmit_han.py sends real meter data. Use this to
#    exercise the receiver's parse/CRC/MQTT pipeline without a live HAN
#    meter or a reachable transmit-side Pi.
#
#    IMPORTANT — read before running:
#    1. This opens the same LoRa HAT (/dev/ttyS0, GPIO M0/M1) that
#       lora_receiver_chsum_oled_v2.py already holds open when it's running.
#       Stop that script's screen session first (screen -r lora_hat, Ctrl-C),
#       run this, then restart the receiver.
#    2. A single LoRa module is half-duplex and does not hear its own
#       transmission — running this and the receiver on the SAME Pi/HAT will
#       NOT make that receiver see these packets. To actually test end-to-end
#       reception, run this on one Pi while a receiver (this script's
#       counterpart) listens on a different, physically separate LoRa HAT.
#

import argparse
import random
import time

import libscrc
import sx126x_mod as sx126x


def build_telegram(seq: int) -> bytes:
    now = time.strftime('%y%m%d%H%M%S') + 'W'

    active_power = round(random.uniform(0.8, 2.5), 3)
    l1p = round(active_power * random.uniform(0.30, 0.36), 3)
    l2p = round(active_power * random.uniform(0.30, 0.36), 3)
    l3p = round(max(active_power - l1p - l2p, 0.0), 3)

    lines = [
        f'0-0:1.0.0({now})',
        f'1-0:1.8.0({6678.394 + seq * 0.05:012.3f}*kWh)',
        f'1-0:2.8.0({0.0:012.3f}*kWh)',
        f'1-0:3.8.0({21.988:012.3f}*kvarh)',
        f'1-0:4.8.0({1020.971:012.3f}*kvarh)',
        f'1-0:1.7.0({active_power:08.3f}*kW)',
        f'1-0:2.7.0({0.0:08.3f}*kW)',
        f'1-0:21.7.0({l1p:08.3f}*kW)',
        f'1-0:41.7.0({l2p:08.3f}*kW)',
        f'1-0:61.7.0({l3p:08.3f}*kW)',
        f'1-0:32.7.0({round(random.uniform(228, 242), 1):05.1f}*V)',
        f'1-0:52.7.0({round(random.uniform(228, 242), 1):05.1f}*V)',
        f'1-0:72.7.0({round(random.uniform(228, 242), 1):05.1f}*V)',
        f'1-0:31.7.0({round(l1p * 1000 / 230, 1):05.1f}*A)',
        f'1-0:51.7.0({round(l2p * 1000 / 230, 1):05.1f}*A)',
        f'1-0:71.7.0({round(l3p * 1000 / 230, 1):05.1f}*A)',
        f'1-0:3.7.0({round(random.uniform(0, 0.2), 3):08.3f}*kVAr)',
        f'1-0:4.7.0({0.0:08.3f}*kVAr)',
    ]

    body = '\r\n'.join(lines)
    telegram = f'/TST5testmeter{seq:04d}\r\n\r\n{body}\r\n!'
    telegram_bytes = telegram.encode('ascii')

    crc = libscrc.ibm(telegram_bytes)
    return telegram_bytes + f'{crc:04X}'.encode('ascii') + b'\r\n'


def send_telegram(node: sx126x.sx126x, telegram: bytes, dest_addr: int, freq: int):
    offset_frequence = freq - (850 if freq > 850 else 410)
    for line in telegram.splitlines(keepends=True):
        header = (
            bytes([dest_addr >> 8, dest_addr & 0xff, offset_frequence]) +
            bytes([node.addr >> 8, node.addr & 0xff, node.offset_freq])
        )
        node.send(header + line)
        print('sent:', line)
        time.sleep(0.05)


def main():
    p = argparse.ArgumentParser(
        description='Send fake HAN telegrams over the LoRa HAT to test a receiver.')
    p.add_argument('--freq', type=int, default=868)
    p.add_argument('--addr', type=int, default=65535,
                    help="this node's own LoRa address (65535 matches the real "
                         "transmitter, and broadcasts to nodes addressed 0-65534)")
    p.add_argument('--dest-addr', type=int, default=0,
                    help='destination address (0 matches the real receiver default)')
    p.add_argument('--power', type=int, default=22)
    p.add_argument('--air-speed', type=int, default=19200)
    p.add_argument('--count', type=int, default=0,
                    help='number of telegrams to send, then exit. '
                         '0 (default) means send continuously until Ctrl-C.')
    p.add_argument('--interval', type=float, default=20.0,
                    help='seconds between telegrams (default: 20)')
    args = p.parse_args()

    node = sx126x.sx126x(
        serial_num='/dev/ttyS0',
        freq=args.freq,
        addr=args.addr,
        power=args.power,
        rssi=True,
        air_speed=args.air_speed,
        relay=False,
    )

    seq = 0
    try:
        while args.count == 0 or seq < args.count:
            telegram = build_telegram(seq)
            label = f'{seq + 1}/{args.count}' if args.count else f'{seq + 1}'
            print(f'--- sending test telegram {label} ({len(telegram)} bytes) ---')
            send_telegram(node, telegram, dest_addr=args.dest_addr, freq=args.freq)
            seq += 1
            if args.count == 0 or seq < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f'\nStopped after {seq} telegram(s).')


if __name__ == '__main__':
    main()
