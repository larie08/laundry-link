from machine import Pin
from time import sleep
import hx711
import network

try:
    import urequests as requests
except ImportError:
    import requests  # fallback for some builds

# Change this to your Flask server IP address
FLASK_SERVER = "http://192.168.32.236:5000"  # <-- set to your computer's IP from ipconfig

# Connect to WiFi
SSID = "chuchuz"  # <-- your WiFi name
PASSWORD = "<1234567890>"  # <-- your WiFi password

sta_if = network.WLAN(network.STA_IF)
sta_if.active(True)
if not sta_if.isconnected():
    print("Connecting to WiFi...")
    sta_if.connect(SSID, PASSWORD)
    timeout = 15  # seconds
    waited = 0
    while not sta_if.isconnected() and waited < timeout:
        sleep(1)
        waited += 1
    if not sta_if.isconnected():
        print("Failed to connect to WiFi. Check SSID and password, and ensure your router is working.")
        raise OSError("WiFi connection failed")
print("Connected:", sta_if.isconnected())
print("SSID:", sta_if.config('essid'))
print("IP address:", sta_if.ifconfig()[0])

hx = hx711.HX711(d_out=19, pd_sck=21)

hx.tare()
print("Tare complete. Starting measurements...")

while True:
    try:
        val = hx.get_value()
        print("Weight reading:", val)
        # Send weight to Flask backend
        try:
            url = FLASK_SERVER + "/api/weight"
            payload = {"weight": val}
            headers = {'Content-Type': 'application/json'}
            requests.post(url, json=payload, headers=headers)
        except Exception as http_err:
            print("HTTP error:", http_err)
            print("Check your WiFi connection, Flask server IP, and ensure the server is running and reachable from this device.")
        sleep(0.5)
    except Exception as e:
        print("Error:", e)
        sleep(1)

