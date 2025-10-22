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

# !!! UPDATED BASE URL !!!
BASE_URL = "http://android.shinemonitor.com/public/"

# Common suffix for app client identification (found in the new URLs)
CLIENT_SUFFIX = "&source=1&_app_client_=android&_app_id_=com.eybond.smartclient.ess&_app_version_=3.40.1.0"

# --- API URL Definitions ---
# The URLs are updated with the new 'sign' and 'salt' values.
URL_CONFIG = {
    'read-status': {
        'description': "Read current status",
        # New Sign/Salt: 36a7d1425932c48f9426b80eae61b3f4cacd7872 / 1761121759161
        'url': (
            f"{BASE_URL}?sign=36a7d1425932c48f9426b80eae61b3f4cacd7872&salt=1761121759161"
            f"&token={{token}}&action=queryDeviceCtrlValue&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    },
    'set-solar': {
        'description': "Set output priority to SOLAR (val=1)",
        # New Sign/Salt: 2faa45e70bbeb5e1516680033de9ce6e3f184bed / 1761121932506
        'url': (
            f"{BASE_URL}?sign=2faa45e70bbeb5e1516680033de9ce6e3f184bed&salt=1761121932506"
            f"&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=1&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    },
    'set-sbu': {
        'description': "Set output priority to SBU (val=2)",
        # New Sign/Salt: 713f0bbb9e506796976db45d247219a91a91d766 / 1761121854528
        'url': (
            f"{BASE_URL}?sign=713f0bbb9e506796976db45d247219a91a91d766&salt=1761121854528"
            f"&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=2&i18n=en_US"
            f"{CLIENT_SUFFIX}"
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

    logger.debug(f"Calling URL: {url}")

    try:
        # Increase timeout slightly, especially for control commands
        response = requests.get(url, timeout=45) 
        response.raise_for_status() # Check for HTTP errors like 404 or 500
        
        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            logger.error(f"❌ ERROR: Received non-JSON response from API. Raw content: {response.text[:200]}...")
            sys.exit(1)

        if data.get("err") == 0:
            logger.info(f"✅ SUCCESS: API call for '{description}' was successful.")
        else:
            # Server-side failure, but request was successfully processed by the server
            logger.warning(f"⚠️ WARNING: API call succeeded, but server reported an error: {data.get('desc', 'No description')}")
            # If a command fails, we still want the step to fail so retries trigger.
            if action != 'read-status':
                sys.exit(1) # Fail for control commands
        
        logger.info(f"    Full API Response: {data}")

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ ERROR: Network request failed for '{description}'. Details: {e}")
        sys.exit(1) # Fail the step to trigger retries

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inverter_control.py <action>")
        print("Available actions: read-status, set-solar, set-sbu")
        sys.exit(1)
    
    action_to_run = sys.argv[1]
    call_api(action_to_run)
