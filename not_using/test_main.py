#!/usr/bin/env python3
import time
import RPi.GPIO as GPIO
from test_radar_sensor import RadarMotion

LED_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
def main():
    radar = RadarMotion()
    
    if not radar.start():
        print("Radar failed to start")
        return
    
    try:
        while True:
            radar_motion = radar.check_motion()  # Changed variable name
            GPIO.output(LED_PIN, radar_motion)
            
            if radar_motion:
                print("RADAR MOTION: True")
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        radar.stop()
        GPIO.cleanup()

if __name__ == "__main__":
    main()