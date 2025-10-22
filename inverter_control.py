# =================================================================================
#  Inverter Control Script for GitHub Actions (ShineMonitor Android API)
# =================================================================================
#  Uses endpoints at http://android.shinemonitor.com/public/ (as provided)
#  Token is supplied via GitHub Secret: INVERTER_TOKEN
# =================================================================================

import os
import sys
import logging
import requests

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("inverter-script")

# --- Configuration from GitHub Secrets ---
INVERTER_TOKEN = os.environ.get('INVERTER_TOKEN')

# Device identifiers (constant for your device)
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"

# New Android API base + common app params
BASE_URL = "http://android.shinemonitor.com/public/"
COMMON_TAIL = (
    "&i18n=en_US&source=1"
    "&_app_client_=android"
    "&_app_id_=com.eybond.smartclient.ess"
    "&_app_version_=3.40.1.0"
)

# ---------------------------------------------------------------------------------
# NOTE on sign/salt:
# These sign/salt pairs came from your working examples. If they rotate again, just
# replace the sign/salt strings here—no code changes elsewhere are required.
# ---------------------------------------------------------------------------------

URL_CONFIG = {
    'read-status': {
        'description': "Read current load priority mode",
        'url': (
            f"{BASE_URL}"
            "?sign=36a7d1425932c48f9426b80eae61b3f4cacd7872"
            "&salt=1761121759161"
            "&token={{token}}"
            "&action=queryDeviceCtrlValue"
            f"&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}"
            "&id=los_output_source_priority"
            f"{COMMON_TAIL}"
        )
    },
    'set-sbu': {
        'description': "Set output priority to SBU",
        'url': (
            f"{BASE_URL}"
            "?sign=713f0bbb9e506796976db45d247219a91a91d766"
            "&salt=1761121854528"
            "&token={{token}}"
            "&action=ctrlDevice"
            f"&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}"
            "&id=los_output_source_priority&val=2"
            f"{COMMON_TAIL}"
        )
    },
    'set-solar': {
        'description': "Set output priority to SOLAR",
        'url': (
            f"{BASE_URL}"
            "?sign=2faa45e70bbeb5e1516680033de9ce6e3f184bed"
            "&salt=1761121932506"
            "&token={{token}}"
            "&action=ctrlDevice"
            f"&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}"
            "&id=los_output_source_priority&val=1"
            f"{COMMON_TAIL}"
        )
    },
}

# Optional decoding of mode to human text
MODE_MAP = {
    "0": "UTILITY (Grid) priority",
    "1": "SOLAR priority",
    "2": "SBU (Solar-Battery-Utility) priority",
    0: "UTILITY (Grid) priority",
    1: "SOLAR priority",
    2: "SBU (Solar-Battery-Utility) priority",
}

def _pretty_mode(val):
    return MODE_MAP.get(val, f"Unknown({val})")

def call_api(action):
    """
    Looks up the requested action, formats the URL with the token,
    and makes the API call. Logs useful details.
    """
    if not INVERTER_TOKEN:
        logger.critical("FATAL: INVERTER_TOKEN secret is not configured in GitHub.")
        sys.exit(1)

    if action not in URL_CONFIG:
        logger.error(f"Invalid action '{action}'. Must be one of {list(URL_CONFIG.keys())}")
        sys.exit(1)

    config = URL_CONFIG[action]
    url = config['url'].format(token=INVERTER_TOKEN)
    description = config['description']

    logger.info(f"Executing job: {description}")

    try:
        headers = {"User-Agent": "github-actions-inverter/1.0"}
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError:
            logger.error("❌ ERROR: Response was not JSON.")
            logger.info(f"Raw response: {response.text[:500]}")
            sys.exit(1)

        err = data.get("err")
        desc = data.get("desc")
        logger.info(f"API result: err={err}, desc={desc}")

        # For read-status, print mode if available
        if action == "read-status":
            d = data.get("data")
            mode_val = None
            if isinstance(d, dict):
                mode_val = d.get("value", d.get("los_output_source_priority"))
            elif isinstance(d, list) and d:
                item0 = d[0]
                if isinstance(item0, dict):
                    mode_val = item0.get("value")

            if mode_val is not None:
                logger.info(f"Current output priority mode: {mode_val} -> {_pretty_mode(mode_val)}")
            else:
                logger.info("Current output priority mode: (not present in payload)")

        if err == 0:
            logger.info(f"✅ SUCCESS: {description}")
        else:
            logger.warning(f"⚠️ WARNING: API returned an error: {desc or 'No description'}")

        logger.info(f"Full API Response (truncated): {str(data)[:1200]}")

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
