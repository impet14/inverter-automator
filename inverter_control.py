# =================================================================================
#  Inverter Control Script for GitHub Actions (reliable, retrying)
# =================================================================================
#  - Retries control commands (set-solar, set-sbu) up to MAX_RETRIES (default 5)
#    with exponential backoff + jitter.
#  - Uses a requests.Session with a small urllib3 Retry policy for transport-level
#    resilience.
#  - Emits GitHub Actions error annotations (::error::) when a command ultimately fails,
#    so the failure is visible in the Actions UI.
# =================================================================================
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

# --- Configuration from GitHub Secrets / Env ---
INVERTER_TOKEN = os.environ.get('INVERTER_TOKEN')

# Adjustable runtime knobs (can be set from workflow env):
MAX_RETRIES = int(os.environ.get("INVERTER_MAX_RETRIES", "5"))        # attempts
BACKOFF_FACTOR = float(os.environ.get("INVERTER_BACKOFF_FACTOR", "2.0"))
REQUEST_TIMEOUT = int(os.environ.get("INVERTER_REQUEST_TIMEOUT", "45"))  # seconds
MAX_BACKOFF_SLEEP = int(os.environ.get("INVERTER_MAX_BACKOFF_SLEEP", "60"))

# Device identifiers (constants -- keep as in your repo)
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"

BASE_URL = "http://android.shinemonitor.com/public/"
CLIENT_SUFFIX = "&source=1&_app_client_=android&_app_id_=com.eybond.smartclient.ess&_app_version_=3.40.1.0"

