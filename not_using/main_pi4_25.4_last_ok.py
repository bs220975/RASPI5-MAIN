#Last Updated
# 2024.11.12 : Update mainloop() function to add "pir_motion_detected = False" at start of loop
# 2025.04.20 : Update and reeenamed all code for pi4_added sennsors_plot
#=========================================================================================================
from misc_functions import (initialize_camera,fetch_data, print_combined_table,save_table_as_pdf,
                        plot_data,send_request_to_esp01_lobby,video_upload_to_drive,change_file_permissions,
                        send_files_to_telegram,log_file,main_loop_time_counter,
                        sensor_thread_loop_time_counter,check_system,check_disk_space)
#from sensor_data_plot import (generate_and_send_sensor_plot)
from bot_messages_handling import *
from OK_esp_status import (esp_status_check)
from send_msg_video_in_queue_on_bot import *
# from OK_esp_status import (signal_strength_to_percentage,get_esp_info,print_esp_table,esp_status_check)

last_updated = "28 June 2025"
script_version = "V25.6.28-pi4"
import asyncio
import prettytable
import matplotlib
matplotlib.use('Agg')  # Set the backend to Agg before importing pyplot
import matplotlib.pyplot as plt
from influxdb import InfluxDBClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from dateutil.parser import parse
import subprocess
import telepot
from telepot.exception import TelegramError
#import RPi.GPIO as GPIO
import datetime
import time
from datetime import datetime
from time import sleep
from subprocess import call
import requests
import os
import glob
import psutil
import logging
from concurrent.futures import wait
import multiprocessing
from multiprocessing import Lock,Process
import traceback
import threading
from threading import Event,Lock
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from PIL import Image, ImageDraw, ImageFont #pip install pillow
import io
import shutil

pir_motion_start_time = 0
pir_total_motion_time = 0
pir_motion_detected = False
print_lock = threading.Lock()
bot_lock = threading.Lock()
message_lock = Lock()
send_lock = Lock()
last_modified = None
sensors_video_rec = True
reed_switch = True
motionSensor = True
motion = True
botvideo = True
drive_upload = False
pauseBot = False
#camera_closed = False
lock1 = True
recording = False
start_rec_time = 0
static_start_rec_time = time.time()
duration = 10
min_video_length = 10
max_video_length = 30  #seconds
DEBOUNCE_TIME = 0.4

#========InfluxDB Configuration=========
INFLUXDB_ADDRESS = 'localhost'
INFLUXDB_PORT = 8086
INFLUXDB_USER = 'admin'
INFLUXDB_PASSWORD = 'admin'
INFLUXDB_DATABASE = 'Pi4'

#========= ESP Device IPs===============

ESP_Lobby_IP = "192.168.1.85:1085"  # ESP-01 lobby relay IP address
ESP_Porch_IP = "192.168.1.89:1089"  # ESP-01 porch relay IP address
ESP_OLED_IP = "192.168.1.102:1020"  # ESP32 OLED attached
ESP32_GSM_IP = "192.168.1.91:9191"  # ESP32_4G_GSM IP address

from gpiozero import DigitalInputDevice
from signal import pause

# BCM pin numbers (not BOARD numbering)
mms_sensor_pin = 27
pir_sensor_pin = 25
reed_switch_pin = 16

try:
    # Initialize sensors
    mms_sensor = DigitalInputDevice(mms_sensor_pin, pull_up=False)
    pir_sensor = DigitalInputDevice(pir_sensor_pin, pull_up=False)
    reed_switch = DigitalInputDevice(reed_switch_pin, pull_up=True)

    prev_door_state = reed_switch.value  # 1 = door closed if using pull-up

except Exception as e:
    print(f"[WARNING] GPIO sensors not connected or error: {e}. Running in mock mode.")
    mms_sensor = None
    pir_sensor = None
    reed_switch = None
    mms_sensor_value = False
    pir_motion_detected = False
    prev_door_state = True

PDF_FILE_PATH = '/home/pi4/esp32/python_raspi/Running_codes/DTH11_temperature_Humidity.pdf'
IMAGE_FILE_PATH = '/home/pi4/esp32/python_raspi/Running_codes/temperature_humidity_plot.png'
filename = time.strftime("%d%b%y_%H%M%S")
file_path = "/home/pi4/raspi_camera_videos/" + filename

