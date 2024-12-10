import subprocess
import argparse
import time
import logging
import logging.handlers
import json
from datetime import datetime
import os
import threading
from prometheus_client import start_http_server, Gauge

# Full path to the config.json
config_file_path = r"/app/config.json"

# Open and read the config file
try:
    with open(config_file_path, 'r') as config_file:
        config = json.load(config_file)
except FileNotFoundError:
    print(f"Error: The config file was not found at {config_file_path}")
    exit(1)
except json.JSONDecodeError:
    print("Error: The config file is not a valid JSON.")
    exit(1)

# Prometheus metrics
metric_success = Gauge('smoketest_success', 'Indicates if a smoke test succeeded (1 for success, 0 for failure)', ['test_name'])
metric_success_duration_millisec = Gauge('smoketest_duration_millisec', 'Duration (in ms) for a smoke test to succeed', ['test_name'])
metric_smoketest_exporter_status = Gauge('exporter_status', 'Indicates if the smoke test exporter is running (1 for running, 0 for stopped)')

raw_metrics = {}  # All metrics will be stored here

def write_log(level, message):
    batchtime = datetime.today().strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # Generating batchtime as a string
    log_message = batchtime + ' ' + 'message=\"' + message.strip().replace(";", "\t")
    my_logger.debug(log_message + '\n')
    if 'SERVICE_DEBUG' in os.environ.keys():
        if os.environ['SERVICE_DEBUG'] == 'true':
            print(log_message)

def smoketest(config, service):
    result = {
        "success": 0,
        "duration": 0,
        "raw_message": ""  # To be logged in log files
    }

    while True:
        start_time = time.time()
        try:
            output = subprocess.run(
                config['services'][service]['command'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=config['services'][service]['timeout']
            )
        except subprocess.TimeoutExpired:
            result['success'] = 0
            result['raw_message'] = f"{service} smoketest timed out."
        else:
            end_time = time.time()
            if output.returncode != 0:
                result['success'] = 0
                result['raw_message'] = output.stderr
            else:
                result['success'] = 1
                result['duration'] = (end_time - start_time) * 1000  # Convert to milliseconds
                result['raw_message'] = f"{service} smoketest is successful in {result['duration']} ms."

        # Update metrics
        metric_success.labels(test_name=service).set(result['success'])
        if result['success'] == 1:
            metric_success_duration_millisec.labels(test_name=service).set(result['duration'])

        # Update the global raw_metrics with the latest result
        raw_metrics[service] = result

        # Log the result
        write_log("INFO", result['raw_message'])

        time.sleep(60)  # Loop delay

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str, help='Smoketest configuration.')
    parser.add_argument('-f', '--log-file', type=str, help='Log file output for script.')
    args = parser.parse_args()

    log_file = args.log_file if args.log_file else "smoketest.log"
    if not os.path.exists(log_file):
        open(log_file, 'a').close()

    print(f"Logging to file: {log_file}")  # Debugging statement
    try:
        handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=100000, backupCount=5)
        handler.terminator = ''  # Suppress newline
        global my_logger
        my_logger = logging.getLogger('MyLogger')
        my_logger.setLevel(logging.DEBUG)
        my_logger.addHandler(handler)
    except Exception as e:
        print(f"Error configuring logger: {e}")
        exit(1)

    # Start Prometheus HTTP server to expose metrics
    start_http_server(8000)
    metric_smoketest_exporter_status.set(1)  # Set exporter status to running
    print("Prometheus HTTP server started on port 8000.")

    # Spawning threads for smoketest
    for service in config['services'].keys():
        raw_metrics[service] = {"success": None, "duration": None, "raw_message": None}
        write_log('INFO', f'Spawning thread for smoketest: {service}')
        t = threading.Thread(target=smoketest, args=(config, service))
        t.start()

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        metric_smoketest_exporter_status.set(0)  # Set exporter status to stopped
        print("Exporter stopped.")

if __name__ == '__main__':
    main()