URL_CONFIG = {
    'read-status': {
        'description': "Read current status",
        'url': (
            f"{BASE_URL}?sign=36a7d1425932c48f9426b80eae61b3f4cacd7872&salt=1761121759161"
            f"&token={{token}}&action=queryDeviceCtrlValue&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    },
    'set-solar': {
        'description': "Set output priority to SOLAR (val=1)",
        'url': (
            f"{BASE_URL}?sign=2faa45e70bbeb5e1516680033de9ce6e3f184bed&salt=1761121932506"
            f"&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=1&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    },
    'set-sbu': {
        'description': "Set output priority to SBU (val=2)",
        'url': (
            f"{BASE_URL}?sign=713f0bbb9e506796976db45d247219a91a91d766&salt=1761121854528"
            f"&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}"
            f"&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=2&i18n=en_US"
            f"{CLIENT_SUFFIX}"
        )
    }
}

# --- Helpers ---


def github_action_error_annotation(message: str):
    """Emit GitHub Actions workflow command to create an error annotation."""
    # This prints a special string that GitHub Actions will convert to an annotation.
    print(f"::error::{message}")


def make_session():
    """
    Create a requests.Session with a conservative urllib3 Retry policy for
    basic transport-level resilience for idempotent methods (GET).
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        backoff_factor=0.5,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _sleep_with_backoff(attempt: int):
    """
    Sleep using exponential backoff with jitter.
    attempt: 1-indexed attempt number (first retry attempt is 1)
    """
    base = BACKOFF_FACTOR ** (attempt - 1)
    jitter = random.uniform(0.5, 1.5)
    sleep_time = min(base * jitter, MAX_BACKOFF_SLEEP)
    logger.info(f"Waiting {sleep_time:.1f}s before retrying (attempt {attempt + 1}/{MAX_RETRIES})...")
    time.sleep(sleep_time)


def call_api(action: str):
    """
    High-level API call:
    - For set-solar and set-sbu: retry up to MAX_RETRIES with backoff/jitter.
    - For read-status: single attempt (preserves previous behavior) but improved logging.
    On final failure of control commands, emit a GitHub Actions error annotation and exit non-zero.
    """
    if not INVERTER_TOKEN:
        logger.critical("FATAL ERROR: The INVERTER_TOKEN secret is not configured in GitHub.")
        github_action_error_annotation("FATAL: INVERTER_TOKEN secret is not set.")
        sys.exit(1)

    if action not in URL_CONFIG:
        logger.error(f"Invalid action specified: '{action}'. Must be one of {list(URL_CONFIG.keys())}")
        github_action_error_annotation(f"Invalid action specified: '{action}'")
        sys.exit(1)

    config = URL_CONFIG[action]
    url = config['url'].format(token=INVERTER_TOKEN)
    description = config['description']

    logger.info(f"Executing job: {description}")
    logger.debug(f"Calling URL: {url}")

    session = make_session()

    # Control commands: retry loop
    if action in ('set-solar', 'set-sbu'):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"Attempt {attempt}/{MAX_RETRIES} for '{description}'")
                response = session.get(url, timeout=REQUEST_TIMEOUT)
                # Try to grab response text for debugging
                data_text = response.text if response is not None else "<no response body>"

                if not response.ok:
                    logger.warning(f"HTTP {response.status_code} on attempt {attempt}. Body: {data_text[:400]}")
                    if attempt == MAX_RETRIES:
                        msg = f"{description} failed after {MAX_RETRIES} attempts: HTTP {response.status_code}"
                        logger.error(msg)
                        github_action_error_annotation(msg + f" — Response: {data_text[:400]}")
                        sys.exit(1)
                    else:
                        _sleep_with_backoff(attempt)
                        continue

                # Parse JSON body
                try:
                    data = response.json()
                except ValueError:
                    logger.warning(f"Non-JSON response on attempt {attempt}. Raw content: {data_text[:400]}")
                    if attempt == MAX_RETRIES:
                        msg = f"{description} failed after {MAX_RETRIES} attempts: non-JSON response"
                        logger.error(msg)
                        github_action_error_annotation(msg + f" — Raw: {data_text[:400]}")
                        sys.exit(1)
                    else:
                        _sleep_with_backoff(attempt)
                        continue

                # API-level status
                if data.get("err") == 0:
                    logger.info(f"✅ SUCCESS: API call for '{description}' succeeded on attempt {attempt}.")
                    logger.debug(f"Full API Response: {data}")
                    return  # success
                else:
                    server_desc = data.get('desc') or str(data)
                    logger.warning(f"Server reported error on attempt {attempt}: {server_desc}")
                    if attempt == MAX_RETRIES:
                        msg = f"{description} failed after {MAX_RETRIES} attempts: server error: {server_desc}"
                        logger.error(msg)
                        github_action_error_annotation(msg)
                        logger.error(f"    Full API Response: {data}")
                        sys.exit(1)
                    else:
                        _sleep_with_backoff(attempt)
                        continue

            except requests.exceptions.RequestException as exc:
                logger.warning(f"Network error on attempt {attempt} for '{description}': {exc}")
                if attempt == MAX_RETRIES:
                    msg = f"{description} failed after {MAX_RETRIES} attempts: network error: {exc}"
                    logger.error(msg)
                    github_action_error_annotation(msg)
                    sys.exit(1)
                else:
                    _sleep_with_backoff(attempt)
                    continue

    # read-status: single attempt, preserve behavior but add annotations for visibility
    else:
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError:
                logger.error(f"❌ ERROR: Received non-JSON response from API. Raw content: {response.text[:200]}...")
                github_action_error_annotation("read-status: non-JSON response from API")
                sys.exit(1)

            if data.get("err") == 0:
                logger.info(f"✅ SUCCESS: API call for '{description}' was successful.")
            else:
                logger.warning(f"⚠️ WARNING: API call succeeded, but server reported an error: {data.get('desc', 'No description')}")
                github_action_error_annotation(f"read-status: server reported error: {data.get('desc', '')}")
                sys.exit(1)

            logger.info(f"    Full API Response: {data}")

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ ERROR: Network request failed for '{description}'. Details: {e}")
            github_action_error_annotation(f"read-status: network request failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inverter_control.py <action>")
        print("Available actions: read-status, set-solar, set-sbu")
        sys.exit(1)

    action_to_run = sys.argv[1]
    call_api(action_to_run)
