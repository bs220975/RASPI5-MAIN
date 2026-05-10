#!/usr/bin/env python3
import serial
import time

class RadarMotion:
    def __init__(self):
        self.radar = None
        self.last_distance = 0
        self.radar_motion = False  # Changed from motion_active
        
    def start(self):
        try:
            self.radar = serial.Serial('/dev/serial0', 115200, timeout=1)
            time.sleep(2)
            return True
        except:
            return False
    
    def check_motion(self):
        if not self.radar:
            return False
            
        if self.radar.in_waiting > 0:
            data = self.radar.read(self.radar.in_waiting).decode('ascii', errors='ignore')
            
            for line in data.split('\n'):
                line = line.strip().replace('\r', '')
                if line.startswith("Range"):
                    try:
                        current_distance = int(line.split()[1])
                        if current_distance != self.last_distance:
                            self.last_distance = current_distance
                            self.radar_motion = True  # Updated variable name
                            return True
                    except:
                        pass
        
        return self.radar_motion  # Updated variable name
    
    def stop(self):
        if self.radar:
            self.radar.close()