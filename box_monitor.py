import Adafruit_DHT
import time
import requests
from RPLCD.i2c import CharLCD

# =========================
# SETTINGS
# =========================

DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 17

LCD_I2C_ADDRESS = 0x27
LCD_COLS = 16
LCD_ROWS = 2

MOONRAKER_URL = "http://127.0.0.1:7125"

SCREEN_TIME = 3
REFRESH_TIME = 1

# =========================
# LCD
# =========================

lcd = CharLCD(
    i2c_expander="PCF8574",
    address=LCD_I2C_ADDRESS,
    cols=LCD_COLS,
    rows=LCD_ROWS
)

degree_symbol = [
    0b00100,
    0b01010,
    0b00100,
    0b00000,
    0b00000,
    0b00000,
    0b00000,
    0b00000
]

percent_symbol = [
    0b11000,
    0b11001,
    0b00010,
    0b00100,
    0b01000,
    0b10011,
    0b00011,
    0b00000
]

lcd.create_char(0, degree_symbol)
lcd.create_char(1, percent_symbol)


# =========================
# FUNCTION
# =========================

def fit_text(text, length=16):
    text = str(text)
    if len(text) > length:
        return text[:length]
    return text.center(length)


def scroll_filename(text, position, length=16):
    text = str(text)

    if len(text) <= length:
        return text.center(length)

    text = text + "    "
    start = position % len(text)
    display_text = text + text

    return display_text[start:start + length]


def display_lcd(line1, line2):
    try:
        lcd.clear()
        lcd.cursor_pos = (0, 0)
        lcd.write_string(fit_text(line1))
        lcd.cursor_pos = (1, 0)
        lcd.write_string(fit_text(line2))
    except OSError as e:
        print(f"LCD chyba: {e}")


def read_dht22():
    humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
    return temperature, humidity


def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read().strip()) / 1000
    except Exception:
        return None


def seconds_to_time(seconds):
    if seconds is None:
        return "--:--"

    seconds = int(seconds)

    if seconds < 0:
        seconds = 0

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    return f"{hours:02d}:{minutes:02d}"


def get_moonraker_data():
    url = (
        f"{MOONRAKER_URL}/printer/objects/query?"
        "print_stats"
        "&display_status"
        "&extruder"
        "&heater_bed"
        "&virtual_sdcard"
    )

    try:
        response = requests.get(url, timeout=2)
        response.raise_for_status()
        data = response.json()

        status = data["result"]["status"]

        print_stats = status.get("print_stats", {})
        display_status = status.get("display_status", {})
        extruder = status.get("extruder", {})
        heater_bed = status.get("heater_bed", {})
        virtual_sdcard = status.get("virtual_sdcard", {})

        state = print_stats.get("state", "unknown")
        filename = print_stats.get("filename", "")

        progress = display_status.get("progress", 0)
        if progress is None:
            progress = 0

        progress_percent = progress * 100

        print_duration = print_stats.get("print_duration", 0)

        remaining_time = None
        if progress > 0.01 and print_duration:
            estimated_total = print_duration / progress
            remaining_time = estimated_total - print_duration

        return {
            "online": True,
            "state": state,
            "filename": filename,
            "progress": progress_percent,
            "print_duration": print_duration,
            "remaining_time": remaining_time,

            "hotend_temp": extruder.get("temperature", 0),
            "hotend_target": extruder.get("target", 0),

            "bed_temp": heater_bed.get("temperature", 0),
            "bed_target": heater_bed.get("target", 0),

            "sd_progress": virtual_sdcard.get("progress", 0) * 100
        }

    except Exception:
        return {
            "online": False
        }


def short_state(state):
    states = {
        "printing": "PRINT",
        "paused": "PAUSE",
        "complete": "DONE",
        "standby": "IDLE",
        "error": "ERROR",
        "cancelled": "CANCEL"
    }

    return states.get(state, state.upper()[:6])


# =========================
# MAIN PROGRAM
# =========================

try:
    screen_index = 0
    last_screen_change = time.time()
    filename_scroll = 0

    while True:
        box_temp, box_hum = read_dht22()
        cpu_temp = get_cpu_temp()
        printer = get_moonraker_data()

        if time.time() - last_screen_change >= SCREEN_TIME:
            screen_index += 1
            last_screen_change = time.time()

        screens = []

        if box_temp is None or box_hum is None:
            line1 = "CHYBA SENZORU"
            if cpu_temp is not None:
                line2 = f"Rpi {cpu_temp:.1f}\x00C"
            else:
                line2 = "Rpi --.-C"
        else:
            line1 = f"Box {box_temp:.1f}\x00C {box_hum:.1f}\x01"
            if cpu_temp is not None:
                line2 = f"Rpi {cpu_temp:.1f}\x00C"
            else:
                line2 = "Rpi --.-C"

        screens.append((line1, line2))

        if printer["online"]:
            state = short_state(printer["state"])
            progress = printer["progress"]
            remaining = seconds_to_time(printer["remaining_time"])

            screens.append((
                f"{state} {progress:.0f}\x01",
                f"Zbyva {remaining}"
            ))

            screens.append((
                f"H {printer['hotend_temp']:.0f}/{printer['hotend_target']:.0f}\x00C",
                f"B {printer['bed_temp']:.0f}/{printer['bed_target']:.0f}\x00C"
            ))

            filename = printer["filename"]

            if filename:
                filename = filename.replace(".gcode", "")
                filename = filename.replace("_", " ")

                screens.append((
                    "Soubor:",
                    scroll_filename(filename, filename_scroll)
                ))
            else:
                screens.append((
                    "Soubor:",
                    "zadny tisk"
                ))

        else:
            screens.append((
                "Moonraker",
                "offline/API err"
            ))

        current_screen = screens[screen_index % len(screens)]
        display_lcd(current_screen[0], current_screen[1])

        if current_screen[0] == "Soubor:":
            filename_scroll += 1

        time.sleep(REFRESH_TIME)

except KeyboardInterrupt:
    print("Ukoncuji program...")
    lcd.clear()