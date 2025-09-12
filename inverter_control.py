import requests
import datetime
import os
import pytz
import sys

# --- Configuration ---
# We will get the sensitive token from GitHub Secrets, not hardcoded here.
# The script expects an environment variable named 'INVERTER_TOKEN'.
API_TOKEN = os.environ.get('INVERTER_TOKEN')

# Your device identifiers from the URL
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"

# --- API URL Templates ---
# Using f-strings to build the URLs dynamically with the token and parameters
BASE_URL = "https://web.dessmonitor.com/public/"

def get_status_url(token):
    """Returns the URL to check the inverter's status."""
    return (
        f"{BASE_URL}?sign=12722bef3236d34648f8f8324421b51a9a400e4a&salt=1757519926971"
        f"&token={token}&action=queryDeviceCtrlValue&source=1&pn={PN}&sn={SN}"
        f"&devcode={DEVCODE}&devaddr=5&id=los_output_source_priority&i18n=en_US"
    )

def set_solar_mode_url(token):
    """Returns the URL to set the inverter to 'Solar' mode (val=1)."""
    return (
        f"{BASE_URL}?sign=df5476429be8d15e10b56046a8d487208142e5e4&salt=1757519959751"
        f"&token={token}&action=ctrlDevice&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}"
        f"&devaddr=5&id=los_output_source_priority&val=1&i18n=en_US"
    )

def set_sbu_mode_url(token):
    """Returns the URL to set the inverter to 'SBU' mode (val=2)."""
    return (
        f"{BASE_URL}?sign=a436acce54f3fc3403c05fc39720e95daf5584c1&salt=1757520016839"
        f"&token={token}&action=ctrlDevice&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}"
        f"&devaddr=5&id=los_output_source_priority&val=2&i18n=en_US"
    )

def call_api(url, action_description):
    """A helper function to make API calls and handle responses."""
    print(f"Attempting to: {action_description}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raises an exception for bad status codes (4xx or 5xx)
        data = response.json()
        print(f"SUCCESS: API Response: {data}")
        if data.get("err") != 0:
            print(f"WARNING: API returned an error: {data.get('desc')}")
        return data
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not connect to API. Details: {e}")
        return None

def run_scheduled_logic():
    """
    This function contains the original time-based logic for scheduled runs.
    """
    # Set the timezone to your local time (Bangkok, Thailand)
    # List of timezones: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
    local_timezone = pytz.timezone("Asia/Bangkok")
    current_time = datetime.datetime.now(local_timezone)
    current_hour = current_time.hour

    print(f"Script run at: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Current hour in your timezone is: {current_hour}")

    # --- Logic to decide which mode to set ---
    # We define a "morning" window and an "evening" window.
    # This makes the script work even if it runs a few minutes late.
    if 5 <= current_hour < 15:
        # It's morning, set to Solar mode
        print("Time is in the morning window (5 AM - 3 PM). Setting to SOLAR mode.")
        call_api(set_solar_mode_url(API_TOKEN), "Set output source to SOLAR")
    elif 16 <= current_hour < 24:
        # It's evening, set to SBU mode
        print("Time is in the evening window (4 PM - 0 AM). Setting to SBU mode.")
        call_api(set_sbu_mode_url(API_TOKEN), "Set output source to SBU")
    else:
        # It's not the scheduled time, do nothing
        print("Not within a scheduled action window. No action will be taken.")


def main():
    """
    Main function to run the inverter control logic.
    Checks for command-line arguments to run specific functions manually.
    If no arguments are provided, it runs the default scheduled logic.
    """
    if not API_TOKEN:
        print("FATAL ERROR: INVERTER_TOKEN environment variable not set.")
        print("Please configure the secret in your GitHub repository settings.")
        return

    # Check if a command-line argument was provided (e.g., "status", "solar", "sbu")
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        print(f"Manual command received: '{command}'")
        if command == "status":
            call_api(get_status_url(API_TOKEN), "Get inverter status")
        elif command == "solar":
            call_api(set_solar_mode_url(API_TOKEN), "Manually set output source to SOLAR")
        elif command == "sbu":
            call_api(set_sbu_mode_url(API_TOKEN), "Manually set output source to SBU")
        else:
            print(f"Error: Unknown command '{command}'. Valid commands are: status, solar, sbu.")
    else:
        # No command provided, run the default time-based logic for the schedule
        print("No manual command detected. Running scheduled logic.")
        run_scheduled_logic()

if __name__ == "__main__":
    main()

