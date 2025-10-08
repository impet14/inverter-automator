# =================================================================================
#  Inverter Control Script for GitHub Actions
# =================================================================================
#  This script is designed to be run by a scheduler. It accepts a command-line
#  argument to determine which specific API action to perform.
# =================================================================================

import os
import sys
import logging
import requests

# --- Logging Configuration ---
# Sets up simple and clear logging for the GitHub Actions console.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("inverter-script")

# --- Configuration from GitHub Secrets ---
# The script will get the token from a secure secret named INVERTER_TOKEN.
INVERTER_TOKEN = os.environ.get('INVERTER_TOKEN')

# Device identifiers (these are constant for your device)
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"
BASE_URL = "https://web.dessmonitor.com/public/"

# --- API URL Definitions ---
# These are the static URLs you provided, ready to be formatted with the token.
URL_CONFIG = {
    'read-status': {
        'description': "Read current status",
        'url': (
            f"{BASE_URL}?sign=60f41fa7d3fbef1e7020a6cee2897532d275d469&salt=1759845291939"
            f"&token={{token}}&action=queryDeviceCtrlValue&source=1&pn={PN}&sn={SN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&i18n=en_US"
        )
    },
    'set-solar': {
        'description': "Set output priority to SOLAR",
        'url': (
            f"{BASE_URL}?sign=4718b344bd43a14e724f617672d64a47ee71d3cc&salt=1759845323170"
            f"&token={{token}}&action=ctrlDevice&source=1&pn={PN}&sn={SN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=1&i18n=en_US"
        )
    },
    'set-sbu': {
        'description': "Set output priority to SBU",
        'url': (
            f"{BASE_URL}?sign=aa99db9e0021b84d4b594bad67f90f848b61287b&salt=1759845374128"
            f"&token={{token}}&action=ctrlDevice&source=1&pn={PN}&sn={SN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=2&i18n=en_US"
        )
    }
}

def call_api(action):
    """
    Looks up the requested action, formats the URL with the token,
    and makes the API call.
    """
    if not INVERTER_TOKEN:
        logger.critical("FATAL ERROR: The INVERTER_TOKEN secret is not configured in GitHub.")
        sys.exit(1) # Exit with an error code

    if action not in URL_CONFIG:
        logger.error(f"Invalid action specified: '{action}'. Must be one of {list(URL_CONFIG.keys())}")
        sys.exit(1)

    config = URL_CONFIG[action]
    url = config['url'].format(token=INVERTER_TOKEN)
    description = config['description']
    
    logger.info(f"Executing job: {description}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status() # Check for HTTP errors like 404 or 500
        data = response.json()

        if data.get("err") == 0:
            logger.info(f"✅ SUCCESS: API call for '{description}' was successful.")
        else:
            logger.warning(f"⚠️ WARNING: API call succeeded, but server reported an error: {data.get('desc', 'No description')}")
        
        logger.info(f"   Full API Response: {data}")

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ ERROR: Network request failed for '{description}'. Details: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inverter_control.py <action>")
        print("Available actions: read-status, set-solar, set-sbu")
        sys.exit(1)
    
    action_to_run = sys.argv[1]
    call_api(action_to_run)

