import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
import json
import pytz
import ssl
import time
import random

# MQTT Configuration for Local Broker (Raspberry Pi)
MQTT_ADDRESS = '192.168.1.122'
MQTT_USER = 'mq'
MQTT_PASSWORD = 'mq'
MQTT_TOPICS = ['DHT11', 'ENERGY', 'ESPLOG', 'UNITS', 'MOTION']

# InfluxDB 2.x Configuration
INFLUXDB_URL = 'http://[::1]:8086'
INFLUXDB_TOKEN = 'mytoken'
INFLUXDB_ORG = 'pi4org'
INFLUXDB_BUCKET = 'pi4data'

# AWS IoT Core Configuration
AWS_ENDPOINT = 'a3m8azs2x620qd-ats.iot.us-east-1.amazonaws.com'
AWS_PORT = 8883
AWS_CLIENT_ID = "RaspberryPi"

# AWS IoT Topics
AWS_DHT_PUBLISH = "DHT11"
AWS_ENERGY_PUBLISH = "ENERGY"
AWS_MOTION_PUBLISH = "MOTION"
AWS_CERT_PATH = "/home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/aws_certs/certificate.pem.crt"
AWS_KEY_PATH = "/home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/aws_certs/private.pem.key"
AWS_ROOT_CA_PATH = "/home/pi/pi4_drive/pi4_python_projects/RASPI4-MAIN/aws_certs/AmazonRootCA1.pem"

# Timezone configuration
INDIAN_TZ = pytz.timezone('Asia/Kolkata')

def get_indian_time():
    """Get current Indian time in 12-hour format with AM/PM"""
    return datetime.now(INDIAN_TZ).strftime('%Y-%m-%d %I:%M:%S %p')

def get_indian_timestamp():
    """Get current Indian time for console logging"""
    return datetime.now(INDIAN_TZ).strftime('%I:%M:%S %p')

# Initialize InfluxDB 2.x client
influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)
query_api = influx_client.query_api()

# AWS MQTT Client Setup
aws_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=AWS_CLIENT_ID)

def on_connect_aws(client, userdata, flags, reasonCode, properties):
    if reasonCode == 0:
        print(f'[{get_indian_timestamp()}] Connected to AWS IoT Broker')  
    else:
        print(f'[{get_indian_timestamp()}] Failed to connect to AWS IoT Broker with code {reasonCode}')

def on_publish_aws(client, userdata, mid, reasonCode, properties):
    print(f'[{get_indian_timestamp()}] AWS Message published with MID: {mid}, Reason: {reasonCode}')

aws_client.on_connect = on_connect_aws
aws_client.on_publish = on_publish_aws

aws_client.tls_set(
    AWS_ROOT_CA_PATH,
    certfile=AWS_CERT_PATH,
    keyfile=AWS_KEY_PATH,
    tls_version=ssl.PROTOCOL_TLSv1_2
)
aws_client.connect(AWS_ENDPOINT, AWS_PORT, 60)

def on_connect(client, userdata, flags, reasonCode, properties):
    if reasonCode == 0:
        print(f'[{get_indian_timestamp()}] Connected to MQTT Broker')
        for topic in MQTT_TOPICS:
            client.subscribe(topic)
    else:
        print(f'[{get_indian_timestamp()}] Failed to connect to MQTT Broker with code {reasonCode}')

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
            publish_to_aws(AWS_ENERGY_PUBLISH, payload)
        elif topic == 'UNITS':
            payload['newUnits'] = float(payload_value['newUnits'])
        elif topic == 'DHT11':
            payload['temperature'] = float(payload_value['temperature'])
            payload['humidity'] = float(payload_value['humidity'])
            publish_to_aws(AWS_DHT_PUBLISH, payload)
        elif topic == 'MOTION':
            payload['motion'] = int(payload_value['motion'])
            payload['distance'] = int(payload_value['distance'])
            publish_to_aws(AWS_MOTION_PUBLISH, payload)
        else:
            print(f"[{get_indian_timestamp()}] Unknown topic: {topic}")
            return
        
        send_to_influxdb(topic, payload)

    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error processing message: {e}')