bot.message_loop(handle)

#=========================================================
def initialize_camera():
    global camera,encoder
    try:     
        camera = Picamera2()
        video_config = camera.create_video_configuration()
        #video_config = camera.create_video_configuration(main={"size": (1280, 960)})
        camera.configure(video_config)
        encoder = H264Encoder(bitrate = 5000000)
        time.sleep(0.15)  # Add a delay of 1 second (adjust as needed)
        return camera, encoder
    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Error: {e}")
        send_message_to_bot(f"Error: {e}")
        return None, None


#=========================================================       
def send_video_to_bot():
    try:
        global pauseBot, start_time, file_path

        if botvideo:             
            start_time = time.time()
            with send_lock:
                bot.sendVideo(chat_id, video = open(file_path + '.mp4', 'rb'))               
            end_time = time.time()
            print(file_path + '.mp4')
            message_upload_time = f"Video uploading time: {round(end_time - start_time,2)} seconds"
            print(message_upload_time)
            pauseBot = False
    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Error: {e}")
        queue_text_message(bot, chat_id, f"Error: {e}")
    finally:    
        #send_message_to_bot(message_upload_time)
        pauseBot = False
        
#=====================Sending Video============================

def video_process_send():    
    global file_path

    h264_file = file_path + '.h264'
    mp4_file = file_path + '.mp4'

    try:
        # Check if ffmpeg is installed
        if shutil.which("ffmpeg") is None:
            raise FileNotFoundError("ffmpeg is not installed or not found in PATH.")

        # Check if .h264 file exists
        if not os.path.exists(h264_file):
            raise FileNotFoundError(f"Input file not found: {h264_file}")

        # Build and run the ffmpeg command
        command = f"ffmpeg -y -framerate 30 -f h264 -i \"{h264_file}\" -c copy \"{mp4_file}\""
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)

        print(f"\033[92mConversion to {mp4_file} completed successfully.\033[0m")
        time.sleep(0.1)
        # Send to bot and upload to drive
        with bot_lock:
            threading.Thread(target=send_video_to_bot).start()        
            #send_video_to_bot()
            
            #queue_video_message(bot, chat_id, mp4_file)
        print(f"Deleting video: {h264_file}")
        os.remove(h264_file)
        threading.Thread(target=video_upload_to_drive).start()

    except subprocess.CalledProcessError as e:
        error_msg = f"ffmpeg failed:\n{e.stderr.strip()}"
        print(f"\033[91m{error_msg}\033[0m")
        logging.error(error_msg)
        queue_text_message(bot, chat_id, error_msg)

    except Exception as e:
        print(f"\033[91mError: {e}\033[0m")
        logging.error(f"Error: {e}")
        queue_text_message(bot, chat_id, f"Error: {e}")

#=========================================================
def stop_recording():
        global recording
        print(f"\033[31mStopping video recording...\033[0m")  # Red text        
        camera.stop_recording()
        recording = False
        check_disk_space()
        
#====================2025.04.25 -V1================================

# Recording control
stop_recording_event = Event()
recording_thread = None
last_motion_time = 0
start_rec_time = None

# Timing constants
MIN_DURATION = 10  # 10 seconds minimum
MAX_DURATION = 120  # 2 minutes maximum

