from hx711 import HX711
from time import sleep, time
from machine import Pin, UART
import urequests
import network  # Add this import

# --- WiFi Configuration ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to WiFi...')
        wlan.connect('chuchuz', '1234567890')  # Replace with your WiFi credentials
        while not wlan.isconnected():
            pass
    print('\nWiFi Connected!')
    print('Device IP:', wlan.ifconfig()[0])
    return wlan.ifconfig()[0]  # Return the IP address

# Initialize WiFi before other code
device_ip = connect_wifi()

# ===============================
# --- HX711 (Weighing Scale) ---
# ===============================
hx = HX711(13, 12)

print("🔧 Initializing digital scale...")
hx.tare()
print("⚖️ Scale tared and ready.")

hx.SCALE = 69450.81  # Calibration factor

MAX_LOAD = 20.0
MIN_LOAD = 0.05
STABLE_TIME = 2.0
SAMPLE_INTERVAL = 0.1
STABLE_TOLERANCE = 0.02
ZERO_TRACK_TOLERANCE = 0.01

# --- LED Pins ---
led_power = Pin(18, Pin.OUT)
led_load = Pin(19, Pin.OUT)
led_overload = Pin(21, Pin.OUT)
led_network = Pin(22, Pin.OUT)  # Add a new LED on GPIO22 for network status
led_power.on()

last_weight = 0.0
stable_start = None
locked_weight = None
is_locked = False

print("\n🟢 Commercial-Style Weighing Scale Ready!\n")

# ===============================
# --- GSM MODULE (Independent) ---
# ===============================
# Example: SIM800L connected to UART2 (GPIO16=RX, GPIO17=TX)
uart = UART(2, baudrate=9600, tx=17, rx=16, timeout=1000)

def send_sms(number, message):
    """Send SMS using GSM module."""
    uart.write('AT\r\n')
    sleep(0.5)
    uart.write('AT+CMGF=1\r\n')  # Set SMS text mode
    sleep(0.5)
    uart.write('AT+CMGS="{}"\r\n'.format(number))
    sleep(0.5)
    uart.write(message + '\r\n')
    uart.write(chr(26))  # End message (Ctrl+Z)
    sleep(2)
    print("\n📩 SMS sent to", number)

def check_incoming_sms():
    """Optional: Check for incoming messages (non-blocking)."""
    if uart.any():
        data = uart.read().decode('utf-8')
        if data.strip():
            print("\n📨 Incoming GSM Data:\n", data)

last_successful_send = 0
RECONNECT_INTERVAL = 5  # Try reconnecting every 5 seconds

def send_weight_to_flask(weight):
    """Send weight to Flask backend with improved error handling."""
    global last_successful_send
    try:
        # Turn off network LED while attempting to send
        led_network.off()
        
        flask_url = f"http://192.168.32.236:5000/api/weight"  # Change this to your Flask server IP
        print(f"ESP32 IP: {device_ip} -> Flask: {flask_url}")  # Debug print
        
        headers = {'Content-Type': 'application/json'}
        data = {'weight': weight}
        
        # Add timeout to prevent hanging
        response = urequests.post(flask_url, json=data, headers=headers, timeout=1)
        response.close()
        
        # Success - turn on network LED
        led_network.on()
        last_successful_send = time()
        return True
        
    except Exception as e:
        current_time = time()
        # Only print error message every RECONNECT_INTERVAL seconds
        if current_time - last_successful_send >= RECONNECT_INTERVAL:
            print(f"\nConnection error: {e}")
            print("Make sure Flask server is running at the correct IP")
            print("Retrying in 5 seconds...")
        return False

# ===============================
# --- MAIN LOOP ---
# ===============================
try:
    led_network.off()  # Start with network LED off
    while True:
        # --- GSM check (independent from weighing) ---
        check_incoming_sms()

        # --- HX711 logic ---
        weight = hx.get_units()
        if weight < 0:
            weight = 0.0

        if weight < ZERO_TRACK_TOLERANCE:
            weight = 0.0

        if weight > MAX_LOAD:
            led_overload.on()
            led_load.off()
            print("\r⚠️ Overload! Remove weight.", end="")
            sleep(SAMPLE_INTERVAL)
            continue
        else:
            led_overload.off()

        if weight >= MIN_LOAD:
            led_load.on()
        else:
            led_load.off()

        diff = abs(weight - last_weight)
        now = time()

        if diff <= STABLE_TOLERANCE:
            if stable_start is None:
                stable_start = now
            elif now - stable_start >= STABLE_TIME and not is_locked and weight >= MIN_LOAD:
                locked_weight = round(weight, 2)
                is_locked = True
        else:
            stable_start = None
            if is_locked and abs(weight - locked_weight) > STABLE_TOLERANCE:
                is_locked = False
                locked_weight = None

        if is_locked:
            print(f"\r🧺 {locked_weight:.2f} kg (Stable)", end="")
            if send_weight_to_flask(locked_weight):
                led_network.on()
        else:
            print(f"\r⚖️ {weight:.2f} kg", end="")
            if send_weight_to_flask(weight):
                led_network.on()

        if is_locked and weight < MIN_LOAD:
            print("\r✅ Load removed — resetting...", end="")
            hx.tare()
            is_locked = False
            stable_start = None
            locked_weight = None
            led_load.off()
            sleep(1)
            print("\r⚖️ 0.00 kg          ", end="")

        last_weight = weight
        sleep(SAMPLE_INTERVAL)

except KeyboardInterrupt:
    led_power.off()
    led_load.off()
    led_overload.off()
    led_network.off()  # Turn off network LED
    print("\n🛑 Scale stopped.")

