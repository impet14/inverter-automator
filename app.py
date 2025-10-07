# =================================================================================
#  DESS Monitor Inverter Control Service - Production Version V3
# =================================================================================
#  This script provides a 24/7 web service to automate an inverter via the
#  DESS Monitor API. This version uses the direct login endpoint (v1/login) and
#  HMAC-SHA256 signing to provide a robust, permanent automation solution
#  that does not depend on an unknown COMPANY_KEY.
# =================================================================================

import os
import time
import hashlib
import hmac
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

# --- DESS Monitor API Client Class ---
class DessMonitorAPI:
    """
    A client for the DESS Monitor API that handles the direct login flow
    and HMAC-SHA256 request signing protocol.
    """
    AUTH_URL = "https://api.dessmonitor.com/api/v1/login"
    CMD_URL = "https://web.dessmonitor.com/public/"
    
    # Constants for device and app identification
    APP_CLIENT = "web"
    APP_VERSION = "1.0.0"
    SOURCE = "1"  # '1' for energy storage

    def __init__(self, username, password, pn, sn, devcode, devaddr):
        if not all([username, password, pn, sn, devcode, devaddr]):
            raise ValueError("All API client parameters are required.")
        self.username = username
        self.password = password
        self.pn = pn
        self.sn = sn
        self.devcode = devcode
        self.devaddr = devaddr
        self.session = requests.Session()
        self.token = None
        self.key = None # Note: This endpoint provides a 'key', not a 'secret'
        logger.info("DESS Monitor API client initialized (HMAC-SHA256 Version).")

    def login(self):
        """
        Authenticates with the API's direct login endpoint.
        Returns True on success, False on failure.
        """
        logger.info(f"Attempting to log in to DESS Monitor as '{self.username}'...")
        
        # This endpoint requires the password to be MD5 hashed
        payload = {
            "username": self.username,
            "password": hashlib.md5(self.password.encode('utf-8')).hexdigest(),
            "client": self.APP_CLIENT,
            "version": self.APP_VERSION
        }

        try:
            response = self.session.post(self.AUTH_URL, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("err") == 0 and "dat" in data:
                self.token = data["dat"].get("token")
                self.key = data["dat"].get("key")
                if self.token and self.key:
                    logger.info("✅ Login successful. Session token and signing key obtained.")
                    return True
            
            logger.error(f"Login failed. API returned an error: {data.get('desc', 'No description')}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during login: {e}")
            return False

    def _send_signed_command(self, action, extra_params=None):
        """Generates a signed URL using HMAC-SHA256 and sends a command."""
        if not self.token or not self.key:
            if not self.login(): # Attempt to re-login if session is invalid
                logger.error("Re-login failed. Aborting command.")
                return None
        
        salt = str(int(time.time() * 1000))
        
        # Build the parameter string for signing
        params_for_signing = (
            f"action={action}&devaddr={self.devaddr}&devcode={self.devcode}"
            f"&i18n=en_US&id=los_output_source_priority&pn={self.pn}&salt={salt}"
            f"&sn={self.sn}&source={self.SOURCE}"
        )
        if extra_params and 'val' in extra_params:
            params_for_signing += f"&val={extra_params['val']}"

        # Sign the parameter string using HMAC-SHA256 with the key from login
        sign = hmac.new(self.key.encode('utf-8'), params_for_signing.encode('utf-8'), hashlib.sha256).hexdigest()
        
        # Build the final URL for the GET request
        final_url = f"{self.CMD_URL}?token={self.token}&sign={sign}&{params_for_signing}"
        
        try:
            response = self.session.get(final_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            logger.info(f"API Response for action '{action}': {data}")
            
            # Check for token expiration error and attempt re-login
            if data.get("err") == 10005: # "ERR_TOKEN_INVALID"
                logger.warning("Token expired or invalid. Attempting to log in again...")
                self.token = None # Invalidate token to force re-login on next call
                return self._send_signed_command(action, extra_params) # Retry the command once
            
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during command '{action}': {e}")
            return None

    def set_output_priority(self, mode):
        """Sets output priority. Mode '1' for SOLAR, '2' for SBU."""
        description = "SOLAR" if mode == '1' else "SBU"
        logger.info(f"Executing job: Set output priority to {description}.")
        return self._send_signed_command("ctrlDevice", extra_params={"val": mode})

    def get_status(self):
        """Reads the current output source priority status."""
        logger.info("Executing job: Read status.")
        return self._send_signed_command("queryDeviceCtrlValue")

# --- Environment Variable Loading ---
DESS_USERNAME = os.environ.get('DESS_USERNAME')
DESS_PASSWORD = os.environ.get('DESS_PASSWORD')
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"
TIMEZONE = 'Asia/Bangkok'

# --- Initialization ---
app = Flask(__name__)

# Validate that credentials are set before proceeding
if not DESS_USERNAME or not DESS_PASSWORD:
    logger.critical("FATAL: DESS_USERNAME or DESS_PASSWORD environment variables are not set.")
    # Exit gracefully if running locally; Render will show an error log and stop.
    api_client = None 
else:
    api_client = DessMonitorAPI(DESS_USERNAME, DESS_PASSWORD, PN, SN, DEVCODE, DEVADDR)
    if not api_client.login():
        logger.warning("Initial login failed. The service will attempt to re-login on the first scheduled job.")

# --- Scheduled Jobs ---
# These functions will only run if the api_client was created successfully
def set_solar_job():
    if api_client: api_client.set_output_priority(mode='1')

def set_sbu_job():
    if api_client: api_client.set_output_priority(mode='2')

def read_status_job():
    if api_client: api_client.get_status()

# --- Flask Web Routes ---
@app.route('/')
def home():
    return "<h1>Inverter Control Service</h1><p>The automation scheduler is active.</p>"

# --- Scheduler Setup ---
scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE), misfire_grace_time=600)
scheduler.add_job(set_solar_job, 'cron', hour=6, minute=5, id='set_solar_job')
scheduler.add_job(set_sbu_job, 'cron', hour=18, minute=3, id='set_sbu_job')
scheduler.add_job(read_status_job, 'cron', hour='*', minute=0, id='read_status_job')
scheduler.start()
logger.info("Scheduler started successfully. Current jobs:")
for job in scheduler.get_jobs():
    logger.info(f"  - Job: '{job.id}', Trigger: {job.trigger}")

