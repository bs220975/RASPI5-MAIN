from influxdb import InfluxDBClient
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import telepot

def generate_and_send_sensor_plot(
    host='localhost',
    port=8086,
    username='admin',
    password='admin',
    database='pi4data',
    minutes_back=10,
    plot_path='/tmp/sensor_plot.png'
):
    bot_token = '6457653240:AAHxGnjzebcVb9gwXJ9LyEar0ZYZ2USFCyw'
    chat_id = '6825638285'
    
    try:
        # Connect to InfluxDB
        client = InfluxDBClient(host=host, port=port, username=username, password=password, database=database)

        # Time range
        now = datetime.utcnow()
        start_time = now - timedelta(minutes=minutes_back)
        start_time_str = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Query data
        query = f"""
        SELECT "pir", "mms" FROM "sensor_data"
        WHERE time >= '{start_time_str}' AND time <= '{end_time_str}'
        ORDER BY time ASC
        """
        results = client.query(query)
        points = list(results.get_points())

        # Extract data
        pir_times, pir_values = [], []
        mms_times, mms_values = [], []

        for point in points:
            timestamp = datetime.strptime(point['time'], '%Y-%m-%dT%H:%M:%S.%fZ')
            if point['pir'] is not None:
                pir_times.append(timestamp)
                pir_values.append(point['pir'])
            if point['mms'] is not None:
                mms_times.append(timestamp)
                mms_values.append(point['mms'])

        # Align timestamps
        common_times = sorted(list(set(pir_times) & set(mms_times)))
        if not common_times:
            print("No common timestamps found.")
            return

        times_sec = [(t - common_times[0]).total_seconds() for t in common_times]
        pir_aligned = [pir_values[pir_times.index(t)] for t in common_times]
        mms_aligned = [mms_values[mms_times.index(t)] for t in common_times]
        both_high = [1 if p == 1 and m == 1 else 0 for p, m in zip(pir_aligned, mms_aligned)]

        # Offsets
        mms_offset = [v + 2 for v in mms_aligned]
        both_offset = [v + 4 for v in both_high]

        # Plotting
        plt.figure(figsize=(12, 6))
        plt.plot(times_sec, pir_aligned, label='PIR Sensor', drawstyle='steps-post', color='blue')
        plt.plot(times_sec, mms_offset, label='MMS Sensor (offset)', drawstyle='steps-post', color='orange')
        plt.plot(times_sec, both_offset, label='Both HIGH (offset)', drawstyle='steps-post', color='green', linewidth=2)

        def label_high_periods(times, states, offset=0, color='black'):
            i = 0
            while i < len(states):
                if states[i] == 1:
                    start = i
                    while i < len(states) and states[i] == 1:
                        i += 1
                    end = i
                    duration = times[end-1] - times[start]
                    mid_time = (times[start] + times[end-1]) / 2
                    plt.text(mid_time, states[start] + offset + 0.1,
                             f'{duration:.1f}s', color=color, fontsize=9, ha='center')
                else:
                    i += 1

        label_high_periods(times_sec, pir_aligned, offset=0, color='blue')
        label_high_periods(times_sec, mms_aligned, offset=2, color='orange')
        label_high_periods(times_sec, both_high, offset=4, color='green')

        # Mark start and end time in HH:MM:SS
        start_label = common_times[0].strftime('%H:%M:%S')
        end_label = common_times[-1].strftime('%H:%M:%S')
        plt.text(times_sec[0], -0.8, f'Start: {start_label}', ha='left', fontsize=9, color='gray')
        plt.text(times_sec[-1], -0.8, f'End: {end_label}', ha='right', fontsize=9, color='gray')

        # Axes and labels
        plt.yticks([0, 1, 2, 3, 4, 5],
                   ['PIR LOW', 'PIR HIGH', 'MMS LOW', 'MMS HIGH', '', 'BOTH HIGH'])
        plt.xlabel('Time (seconds)')
        plt.ylabel('Sensor State')
        plt.title(f'Sensor States (Last {minutes_back} minutes)')
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.show()

        # Save and send
        plt.savefig(plot_path)
        plt.close()

        bot = telepot.Bot(bot_token)
        with open(plot_path, 'rb') as photo:
            bot.sendPhoto(chat_id, photo)

        print("Plot saved and sent successfully.")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        client.close()
