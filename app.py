# this file main for render to automate control inverter
import os
import pytz
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- Configuration Section ---
# We will get the API_TOKEN from a secure environment variable later.
API_TOKEN = os.environ.get('INVERTER_TOKEN') 
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
BASE_URL = "https://web.dessmonitor.com/public/"

# --- API URL Functions ---
# These functions build the correct API URLs with your new sign and salt values.
def set_solar_mode_url(token):
    """Returns the URL to set to 'Solar' mode with the NEW signature."""
    return (
        f"{BASE_URL}?sign=bfd02f3e740be5be842badb0876b29659bf4fd59&salt=1757925531700"
        f"&token={token}&action=ctrlDevice&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}"
        f"&devaddr=5&id=los_output_source_priority&val=1&i18n=en_US"
    )

def set_sbu_mode_url(token):
    """Returns the URL to set to 'SBU' mode with the NEW signature."""
    return (
        f"{BASE_URL}?sign=b6e3f81ce74e84b2f4c3c1d2ed5c14ecfc16a514&salt=1757925702459"
        f"&token={token}&action=ctrlDevice&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}"
        f"&devaddr=5&id=los_output_source_priority&val=2&i18n=en_US"
    )

# --- API Call Helper Function ---
# This reusable function handles calling the API and logging the outcome.
def call_api(url, action_description):
    print(f"Executing scheduled job: {action_description}")
    if not API_TOKEN:
        print("FATAL ERROR: The INVERTER_TOKEN secret has not been configured.")
        return
    try:
        # Make the web request to the inverter API
        response = requests.get(url, timeout=30)
        response.raise_for_status() # Raise an error for bad responses (4xx or 5xx)
        data = response.json()
        print(f"SUCCESS: API Response from server: {data}")
        if data.get("err") != 0:
            print(f"WARNING: The API reported an error: {data.get('desc')}")
    except requests.exceptions.RequestException as e:
        print(f"ERROR: The API call failed. Details: {e}")

# --- Job Definitions ---
# These are the specific functions our scheduler will run at the set times.
def set_to_solar_job():
    """Job to switch the inverter to Solar mode."""
    call_api(set_solar_mode_url(API_TOKEN), "Set output source priority to SOLAR")

def set_to_sbu_job():
    """Job to switch the inverter to SBU mode."""
    call_api(set_sbu_mode_url(API_TOKEN), "Set output source priority to SBU")


# --- Flask Web Application ---
# This part of the code creates a simple web server that keeps our script running 24/7.
app = Flask(__name__)

@app.route('/')
def home():
    """This creates a simple webpage to show that our service is alive and running."""
    return "<h1>Inverter Control Service</h1><p>The scheduler is active and running in the background.</p>"

# --- APScheduler Setup ---
# This is our high-precision internal clock. We set it to your local timezone.
scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Bangkok'))

# Schedule the jobs to run at your precise local times using 'cron' syntax.
scheduler.add_job(set_to_solar_job, 'cron', hour=9, minute=0)
scheduler.add_job(set_to_sbu_job, 'cron', hour=18, minute=0)

# Start the scheduler in the background.
print("Starting the background scheduler...")
scheduler.start()
print("Scheduler started successfully. Jobs are scheduled and waiting.")

# Note: In a production environment like Render, a professional server called Gunicorn
# will run the 'app' object. We don't need app.run() here.

