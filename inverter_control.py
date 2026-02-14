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

# --- Configuration ---
INVERTER_TOKEN = os.environ.get('INVERTER_TOKEN')
MAX_RETRIES = int(os.environ.get("INVERTER_MAX_RETRIES", "5"))
BACKOFF_FACTOR = float(os.environ.get("INVERTER_BACKOFF_FACTOR", "2.0"))
REQUEST_TIMEOUT = int(os.environ.get("INVERTER_REQUEST_TIMEOUT", "45"))
MAX_BACKOFF_SLEEP = int(os.environ.get("INVERTER_MAX_BACKOFF_SLEEP", "60"))

# Device identifiers
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"

BASE_URL = "http://android.shinemonitor.com/public/"
# Updated version to 3.43.0.1
CLIENT_SUFFIX = "&source=1&_app_client_=android&_app_id_=com.eybond.smartclient.ess&_app_version_=3.43.0.1"

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

def github_action_error_annotation(message: str):
    print(f"::error::{message}")

def make_session():
    session = requests.Session()
    # Updated Headers to match the new request
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
        backoff_factor=0.5,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def _sleep_with_backoff(attempt: int):
    base = BACKOFF_FACTOR ** (attempt - 1)
    jitter = random.uniform(0.5, 1.5)
    sleep_time = min(base * jitter, MAX_BACKOFF_SLEEP)
    logger.info(f"Waiting {sleep_time:.1f}s before retrying (attempt {attempt + 1}/{MAX_RETRIES})...")
    time.sleep(sleep_time)

def call_api(action: str):
    if not INVERTER_TOKEN:
        logger.critical("FATAL ERROR: INVERTER_TOKEN secret is not set.")
        github_action_error_annotation("FATAL: INVERTER_TOKEN secret is not set.")
        sys.exit(1)

    if action not in URL_CONFIG:
        logger.error(f"Invalid action: '{action}'")
        sys.exit(1)

    config = URL_CONFIG[action]
    url = config['url'].format(token=INVERTER_TOKEN)
    description = config['description']

    logger.info(f"Executing: {description}")
    session = make_session()

    # Retry logic for control, single attempt for status
    attempts = MAX_RETRIES if action in ('set-solar', 'set-sbu') else 1

    for attempt in range(1, attempts + 1):
        try:
            logger.info(f"Attempt {attempt}/{attempts}")
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            data_text = response.text

            if not response.ok:
                logger.warning(f"HTTP {response.status_code}. Body: {data_text[:200]}")
                if attempt == attempts:
                    github_action_error_annotation(f"{description} failed: HTTP {response.status_code}")
                    sys.exit(1)
                _sleep_with_backoff(attempt)
                continue

            try:
                data = response.json()
            except ValueError:
                logger.warning(f"Non-JSON response. Raw: {data_text[:200]}")
                if attempt == attempts:
                    github_action_error_annotation(f"{description} failed: Non-JSON response")
                    sys.exit(1)
                _sleep_with_backoff(attempt)
                continue

            if data.get("err") == 0:
                logger.info(f"✅ SUCCESS: {description}")
                logger.info(f"Response: {data}")
                return
            else:
                server_desc = data.get('desc') or str(data)
                logger.warning(f"Server Error: {server_desc}")
                if attempt == attempts:
                    github_action_error_annotation(f"{description} failed: {server_desc}")
                    sys.exit(1)
                _sleep_with_backoff(attempt)

        except requests.exceptions.RequestException as exc:
            logger.warning(f"Network error: {exc}")
            if attempt == attempts:
                github_action_error_annotation(f"Network error: {exc}")
                sys.exit(1)
            _sleep_with_backoff(attempt)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(1)
    call_api(sys.argv[1])
    
