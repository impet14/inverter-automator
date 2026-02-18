import os
import sys
import logging
import time
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("inverter-debug")

# --- Configuration ---
INVERTER_TOKEN = os.environ.get('INVERTER_TOKEN')
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

MAX_RETRIES = int(os.environ.get("INVERTER_MAX_RETRIES", "3")) # ลด Retry ลงเล็กน้อยเพื่อความเร็ว
REQUEST_TIMEOUT = 45

# Device Constants
PN = "Q0029389993714"
SN = "Q002938999371409AD05"
DEVCODE = "2477"
DEVADDR = "5"

BASE_URL = "http://android.shinemonitor.com/public/"
CLIENT_SUFFIX = "&source=1&_app_client_=android&_app_id_=com.eybond.smartclient.ess&_app_version_=3.43.0.1"

URL_CONFIG = {
    'read-status': {
        'description': "Read Output Priority Status",
        'url': f"{BASE_URL}?sign=5e19204eda29cb35c95e9f661d9887a70baa487c&salt=1771039412410&token={{token}}&action=queryDeviceCtrlValue&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&i18n=en_US{CLIENT_SUFFIX}"
    },
    'set-solar': {
        'description': "Set priority to SOLAR (val=1)",
        'url': f"{BASE_URL}?sign=f641c3f877283488a6e0a9c4e2fd52ca7fe268cd&salt=1771039559330&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=1&i18n=en_US{CLIENT_SUFFIX}"
    },
    'set-sbu': {
        'description': "Set priority to SBU (val=2)",
        'url': f"{BASE_URL}?sign=8e31da38ae8b3878bc5bbd552b76616f1111d25d&salt=1771039708297&token={{token}}&action=ctrlDevice&sn={SN}&pn={PN}&devcode={DEVCODE}&devaddr={DEVADDR}&id=los_output_source_priority&val=2&i18n=en_US{CLIENT_SUFFIX}"
    }
}

def send_line_debug(action_desc, status_code, response_data, is_success=True):
    """ส่งข้อความ Debug แบบละเอียดเข้า LINE"""
    if not LINE_TOKEN or not LINE_USER_ID:
        return

    icon = "✅" if is_success else "❌"
    
    # แปลง JSON response ให้เป็นข้อความที่อ่านง่าย
    try:
        formatted_json = json.dumps(response_data, indent=2, ensure_ascii=False)
    except:
        formatted_json = str(response_data)

    message = (
        f"{icon} Inverter Task: {action_desc}\n"
        f"----------------------\n"
        f"HTTP Status: {status_code}\n"
        f"Body:\n{formatted_json}"
    )

    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
    
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"LINE Notification Failed: {e}")

def make_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; Android 16; 2312FPCA6G Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.132 Mobile Safari/537.36',
        'X-Requested-With': 'com.eybond.smartclient.ess'
    })
    return session

def call_api(action: str):
    if not INVERTER_TOKEN:
        logger.error("Error: INVERTER_TOKEN not found.")
        return

    config = URL_CONFIG.get(action)
    url = config['url'].format(token=INVERTER_TOKEN)
    description = config['description']
    session = make_session()
    
    attempts = MAX_RETRIES if action.startswith('set-') else 1

    for attempt in range(1, attempts + 1):
        try:
            logger.info(f"Executing: {description} (Attempt {attempt})")
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            
            # พยายามดึง JSON ถ้าไม่ได้ให้ใช้ text ธรรมดา
            try:
                data = response.json()
            except:
                data = {"raw_text": response.text}

            # ตรวจสอบเงื่อนไขสำเร็จ (err == 0)
            if response.ok and data.get("err") == 0:
                logger.info(f"API Success: {data}")
                send_line_debug(description, response.status_code, data, is_success=True)
                return
            else:
                logger.warning(f"API Failure: {data}")
                if attempt == attempts:
                    send_line_debug(description, response.status_code, data, is_success=False)
                    sys.exit(1)
                time.sleep(5)

        except Exception as e:
            error_info = {"exception": str(e)}
            logger.error(f"Request Exception: {e}")
            if attempt == attempts:
                send_line_debug(description, "EXCEPTION", error_info, is_success=False)
                sys.exit(1)
            time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("No action provided.")
        sys.exit(1)
    call_api(sys.argv[1])
