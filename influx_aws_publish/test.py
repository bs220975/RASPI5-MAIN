# test_pi4org.py
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUXDB_URL = 'http://localhost:8086'
INFLUXDB_TOKEN = 'mytoken'
INFLUXDB_ORG = 'pi4org'      # Organization name
INFLUXDB_BUCKET = 'pi4data'  # Bucket name

try:
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    
    # Check health
    health = client.health()
    print(f"? InfluxDB Health: {health.status}")
    
    # Test write
    from influxdb_client import Point
    write_api = client.write_api(write_options=SYNCHRONOUS)
    
    test_point = Point("test").field("status", 1)
    write_api.write(bucket=INFLUXDB_BUCKET, record=test_point)
    print("? Successfully wrote to pi4data bucket in pi4org!")
    
    client.close()
    
except Exception as e:
    print(f"? Error: {e}")