from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime

def log_to_influxdb(ld2420_motion_status, prev_state):
    """Log motion sensor data to InfluxDB 2.x"""
    print(f"?? DEBUG: log_to_influxdb called with motion={ld2420_motion_status}, prev={prev_state}")
    
    try:
        # Only log if state changed
        if ld2420_motion_status != prev_state:
            print("?? DEBUG: State changed, attempting to log...")
            
            # Initialize InfluxDB 2.x client
            client = InfluxDBClient(
                url="http://localhost:8086",
                token="mytoken",
                org="pi4org"
            )
            
            write_api = client.write_api(write_options=SYNCHRONOUS)
            
            # Create data point
            point = Point("motion_sensor") \
                .tag("sensor", "LD2420") \
                .field("motion_status", int(ld2420_motion_status)) \
                .time(datetime.utcnow())
            
            # Write to InfluxDB
            write_api.write(bucket="pi4data", record=point)
            print(f"? Logged to InfluxDB | Motion={ld2420_motion_status}", flush=True)
            
            # Close clients
            write_api.close()
            client.close()
            
            return ld2420_motion_status
        else:
            print("?? DEBUG: No state change, skipping log")
            
    except Exception as e:
        print(f"?? InfluxDB write failed: {e}")
        import traceback
        traceback.print_exc()  # This will show the full error stack
        return prev_state
    
    return prev_state