#===================================================================
camera_lock = threading.Lock()
def start_video_recording(filename, max_duration, stop_event):
    global camera, encoder, file_path, recording
    start_time = time.time()
    message_sent = False

    with camera_lock:  # Acquire lock for camera operations
        try:
            # Initialize camera if needed
            if camera is None or encoder is None:
                camera, encoder = initialize_camera()
                if camera is None or encoder is None:
                    raise RuntimeError("Camera initialization failed")

            # Create filename/path
            file_path = f"/home/pi4/raspi_camera_videos/{filename}"
            
            # Start recording
            camera.start_recording(encoder, file_path + ".h264")
            recording = True  # Set recording flag
            message = "Recording video on motion detection..."
            print(f"\033[34m{message}\033[0m")
            queue_text_message(bot, chat_id, message)
            message_sent = True

            # Main recording loop
            while not stop_event.is_set() and (time.time() - start_time < max_duration):
                if (time.time() - start_time) < MIN_DURATION:
                    stop_event.clear()
                time.sleep(0.5)

            actual_duration = time.time() - start_time
            print(f"Stopping recording after {actual_duration:.1f}s")

        except Exception as e:
            error_msg = f"Recording error: {str(e)}"
            print(f"\033[31m{error_msg}\033[0m")
            logging.error(error_msg)
            queue_text_message(bot, chat_id, error_msg)
            
        finally:
            # Ensure proper cleanup
            try:
                if recording:  # Only stop if we were actually recording
                    camera.stop_recording()
                    recording = False
                    check_disk_space()
            except Exception as e:
                print(f"Stop recording error: {str(e)}")

            # Process video if we recorded past minimum duration
            if time.time() - start_time >= MIN_DURATION:
                video_process_send()
            elif message_sent:
                queue_text_message(bot, chat_id, "Short motion ignored (under 10s)")            
            stop_event.clear() 

#=========================================================================

def mms_pir_sensor():
    global last_motion_time, stop_recording_event, recording_thread
    global motionSensor  # Keep this if used elsewhere
    global start_rec_time

    try:
        # Initialize InfluxDB client
        client = InfluxDBClient(
            host='localhost',
            port=8086,
            username='admin',
            password='admin',
            database='pi4data'
        )

        # Read sensor states
        pir_state = pir_sensor.value
        mms_state = mms_sensor.value
        current_hour = datetime.now().hour

        # Manage previous states
        if 'prev_pir_state' not in globals():
            global prev_pir_state
            prev_pir_state = pir_state
        
        if 'prev_mms_state' not in globals():
            global prev_mms_state
            prev_mms_state = mms_state

        # Log state changes to InfluxDB
        if pir_state != prev_pir_state or mms_state != prev_mms_state:
            timestamp = datetime.utcnow().isoformat() + 'Z'
            json_body = [{
                "measurement": "sensor_data",
                "time": timestamp,
                "fields": {"pir": pir_state, "mms": mms_state}
            }]
            client.write_points(json_body)
            print(f"Logged to InfluxDB | PIR={pir_state}, MMS={mms_state}", flush=True)
            prev_pir_state, prev_mms_state = pir_state, mms_state

        # Motion detection logic
        if pir_state and mms_state:
            last_motion_time = time.time()
            
            # Light control logic
            if motionSensor and (current_hour < 8 or current_hour >= 18):
                print("Nighttime motion detected - activating lights")
                motionSensor = False  # Prevent multiple triggers
                
                def esp01_worker():
                    try:
                        print("Sending request to ESP01...")
                        response = send_request_to_esp01_lobby()
                        print(f"ESP01 response: {response}")
                    except Exception as e:
                        print(f"Error in ESP01 thread: {e}")
                    finally:
                        global motionSensor
                        motionSensor = True  # Reset flag
                        print("ESP01 thread completed")
                
                # Start thread with error handling
                t = threading.Thread(target=esp01_worker, daemon=True)
                t.start()
                print(f"Started ESP01 thread (ID: {t.ident})")

            # Start new recording if not already running
            if not (recording_thread and recording_thread.is_alive()):
                print("Both sensors active - starting recording")
                stop_recording_event.clear()
                filename = time.strftime("%d%b%y_%H%M%S")
                start_rec_time = time.time()
                recording_thread = threading.Thread(
                    target=start_video_recording,
                    args=(filename, MAX_DURATION, stop_recording_event)
                )
                recording_thread.start()

        # Check if we should stop recording
        #if recording_thread and recording_thread.is_alive():
        if recording_thread and recording_thread.is_alive() and start_rec_time is not None:
            time_since_motion = time.time() - last_motion_time
            
            # Stop conditions (10s cooldown after minimum duration)
            if time_since_motion > 10 and (time.time() - start_rec_time) >= MIN_DURATION:
                print("No recent motion - stopping recording")
                stop_recording_event.set()

        client.close()

    except Exception as e:
        print(f"Error in mms_pir_sensor: {e}")
        logging.error(f"Error in mms_pir_sensor: {e}")

#=============================================================================

