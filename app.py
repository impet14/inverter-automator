import os
import pytz
import requests
import logging
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- Configuration Section ---
API_TOKEN = os.environ.get('INVERTER_TOKEN')
PN = os.environ.get('DESS_PN', "Q0029389993714")
SN = os.environ.get('DESS_SN', "Q002938999371409AD05")
DEVCODE = os.environ.get('DESS_DEVCODE', "2477")
BASE_URL = os.environ.get('DESS_BASE_URL', "https://web.dessmonitor.com/public/")
TIMEZONE = os.environ.get('TIMEZONE', 'Asia/Bangkok')

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger("inverter-automator")

# --- API URL Functions ---
def set_solar_mode_url(token):
    return (
        f"{BASE_URL}?sign=2e0255a36c217c429c837c9d1101896e9b766d2e&salt=1759425890532"
        f"&token={token}&action=ctrlDevice&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}"
        f"&devaddr=5&id=los_output_source_priority&val=1&i18n=en_US"
    )

def set_sbu_mode_url(token):
    return (
        f"{BASE_URL}?sign=31a2fd5de82e2a58d551028341b3fb5b8bb03717&salt=1759425937434"
        f"&token={token}&action=ctrlDevice&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}"
        f"&devaddr=5&id=los_output_source_priority&val=2&i18n=en_US"
    )

def read_status_url(token):
    return (
        f"{BASE_URL}?sign=63bdf141c54c44069a37630777185c98ab863121&salt=1759425782351"
        f"&token={token}&action=queryDeviceCtrlValue&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}"
        f"&devaddr=5&id=los_output_source_priority&i18n=en_US"
    )

# --- API Call Helper Function ---
def call_api(url, action_description):
    logger.info(f"COMMAND: {action_description}")
    logger.debug(f"URL: {url}")

    if not API_TOKEN:
        logger.error("FATAL ERROR: The INVERTER_TOKEN secret has not been configured.")
        return None

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        logger.info(f"SUCCESS: API Response from server: {data}")
        if data.get("err") != 0:
            logger.warning(f"The API reported an error: {data.get('desc')}")
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"ERROR: The API call failed. Details: {e}")
        return None
    except Exception as ex:
        logger.exception(f"Unhandled exception: {ex}")
        return None

# --- Job Definitions ---
def set_to_solar_job():
    call_api(set_solar_mode_url(API_TOKEN), "Set output source priority to SOLAR")

def set_to_sbu_job():
    call_api(set_sbu_mode_url(API_TOKEN), "Set output source priority to SBU")

def read_status_job():
    call_api(read_status_url(API_TOKEN), "Read current output source priority status")

# --- Flask Web Application ---
app = Flask(__name__)

@app.route('/')
def home():
    return "<h1>Inverter Control Service</h1><p>The scheduler is active and running in the background.</p>"

@app.route('/status')
def status():
    data = call_api(read_status_url(API_TOKEN), "Read current output source priority status (HTTP request)")
    if data:
        return f"<pre>{data}</pre>"
    else:
        return "<p>Could not read status.</p>", 500

# --- APScheduler Setup ---
scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE))
scheduler.add_job(set_to_solar_job, 'cron', hour=6, minute=13)
scheduler.add_job(set_to_sbu_job, 'cron', hour=18, minute=5)
scheduler.add_job(read_status_job, 'cron', minute=0)  # Every hour, at minute 0

logger.info("Starting the background scheduler...")
scheduler.start()
logger.info("Scheduler started successfully. Jobs are scheduled and waiting.")

# Note: In production, a WSGI server like Gunicorn will run the 'app' object.
