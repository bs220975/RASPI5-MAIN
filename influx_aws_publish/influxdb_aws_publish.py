import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
from datetime import datetime
import json
import pytz
import ssl
import time

# MQTT Configuration for Local Broker (Raspberry Pi)
MQTT_ADDRESS = '192.168.1.122'
MQTT_USER = 'mq'
MQTT_PASSWORD = 'mq'
MQTT_TOPICS = ['DHT11', 'ENERGY', 'ESPLOG', 'UNITS', 'MOTION']

# InfluxDB Configuration
INFLUXDB_ADDRESS = 'localhost'
INFLUXDB_PORT = 8086
INFLUXDB_USER = 'admin'
INFLUXDB_PASSWORD = 'admin'
INFLUXDB_DATABASE = 'pi4data'

# AWS IoT Core Configuration
AWS_ENDPOINT = 'a3m8azs2x620qd-ats.iot.us-east-1.amazonaws.com'  # Change region if needed
AWS_PORT = 8883
AWS_CLIENT_ID = "RaspberryPi"

# AWS IoT Topics
AWS_DHT_PUBLISH = "DHT11"      # AWS IoT topic for DHT11 sensor
AWS_ENERGY_PUBLISH = "ENERGY"  # AWS IoT topic for ENERGY meter
AWS_MOTION_PUBLISH = "MOTION"   # AWS IoT topic for radar motion

AWS_CERT_PATH = "/home/pi4/pi4_drive/pi4_python_projects/pi4_main_code/aws_certs/certificate.pem.crt"
AWS_KEY_PATH = "/home/pi4/pi4_drive/pi4_python_projects/pi4_main_code/aws_certs/private.pem.key"
AWS_ROOT_CA_PATH = "/home/pi4/pi4_drive/pi4_python_projects/pi4_main_code/aws_certs/AmazonRootCA1.pem"

# Initialize InfluxDB client
influx_client = InfluxDBClient(INFLUXDB_ADDRESS, INFLUXDB_PORT, INFLUXDB_USER, INFLUXDB_PASSWORD, INFLUXDB_DATABASE)

# AWS MQTT Client Setup
aws_client = mqtt.Client(client_id=AWS_CLIENT_ID)
aws_client.tls_set(
    AWS_ROOT_CA_PATH,
    certfile=AWS_CERT_PATH,
    keyfile=AWS_KEY_PATH,
    tls_version=ssl.PROTOCOL_TLSv1_2
)
aws_client.connect(AWS_ENDPOINT, AWS_PORT, 60)

def on_connect(client, userdata, flags, reasonCode, properties=None):
    if reasonCode == 0:
        print('Connected to MQTT Broker')
        for topic in MQTT_TOPICS:
            client.subscribe(topic)
    else:
        print(f'Failed to connect to MQTT Broker with code {rc}')

def on_message(client, userdata, msg):
    try:
        payload_value = json.loads(msg.payload.decode('utf-8'))
        topic = msg.topic
        payload = {}

        if topic == 'ESPLOG':
            payload['message'] = payload_value
        elif topic == 'ENERGY':
            payload['voltage'] = float(payload_value['voltage'])
            payload['current'] = float(payload_value['current'])
            payload['power'] = float(payload_value['power'])
            payload['kWh'] = float(payload_value['kWh'])
            publish_to_aws(AWS_ENERGY_PUBLISH, payload)  # Publish to AWS ENERGY topic
        elif topic == 'UNITS':
            payload['newUnits'] = float(payload_value['newUnits'])
        elif topic == 'DHT11':
            payload['temperature'] = float(payload_value['temperature'])
            payload['humidity'] = float(payload_value['humidity'])
            publish_to_aws(AWS_DHT_PUBLISH, payload)  # Publish to AWS DHT11 
        elif topic == 'MOTION':
            payload['motion'] = int(payload_value['motion'])
            payload['distance'] = int(payload_value['distance'])
            publish_to_aws(AWS_MOTION_PUBLISH, payload)
        else:
            print(f"Unknown topic: {topic}")
            return
        
        send_to_influxdb(topic, payload)

    except Exception as e:
        print(f'Error processing message: {e}')

def send_to_influxdb(topic, payload):
    try:
        print(f'Writing to InfluxDB - Topic: {topic}, Payload: {payload}')
        utc_now = datetime.utcnow()
        india_tz = pytz.timezone('Asia/Kolkata')
        ist_now = utc_now.replace(tzinfo=pytz.utc).astimezone(india_tz)
        timestamp = ist_now.strftime('%Y-%m-%dT%H:%M:%SZ')

        json_body = [{"measurement": topic, "time": timestamp, "fields": payload}]
        influx_client.write_points(json_body)
        print('Data written to InfluxDB successfully')

    except Exception as e:
        print(f'Error writing to InfluxDB: {e}')

def publish_to_aws(aws_topic, payload):
    try:
        aws_message = {
            "timestamp": int(time.time()),
            "data": payload
        }
        aws_client.publish(aws_topic, json.dumps(aws_message))
        print(f'Data published to AWS IoT - Topic: {aws_topic}, Payload: {aws_message}')
    
    except Exception as e:
        print(f'Error publishing to AWS: {e}')

if __name__ == '__main__':
    print('MQTT to InfluxDB & AWS IoT Bridge')
    try:
        mqtt_client = mqtt.Client()
        mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message
        mqtt_client.connect(MQTT_ADDRESS, 1883)
        mqtt_client.loop_start()
        
        aws_client.loop_start()  # Start AWS MQTT loop

        while True:
            time.sleep(5)  # Keep script running
        
    except Exception as e:
        print(f'Error: {e}')
