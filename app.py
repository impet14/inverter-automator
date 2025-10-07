# =================================================================================
#  DESS Monitor Inverter Control Service - Static API Version
# =================================================================================
#  This script uses a simple, static URL approach to control the inverter.
#  It relies on a manually provided, long-lived token, removing the complexities
#  of dynamic authentication to ensure immediate functionality and reliability.
# =================================================================================

import os
import logging
import requests
import pytz
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("inverter-automator")

# --- Configuration from Environment Variables ---
# This is the ONLY secret you need to configure on Render.com
INVERTER_TOKEN = os.environ.get('INVERTER_TOKEN')

# Device identifiers (hardcoded as they are constant for your device)
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"
TIMEZONE = 'Asia/Bangkok'
BASE_URL = "https://web.dessmonitor.com/public/"

# --- API Call Helper ---
def call_api(url, action_description):
    """A robust function to make an API call and handle responses."""
    logger.info(f"Executing job: {action_description}")
    
    if not INVERTER_TOKEN:
        logger.critical("FATAL ERROR: The INVERTER_TOKEN environment variable is not set. Cannot send command.")
        return None

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raises an error for bad status codes (4xx or 5xx)
        data = response.json()
        
        if data.get("err") == 0:
            logger.info(f"✅ SUCCESS: API call for '{action_description}' was successful.")
        else:
            logger.warning(f"⚠️ WARNING: API call succeeded, but the server reported an error: {data.get('desc', 'No description')}")
            
        logger.info(f"   Full API Response: {data}")
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ ERROR: Network request failed for '{action_description}'. Details: {e}")
        return None

# --- Scheduled Job Functions ---
def set_solar_job():
    """Constructs the URL and calls the API to set SOLAR mode."""
    # Using the static sign and salt from your working URL
    static_params = (
        "sign=4718b344bd43a14e724f617672d64a47ee71d3cc&salt=1759845323170"
    )
    url = (
        f"{BASE_URL}?{static_params}&token={INVERTER_TOKEN}&action=ctrlDevice"
        f"&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}&devaddr={DEVADDR}"
        f"&id=los_output_source_priority&val=1&i18n=en_US"
    )
    call_api(url, "Set output priority to SOLAR")

def set_sbu_job():
    """Constructs the URL and calls the API to set SBU mode."""
    # Using the static sign and salt from your working URL
    static_params = (
        "sign=aa99db9e0021b84d4b594bad67f90f848b61287b&salt=1759845374128"
    )
    url = (
        f"{BASE_URL}?{static_params}&token={INVERTER_TOKEN}&action=ctrlDevice"
        f"&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}&devaddr={DEVADDR}"
        f"&id=los_output_source_priority&val=2&i18n=en_US"
    )
    call_api(url, "Set output priority to SBU")

def read_status_job():
    """Constructs the URL and calls the API to read the current status."""
    # Using the static sign and salt from your working URL
    static_params = (
        "sign=60f41fa7d3fbef1e7020a6cee2897532d275d469&salt=1759845291939"
    )
    url = (
        f"{BASE_URL}?{static_params}&token={INVERTER_TOKEN}&action=queryDeviceCtrlValue"
        f"&source=1&pn={PN}&sn={SN}&devcode={DEVCODE}&devaddr={DEVADDR}"
        f"&id=los_output_source_priority&i18n=en_US"
    )
    call_api(url, "Read current status")

# --- Flask Web App ---
app = Flask(__name__)

@app.route('/')
def home():
    return "<h1>Inverter Control Service (Static API Version)</h1><p>The automation scheduler is active.</p>"

# --- Scheduler Setup ---
scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE), misfire_grace_time=600)
scheduler.add_job(set_solar_job, 'cron', hour=6, minute=5, id='set_solar_job')
scheduler.add_job(set_sbu_job, 'cron', hour=18, minute=3, id='set_sbu_job')
scheduler.add_job(read_status_job, 'cron', hour='*', minute=0, id='read_status_job')
scheduler.start()
logger.info("Scheduler started successfully with static API configuration. Current jobs:")
for job in scheduler.get_jobs():
    logger.info(f"  - Job: '{job.id}', Trigger: {job.trigger}")

