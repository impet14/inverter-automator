import os
import sys
import logging
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("inverter-script")

# --- Configuration from Environment ---
INVERTER_TOKEN = os.environ.get('INVERTER_TOKEN')
MAX_RETRIES = int(os.environ.get("INVERTER_MAX_RETRIES", "5"))
BACKOFF_FACTOR = float(os.environ.get("INVERTER_BACKOFF_FACTOR", "2.0"))
REQUEST_TIMEOUT = int(os.environ.get("INVERTER_REQUEST_TIMEOUT", "45"))
MAX_BACKOFF_SLEEP = int(os.environ.get("INVERTER_MAX_BACKOFF_SLEEP", "60"))

# Device Constants
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"

BASE_URL = "http://android.shinemonitor.com/public/"
CLIENT_SUFFIX = "&source=1&_app_client_=android&_app_id_=com.eybond.smartclient.ess&_app_version_=3.43.0.1"

# API Endpoints with updated Signatures and Salts
URL_CONFIG = {
    'read-status': {
        'description': "Read current status",
        'url': (
            f"{BASE_URL}?sign=5e19204eda29cb35c95e9f661d9887a70baa487c&salt=1771039412410"
            f"&token={{token}}&action=queryDeviceCtrlValue&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    },
    'set-solar': {
        'description': "Set output priority to SOLAR (val=1)",
        'url': (
            f"{BASE_URL}?sign=f641c3f877283488a6e0a9c4e2fd52ca7fe268cd&salt=1771039559330"
            f"&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=1&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    },
    'set-sbu': {
        'description': "Set output priority to SBU (val=2)",
        'url': (
            f"{BASE_URL}?sign=8e31da38ae8b3878bc5bbd552b76616f1111d25d&salt=1771039708297"
            f"&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=2&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    }
}

def make_session():
    """Create a session with mobile headers and retry logic."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 2312FPCA6G Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.132 Mobile Safari/537.36',
        'X-Requested-With': 'com.eybond.smartclient.ess',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9'
    })
    
    retry_strategy = Retry(
        total=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        backoff_factor=0.5
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def call_api(action: str):
    if not INVERTER_TOKEN:
        logger.error("::error::INVERTER_TOKEN not found in environment.")
        sys.exit(1)

    config = URL_CONFIG.get(action)
    url = config['url'].format(token=INVERTER_TOKEN)
    description = config['description']

    session = make_session()
    # Control commands use retries; read-status uses 1 attempt
    attempts = MAX_RETRIES if action.startswith('set-') else 1

    for attempt in range(1, attempts + 1):
        try:
            logger.info(f"Task: {description} (Attempt {attempt}/{attempts})")
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            
            if not response.ok:
                logger.warning(f"HTTP Error {response.status_code}")
                if attempt == attempts: sys.exit(1)
                time.sleep(min(BACKOFF_FACTOR ** attempt, MAX_BACKOFF_SLEEP))
                continue

            data = response.json()
            if data.get("err") == 0:
                logger.info(f"✅ SUCCESS: {description}")
                logger.info(f"Response Body: {data}")
                return
            else:
                logger.warning(f"API Error: {data.get('desc')}")
                if attempt == attempts: sys.exit(1)
                time.sleep(min(BACKOFF_FACTOR ** attempt, MAX_BACKOFF_SLEEP))

        except Exception as e:
            logger.error(f"Request failed: {e}")
            if attempt == attempts: sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    call_api(sys.argv[1])