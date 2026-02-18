import os
import sys
import logging
import time
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
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

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

URL_CONFIG = {
    'read-status': {
        'description': "Read current status",
        'url': f"{BASE_URL}?sign=5e19204eda29cb35c95e9f661d9887a70baa487c&salt=1771039412410&token={{token}}&action=queryDeviceCtrlValue&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&i18n=en_US{CLIENT_SUFFIX}"
    },
    'set-solar': {
        'description': "Set priority to SOLAR",
        'url': f"{BASE_URL}?sign=f641c3f877283488a6e0a9c4e2fd52ca7fe268cd&salt=1771039559330&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=1&i18n=en_US{CLIENT_SUFFIX}"
    },
    'set-sbu': {
        'description': "Set priority to SBU",
        'url': f"{BASE_URL}?sign=8e31da38ae8b3878bc5bbd552b76616f1111d25d&salt=1771039708297&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=2&i18n=en_US{CLIENT_SUFFIX}"
    }
}

def send_line_message(message: str):
    """ส่งข้อความแจ้งเตือนเข้า LINE Messaging API"""
    if not LINE_TOKEN or not LINE_USER_ID:
        logger.warning("LINE credentials missing. Skipping notification.")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info("LINE notification sent.")
        else:
            logger.error(f"LINE API Error: {res.text}")
    except Exception as e:
        logger.error(f"Failed to send LINE message: {e}")

def make_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; Android 16; ...)',
        'X-Requested-With': 'com.eybond.smartclient.ess',
        'Accept': 'application/json, text/plain, */*'
    })
    retry_strategy = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retry_strategy))
    return session

def call_api(action: str):
    if not INVERTER_TOKEN:
        logger.error("INVERTER_TOKEN missing.")
        sys.exit(1)

    config = URL_CONFIG.get(action)
    url = config['url'].format(token=INVERTER_TOKEN)
    description = config['description']
    session = make_session()
    attempts = MAX_RETRIES if action.startswith('set-') else 1

    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            data = response.json()
            
            if response.ok and data.get("err") == 0:
                msg = f"✅ SUCCESS: {description}\nResponse: {data.get('desc', 'OK')}"
                logger.info(msg)
                # ส่ง LINE เมื่อสำเร็จ (เฉพาะคำสั่ง set-)
                if action.startswith('set-'):
                    send_line_message(msg)
                return
            else:
                error_msg = data.get('desc', 'Unknown Error')
                logger.warning(f"Attempt {attempt} failed: {error_msg}")
                if attempt == attempts:
                    send_line_message(f"❌ FAILED: {description}\nError: {error_msg}")
                    sys.exit(1)
                time.sleep(min(BACKOFF_FACTOR ** attempt, MAX_BACKOFF_SLEEP))

        except Exception as e:
            if attempt == attempts:
                send_line_message(f"🚨 CRITICAL ERROR: {description}\nException: {str(e)}")
                sys.exit(1)
            time.sleep(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    call_api(sys.argv[1])
    