def send_to_influxdb(topic, payload):
    try:
        print(f'[{get_indian_timestamp()}] Writing to InfluxDB - Topic: {topic}, Payload: {payload}')
        
        # Create timestamp in UTC (InfluxDB 2.x prefers UTC)
        timestamp = datetime.utcnow()
        
        # Create data point for InfluxDB 2.x
        from influxdb_client import Point
        
        point = Point(topic).time(timestamp)
        
        # Add fields based on data type
        for key, value in payload.items():
            if isinstance(value, (int, float)):
                point = point.field(key, value)
            else:
                point = point.field(key, str(value))
        
        # Write to InfluxDB
        write_api.write(bucket=INFLUXDB_BUCKET, record=point)
        print(f'[{get_indian_timestamp()}] Data written to InfluxDB successfully')

    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error writing to InfluxDB: {e}')
'''
def publish_to_aws(aws_topic, payload):
    try:
        aws_message = {
            "timestamp": int(time.time()),
            "data": payload
        }
        aws_client.publish(aws_topic, json.dumps(aws_message))
        print(f'[{get_indian_timestamp()}] Data published to AWS IoT - Topic: {aws_topic}, Payload: {aws_message}')
    
    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error publishing to AWS: {e}')
'''
def publish_to_aws(aws_topic, payload):
    try:
        aws_message = {
            "timestamp": int(time.time()),
            "data": payload
        }
        aws_client.publish(aws_topic, json.dumps(aws_message))
        print(f'[{get_indian_timestamp()}] Data published to AWS IoT - Topic: {aws_topic}, Payload: {aws_message}')
        
        # Also publish random motion data if we're not already publishing motion
        if aws_topic != AWS_MOTION_PUBLISH:
            publish_random_motion_data()
    
    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error publishing to AWS: {e}')

def publish_random_motion_data():
    """Publish random motion data to AWS"""
    try:
        # Generate random motion data
        motion_payload = {
            "motion": 1,
            "distance": random.randint(10, 200)
        }
        
        motion_message = {
            "timestamp": int(time.time()),
            "data": motion_payload
        }
        
        # Publish to AWS MOTION topic
        aws_client.publish(AWS_MOTION_PUBLISH, json.dumps(motion_message))
        
        motion_status = "DETECTED" if motion_payload['motion'] else "NO MOTION"
        print(f'[{get_indian_timestamp()}] 🚶 Random Motion published to AWS - {motion_status}, Distance: {motion_payload["distance"]}cm')
        
    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error publishing random motion: {e}')
def query_influxdb(measurement, hours=24):
    """Query data from InfluxDB 2.x with Indian time display"""
    try:
        query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r._measurement == "{measurement}")
          |> limit(n: 10)
        '''
        
        result = query_api.query(query)
        
        print(f"\n📊 {measurement} Data (Last {hours} hours):")
        for table in result:
            for record in table.records:
                # Convert UTC time to Indian time for display
                utc_time = record.get_time()
                indian_time = utc_time.astimezone(INDIAN_TZ)
                formatted_time = indian_time.strftime('%Y-%m-%d %I:%M:%S %p')
                print(f'   📅 {formatted_time} | 📈 {record.get_field()}: {record.get_value()}')
                
    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error querying InfluxDB: {e}')

def query_all_recent_data(hours=1):
    """Query all recent data with Indian time display"""
    try:
        query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
          |> range(start: -{hours}h)
          |> limit(n: 20)
        '''
        
        result = query_api.query(query)
        
        print(f"\n📊 All Recent Data (Last {hours} hour):")
        for table in result:
            for record in table.records:
                # Convert UTC time to Indian time for display
                utc_time = record.get_time()
                indian_time = utc_time.astimezone(INDIAN_TZ)
                formatted_time = indian_time.strftime('%Y-%m-%d %I:%M:%S %p')
                print(f'   📅 {formatted_time} | 📊 {record.get_measurement()} | 📈 {record.get_field()}: {record.get_value()}')
                
    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error querying InfluxDB: {e}')

if __name__ == '__main__':
    print(f'[{get_indian_timestamp()}] MQTT to InfluxDB 2.x & AWS IoT Bridge')
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message
        mqtt_client.connect(MQTT_ADDRESS, 1883)
        mqtt_client.loop_start()
        
        aws_client.loop_start()

        # Test the query function with Indian time
        print(f"\n[{get_indian_timestamp()}] Testing data query with Indian time...")
        time.sleep(10)  # Wait for some data to be collected
        
        # Query and display data with Indian time
        query_all_recent_data(1)  # Show last 1 hour of data
        
        while True:
            # You can call query functions periodically if needed
            # query_all_recent_data(1)  # Uncomment to query every loop
            time.sleep(5)
        
    except Exception as e:
        print(f'[{get_indian_timestamp()}] Error: {e}')
    finally:
        # Close InfluxDB client properly
        influx_client.close()