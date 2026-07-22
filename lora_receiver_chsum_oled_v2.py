import argparse
import libscrc
import paho.mqtt.client as mqtt
import logging
import time
import io
import board
import busio
import adafruit_ssd1306
import sx126x_mod as sx126x
import json
import threading

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# define file handler and set formatter
file_handler = logging.FileHandler('error.log')
file_handler.setLevel(logging.ERROR)
formatter    = logging.Formatter('%(asctime)s : %(levelname)s : %(name)s : %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


def extract_frame(buf: bytes):
    start = buf.find(b'/')
    end = buf.find(b'!', start)
    if start < 0 or end < 0 or end + 5 > len(buf):
        return None, None, buf
    payload = buf[start:end+1]
    crc_field = buf[end+1:end+5]
    try:
        expected = int(crc_field.decode('ascii'), 16)
    except ValueError:
        return None, None, buf[end+5:]
    return payload, expected, buf[end+5:]


def process_payload(payload_bytes, read_lines):
    result = {}
    try:
        payload_stream = io.BytesIO(payload_bytes)
        for i in range(read_lines):
            elec_data = payload_stream.readline().strip()
            pos_start = elec_data.find(b'(') + 1
            pos_end = elec_data.find(b'*')
            if pos_end == -1: pos_end = elec_data.find(b'W')
            pos_type = elec_data.find(b')')
            if pos_start <= 0 or pos_end == -1: continue
            value = elec_data[pos_start:pos_end].decode('utf-8')
            if i == 2: result['datevalue'] = elec_data[10:22].decode('utf-8')
            elif i == 3: result['active_energy_out'] = value
            elif i == 4: result['active_energy_in'] = value
            elif i == 5: result['reactive_energy_out'] = value
            elif i == 7: result['active_energy_out_curr'] = value
            elif i == 23: result['L1voltage'] = value
            elif i == 24: result['L2voltage'] = value
            elif i == 25: result['L3voltage'] = value
            elif i == 26: result['L1ampere'] = value
            elif i == 27: result['L2ampere'] = value
            elif i == 28: result['L3ampere'] = value
            else: result[f'value_{i}'] = value
        return result
    except Exception as e:
        print('Error while processing payload:', e)
        return None




# One-time discovery state — only need to (re)send the discovery
# payloads once per script run, since they're retained on the broker.
_discovery_sent = False

MQTT_HOST = 'thunholm.homelinux.com'
MQTT_USER = 'remoteuser'
MQTT_PASS = 'Leokatt60'

# Change this per site: it controls both the device grouping in HA
# and the topic namespace, so Kronudden and Husby never collide.
SITE_ID = 'new_kronudden'          # was implicitly "tobo" via /el/tobo/
SITE_NAME = 'New_Kronudden'

DEVICE_INFO = {
    "identifiers": [f"{SITE_ID}_energy_meter"],
    "name": f"{SITE_NAME} Energy Meter",
    "manufacturer": "DIY",
    "model": "DSMR via LoRa relay",
    "suggested_area": SITE_NAME,
}

# Maps our internal data keys -> (object_id, HA display name, unit, device_class, state_class)
SENSOR_DEFS = {
    'datevalue':               ('date_time',        'Date/Time',            None,   None,      None),
    'active_energy_out':       ('aktiv_energi',      'Aktiv energi mätare',  'kWh',  'energy',  'total_increasing'),
    'active_energy_out_curr':  ('aktiv_effekt',      'Active power',         'kW',   'power',   'measurement'),
    'L1ampere':                ('fasstrom_l1',       'Strömförbrukning L1',  'A',    None,      'measurement'),
    'L2ampere':                ('fasstrom_l2',       'Strömförbrukning L2',  'A',    None,      'measurement'),
    'L3ampere':                ('fasstrom_l3',       'Strömförbrukning L3',  'A',    None,      'measurement'),
}


def get_mqtt_client():
    connected_event = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            connected_event.set()
        else:
            logger.error(f'MQTT connect failed: {reason_code}')

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{SITE_ID}_relay",
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(MQTT_USER, password=MQTT_PASS)
    client.on_connect = on_connect
    client.connect(MQTT_HOST, 1883, keepalive=60)
    client.loop_start()

    if not connected_event.wait(timeout=5):
        client.loop_stop()
        raise TimeoutError("MQTT connection did not complete within 5s")

    return client

def publish_discovery(client):
    """Send one retained discovery config per sensor so HA creates
    the device automatically. Only needs to run once per session."""
    for key, (object_id, name, unit, device_class, state_class) in SENSOR_DEFS.items():
        topic = f"homeassistant/sensor/{SITE_ID}/{object_id}/config"
        payload = {
            "name": name,
            "state_topic": f"{SITE_ID}/el/{object_id}",
            "unique_id": f"{SITE_ID}_{object_id}",
            "device": DEVICE_INFO,
        }
        if unit:
            payload["unit_of_measurement"] = unit
        if device_class:
            payload["device_class"] = device_class
        if state_class:
            payload["state_class"] = state_class

        client.publish(topic, json.dumps(payload), qos=1, retain=True)


def mqtt_save(data):
    global _discovery_sent
    client = None
    try:
        client = get_mqtt_client()

        if not _discovery_sent:
            publish_discovery(client)
            _discovery_sent = True

        print('--- MQTT publish ---')
        infos = []
        for key, (object_id, name, *_rest) in SENSOR_DEFS.items():
            value = data.get(key)
            if value is None:
                continue
            topic = f"{SITE_ID}/el/{object_id}"
            info = client.publish(topic, value, qos=1)
            infos.append(info)
            print(f'  {name}: {value}')

        # Block until every QoS 1 publish is actually acknowledged
        for info in infos:
            info.wait_for_publish(timeout=5)

        logger.info('MQTT Published successfully (v5, discovery).')
    except Exception as e:
        logger.error(f'MQTT error: {e}')
    finally:
        if client:
            client.loop_stop()
            client.disconnect()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('-o', '--output', default='lora.log')
    p.add_argument('--freq', type=int, default=868)
    p.add_argument('--addr', type=int, default=0)
    p.add_argument('--power', type=int, default=22)
    p.add_argument('--air-speed', type=int, default=19200)
    args = p.parse_args()

    node = sx126x.sx126x(
        serial_num="/dev/ttyS0",
        freq=args.freq,
        addr=args.addr,
        power=args.power,
        rssi=True,
        air_speed=args.air_speed,
        relay=False,
    )

    i2c_bus = busio.I2C(board.SCL, board.SDA, frequency=50000)
    oled = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c_bus)
    oled.contrast(5)
    oled.fill(0); oled.show()

    screen_on, last_update = True, time.time()
    messages, error_messages = 0, 0

    with open(args.output, 'ab') as fout:
        buf = b''
        while True:
            # AUTO-SLEEP AFTER 5 SECONDS
            if screen_on and (time.time() - last_update > 5):
                oled.fill(0); oled.show(); oled.poweroff()
                screen_on = False
                print('Screen sleep (5s timeout).')

            chunks = node.receive()
            if not chunks:
                continue

            for chunk in chunks:
                buf += chunk

            # extract as many complete telegrams as are now available
            while True:
                payload, expected_crc, buf = extract_frame(buf)
                if payload is None:
                    break

                # WAKE SCREEN
                if not screen_on:
                    oled.poweron(); screen_on = True

                last_update = time.time()
                messages += 1

                # Create Timestamp
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S').encode()

                if libscrc.ibm(payload) == expected_crc:
                    success = messages - error_messages
                    rate = (error_messages / messages * 100) if messages > 0 else 0
                    stats = f' [OK:{success} ERR:{error_messages} {rate:.1f}%]'.encode()

                    fout.write(timestamp + stats + b' ' + payload + b'!' + f'{expected_crc:04X}'.encode() + b'\r\n')
                    fout.flush()
                    result_dict = process_payload(payload, 29)
                    if result_dict: mqtt_save(result_dict)
                else:
                    error_messages += 1
                    success = messages - error_messages
                    rate = (error_messages / messages * 100) if messages > 0 else 0
                    stats = f' [OK:{success} ERR:{error_messages} {rate:.1f}%]'.encode()

                    fout.write(timestamp + stats + b' !!FAILED!! ' + payload + b'!' + f'{expected_crc:04X}'.encode() + b'\r\n')
                    fout.flush()

                # PIXEL SHIFT (4x4 Grid) - drawn after CRC check so the
                # error count/rate shown reflects this message too
                off_x, off_y = (messages % 4), (messages % 4)

                oled.fill(0)
                oled.text('MQTT Published', 2 + off_x, 2 + off_y, 1)
                oled.text(f'Msgs: {messages}', 2 + off_x, 12 + off_y, 1)
                oled.text(f'Err:{error_messages} {rate:.1f}%', 2 + off_x, 22 + off_y, 1)
                oled.show()

                print('MQTT Published')
                print(f'Msgs: {messages}')
                print(f'Err:{error_messages} {rate:.1f}%')


if __name__ == '__main__':
    main()