def door_reed_switch():
    global prev_door_state  # Declare prev_door_state as global
    try:
        # Read the state of the door sensor (1 when closed, 0 when open due to pull_up=True)
        door_state = reed_switch.value
        time.sleep(1)
        #print(door_state)
        
        if door_state != prev_door_state:
            if door_state == 0:  # 0 = open (magnet moved away)
                print("Door is OPEN")
                # t1 = threading.Thread(target=send_request_to_esp32_gsm)
                # t1.start()
                queue_text_message(bot, chat_id, "Door is OPEN now")
                # t1.join()
            else:  # 1 = closed (magnet near)
                print("Door is CLOSED")
                queue_text_message(bot, chat_id, "Door is CLOSED now")
                
            prev_door_state = door_state

    except Exception as e:
        print(f'Error: {e}')

#====================running main loop=================================
def main_loop():           
    try:
        global last_stop_recording_time
        global motion

        last_stop_recording_time = time.time()
        pir_current_state = pir_sensor.value
        pir_motion_detected = False
        main_loop_counter = 0
        pir_total_motion_time = 0
        main_loop_start_time = time.time()
        error_flag = False
        time.sleep(1)

        while True:
            time.sleep(0.1)  # loop delay 100 ms
            # Replace with your actual motion detection logic
            motion = ()
            if motion:
                mms_pir_sensor()
                #print(motion) 
            if reed_switch:
                door_reed_switch()

            # Loop speed info (optional debug line)
            # main_loop_counter, main_loop_start_time, error_flag = main_loop_time_counter(main_loop_start_time, main_loop_counter, error_flag)

            # PIR state check using gpiozero
            pir_new_state = pir_sensor.value
            #print(pir_new_state)

            if pir_new_state != pir_current_state:
                if pir_new_state:
                    #print("PIR Sensor is High")
                    pir_motion_start_time = time.time()
                    pir_motion_detected = True
                else:
                    print("PIR Sensor is Low")
                    if pir_motion_detected:
                        motion_duration = time.time() - pir_motion_start_time
                        pir_total_motion_time += motion_duration
                        print(f"PIR sensor High duration: {motion_duration:.2f} seconds")
                        pir_motion_detected = False

                pir_current_state = pir_new_state

    except Exception as e:
        print(f"Error in main_loop: {e}")
        logging.error(f"Error in main loop function: {e}")
        queue_text_message(bot, chat_id, f"Error in main loop function: {e}")

    finally:
        print("GPIO cleanup done.")  # No actual cleanup needed with gpiozero
        # restart_script()  # Uncomment if needed           


#=================functions run once==========================
        
if __name__ == "__main__":
    global camera,encoder
    try:        
        last_run = datetime.now()
        formattedTime = last_run.strftime('%A %d/%m/%y %I:%M:%S %p')
        print(f"Raspberry Pi 5\n===================\nScript version : V25.4\nDated: {last_updated}\nRun Time : {formattedTime}")
        queue_text_message(bot, chat_id, f"Raspberry Pi 5\n===================\nScript version : {script_version}\nDated: {last_updated}\nRun Time : {formattedTime}")
        camera, encoder = initialize_camera()
        time.sleep(0.25)
        if camera is None or encoder is None:
            print("Camera not properly initialized.")
            queue_text_message(bot, chat_id, "Camera not properly initialized.")
        else:
            print("Camera initialized successfully")
            #send_message_to_bot("Camera initialized successfully")
            queue_text_message(bot, chat_id, "Camera initialized successfully")
        #time.sleep(0.15)
        #change_file_permissions(PDF_FILE_PATH)
        #change_file_permissions(IMAGE_FILE_PATH)        
        log_file()     
        print("Wait 5 seconds to stablize PIR sensor")
        time.sleep(5)
        print("***DONE****")
        #check_system(camera, mms_sensor_pin, pir_sensor_pin, reed_switch_pin)
        #esp_status_check()
        main_loop()
    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Error: {e}")
        queue_text_message(bot, chat_id, f"Error: {e}")
    finally:
        # Ensure camera is properly closed
        if camera is not None:
            try:
                if hasattr(camera, 'recording') and camera.recording:
                    camera.stop_recording()
                camera.close()
            except Exception as e:
                print(f"Error closing camera in :__name__ == __main__: {e}")          
