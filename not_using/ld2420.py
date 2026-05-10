#!/usr/bin/env python3
import serial
import RPi.GPIO as GPIO
import time

LED_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
GPIO.output(LED_PIN, False)

print("SMART MOTION DETECTION - Ignoring fan movements")
print("Using threshold and pattern analysis")

radar = serial.Serial('/dev/serial0', 115200, timeout=1)
time.sleep(2)

buffer = ""
last_distance = 0
led_state = False
last_motion_time = 0
motion_timeout = 2.0
change_count = 0

# Anti-fan filtering parameters
MIN_DISTANCE_CHANGE = 15    # Ignore changes smaller than 15cm
CONSECUTIVE_REQUIRED = 2    # Require 2 consecutive detections
MIN_RANGE = 50              # Minimum valid distance
MAX_RANGE = 400             # Maximum valid distance

consecutive_detections = 0

try:
    while True:
        current_time = time.time()
        
        # Auto turn off after timeout
        if led_state and current_time - last_motion_time > motion_timeout:
            GPIO.output(LED_PIN, False)
            led_state = False
            consecutive_detections = 0
            print("? TIMEOUT - LED OFF")
        
        if radar.in_waiting > 0:
            data = radar.read(radar.in_waiting).decode('ascii', errors='ignore')
            buffer += data
            
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip().replace('\r', '')
                
                if line.startswith("Range"):
                    try:
                        current_distance = int(line.split()[1])
                        
                        # Anti-fan filtering
                        valid_distance = MIN_RANGE <= current_distance <= MAX_RANGE
                        significant_change = abs(current_distance - last_distance) >= MIN_DISTANCE_CHANGE
                        
                        if valid_distance and significant_change:
                            consecutive_detections += 1
                            
                            if consecutive_detections >= CONSECUTIVE_REQUIRED:
                                change_count += 1
                                last_motion_time = current_time
                                
                                if not led_state:
                                    GPIO.output(LED_PIN, True)
                                    led_state = True
                                    print(f"?? HUMAN MOTION #{change_count}: {last_distance}?{current_distance} - LED ON")
                                else:
                                    print(f"?? Motion #{change_count}: {last_distance}?{current_distance}")
                                
                                last_distance = current_distance
                        else:
                            consecutive_detections = 0  # Reset counter
                            
                    except Exception as e:
                        consecutive_detections = 0
        
        time.sleep(0.1)

except KeyboardInterrupt:
    print(f"\nTotal real motion detections: {change_count}")

finally:
    GPIO.output(LED_PIN, False)
    radar.close()
    GPIO.cleanup()