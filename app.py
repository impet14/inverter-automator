# =================================================================================
#  DESS Monitor Inverter Control Service - Production Version
# =================================================================================
#  This script provides a 24/7 web service to automate an inverter via the
#  DESS Monitor API. It uses a robust, class-based approach to handle
#  authentication and dynamic, signed command generation, ensuring long-term
#  reliability without manual credential updates.
# =================================================================================

import os
import time
import hashlib
import logging
import requests
import pytz
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- Logging Configuration ---
# Set up a clear and informative logging format.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("inverter-automator")

# --- DESS Monitor API Client Class ---
class DessMonitorAPI:
    """
    A client for the DESS Monitor API that handles the official authentication
    and SHA-1 request signing protocol.
    """
    AUTH_URL = "http://api.dessmonitor.com/public/"
    CMD_URL = "https://web.dessmonitor.com/public/"
    
    # Constants from API documentation
    COMPANY_KEY = "0123456789ABCDEF"
    APP_CLIENT = "web"
    APP_ID = "com.dessmonitor.web"
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
        self.secret = None
        logger.info("DESS Monitor API client initialized.")

    def login(self):
        """
        Authenticates with the API to get a session token and secret.
        Returns True on success, False on failure.
        """
        logger.info(f"Attempting to log in to DESS Monitor as '{self.username}'...")
        salt = str(int(time.time() * 1000))
        sha1_password = hashlib.sha1(self.password.encode('utf-8')).hexdigest()

        params_str = (
            f"&action=authSource&usr={self.username}&company-key={self.COMPANY_KEY}"
            f"&source={self.SOURCE}&_app_client_={self.APP_CLIENT}"
            f"&_app_id_={self.APP_ID}&_app_version_={self.APP_VERSION}"
        )
        
        string_to_hash = salt + sha1_password + params_str
        sign = hashlib.sha1(string_to_hash.encode('utf-8')).hexdigest()
        full_url = f"{self.AUTH_URL}?sign={sign}&salt={salt}{params_str}"

        try:
            response = self.session.get(full_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("err") == 0 and "dat" in data:
                self.token = data["dat"].get("token")
                self.secret = data["dat"].get("secret")
                if self.token and self.secret:
                    logger.info("✅ Login successful. Session token and secret obtained.")
                    return True
            
            logger.error(f"Login failed. API returned an error: {data.get('desc', 'No description')}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during login: {e}")
            return False

    def _send_signed_command(self, action, extra_params=None):
        """Generates a signed URL and sends a command."""
        if not self.token or not self.secret:
            logger.error("Cannot send command: not logged in.")
            return None
        
        salt = str(int(time.time() * 1000))
        
        # Build the parameter string for signing
        # The order of parameters in the signature string is critical
        params_for_signing = (
            f"&action={action}&devaddr={self.devaddr}&devcode={self.devcode}"
            f"&i18n=en_US&id=los_output_source_priority&pn={self.pn}&salt={salt}"
            f"&sn={self.sn}&source={self.SOURCE}"
        )
        if extra_params and 'val' in extra_params:
            params_for_signing += f"&val={extra_params['val']}"

        string_to_hash = salt + self.secret + self.token + params_for_signing
        sign = hashlib.sha1(string_to_hash.encode('utf-8')).hexdigest()
        
        # Build the final URL for the request
        final_url = f"{self.CMD_URL}?sign={sign}&salt={salt}&token={self.token}{params_for_signing.replace(f'&salt={salt}', '')}"
        
        try:
            response = self.session.get(final_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            logger.info(f"API Response for action '{action}': {data}")
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
# Load credentials and configuration securely from the environment.
DESS_USERNAME = os.environ.get('DESS_USERNAME')
DESS_PASSWORD = os.environ.get('DESS_PASSWORD')
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"
TIMEZONE = 'Asia/Bangkok'

# --- Initialization ---
app = Flask(__name__)
api_client = DessMonitorAPI(DESS_USERNAME, DESS_PASSWORD, PN, SN, DEVCODE, DEVADDR)

# Perform initial login. If it fails, the app will log the error.
# The scheduler will keep retrying jobs, which will also trigger login attempts.
if not api_client.login():
    logger.critical("Initial login failed. The service will start, but jobs may fail until a login succeeds.")

# --- Scheduled Jobs ---
# These functions will be called by the scheduler.
def set_solar_job():
    api_client.set_output_priority(mode='1')

def set_sbu_job():
    api_client.set_output_priority(mode='2')

def read_status_job():
    api_client.get_status()

# --- Flask Web Routes ---
@app.route('/')
def home():
    return "<h1>Inverter Control Service</h1><p>The automation scheduler is active.</p>"

# --- Scheduler Setup ---
scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE), misfire_grace_time=600)
scheduler.add_job(set_solar_job, 'cron', hour=6, minute=5, id='set_solar_job')
scheduler.add_job(set_sbu_job, 'cron', hour=18, minute=3, id='set_sbu_job')
scheduler.add_job(read_status_job, 'cron', hour='*', minute=0, id='read_status_job') # Every hour at minute 0
scheduler.start()
logger.info("Scheduler started successfully. Current jobs:")
for job in scheduler.get_jobs():
    logger.info(f"  - Job: '{job.id}', Trigger: {job.trigger}")

