#!/usr/bin/env python3
import serial
import RPi.GPIO as GPIO
import time

LED_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
GPIO.output(LED_PIN, False)

print("MOTION CHANGE DETECTION - LED on only when distance changes")
print("Ignores static detections at same distance")

radar = serial.Serial('/dev/serial0', 115200, timeout=1)
time.sleep(2)

buffer = ""
last_distance = 0
led_state = False
last_motion_time = 0
motion_timeout = 3.0  # LED turns off after 3 seconds of no distance changes

try:
    while True:
        current_time = time.time()
        
        # Turn LED off if no distance changes for timeout period
        if led_state and current_time - last_motion_time > motion_timeout:
            GPIO.output(LED_PIN, False)
            led_state = False
            print("*** NO DISTANCE CHANGES - LED OFF ***")
        
        if radar.in_waiting > 0:
            data = radar.read(radar.in_waiting).decode('ascii', errors='ignore')
            buffer += data
            
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip().replace('\r', '')
                
                if line.startswith("Range"):
                    try:
                        current_distance = int(line.split()[1])
                        
                        # Only trigger LED if distance changes
                        if current_distance != last_distance:
                            last_motion_time = current_time
                            
                            if not led_state:
                                GPIO.output(LED_PIN, True)
                                led_state = True
                                print(f"?? DISTANCE CHANGED {last_distance}?{current_distance} - LED ON")
                            else:
                                print(f"?? Distance changed: {last_distance} ? {current_distance}")
                            
                            last_distance = current_distance
                        # else:
                        #     print(f"Same distance: {current_distance} (no change)")
                            
                    except Exception as e:
                        print(f"Error parsing distance: {e}")
        
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nShutting down...")

finally:
    GPIO.output(LED_PIN, False)
    radar.close()
    GPIO.cleanup()
    print("Cleanup completed")