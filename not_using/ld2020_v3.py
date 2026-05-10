#!/usr/bin/env python3
import serial
import RPi.GPIO as GPIO
import time

LED_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
GPIO.output(LED_PIN, False)

print("SENSITIVE MOTION DETECTION - LED on with any distance change")
print("Even small distance changes trigger LED")

radar = serial.Serial('/dev/serial0', 115200, timeout=1)
time.sleep(2)

buffer = ""
last_distance = 0
led_state = False
last_motion_time = 0
motion_timeout = 2.0
change_count = 0

try:
    while True:
        current_time = time.time()
        
        # Auto turn off after timeout
        if led_state and current_time - last_motion_time > motion_timeout:
            GPIO.output(LED_PIN, False)
            led_state = False
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
                        
                        # Any change in distance triggers LED
                        if current_distance != last_distance:
                            change_count += 1
                            last_motion_time = current_time
                            
                            if not led_state:
                                GPIO.output(LED_PIN, True)
                                led_state = True
                                print(f"?? MOTION DETECTED - LED ON (Change #{change_count})")
                            
                            last_distance = current_distance
                            
                    except Exception as e:
                        pass
        
        time.sleep(0.1)

except KeyboardInterrupt:
    print(f"\nTotal distance changes: {change_count}")

finally:
    GPIO.output(LED_PIN, False)
    radar.close()
    GPIO.cleanup()