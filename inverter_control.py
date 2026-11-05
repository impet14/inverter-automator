import os
import sys
import logging
import time
import json
from datetime import datetime
import pytz
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

MAX_RETRIES = int(os.environ.get("INVERTER_MAX_RETRIES", "3"))
REQUEST_TIMEOUT = 45

# Device Constants (Configurable via environment variables with defaults)
PN = os.environ.get('INVERTER_PN', "Q0029389993714")
SN = os.environ.get('INVERTER_SN', "Q002938999371409AD05")
DEVCODE = os.environ.get('INVERTER_DEVCODE', "2477")
DEVADDR = os.environ.get('INVERTER_DEVADDR', "5")

TIMEZONE_DEFAULT = os.environ.get("TIMEZONE", "Asia/Bangkok")
BILLING_SKIP_DAYS_DEFAULT = os.environ.get("BILLING_SKIP_DAYS", "24,25")

BASE_URL = "http://android.shinemonitor.com/public/"
CLIENT_SUFFIX = "&source=1&_app_client_=android&_app_id_=com.eybond.smartclient.ess&_app_version_=3.43.0.1"

def get_url_config():
    """Generates URL configuration using current device constants."""
    pn = os.environ.get('INVERTER_PN', PN)
    sn = os.environ.get('INVERTER_SN', SN)
    devcode = os.environ.get('INVERTER_DEVCODE', DEVCODE)
    devaddr = os.environ.get('INVERTER_DEVADDR', DEVADDR)
    
    return {
        'read-status': {
            'description': "Read Output Priority Status",
            'url': f"{BASE_URL}?sign=5e19204eda29cb35c95e9f661d9887a70baa487c&salt=1771039412410&token={{token}}&action=queryDeviceCtrlValue&sn={sn}&pn={pn}&devcode={devcode}&devaddr={devaddr}&id=los_output_source_priority&i18n=en_US{CLIENT_SUFFIX}"
        },
        'set-solar': {
            'description': "Set priority to SOLAR (val=1)",
            'url': f"{BASE_URL}?sign=f641c3f877283488a6e0a9c4e2fd52ca7fe268cd&salt=1771039559330&token={{token}}&action=ctrlDevice&sn={sn}&pn={pn}&devcode={devcode}&devaddr={devaddr}&id=los_output_source_priority&val=1&i18n=en_US{CLIENT_SUFFIX}"
        },
        'set-sbu': {
            'description': "Set priority to SBU (val=2)",
            'url': f"{BASE_URL}?sign=8e31da38ae8b3878bc5bbd552b76616f1111d25d&salt=1771039708297&token={{token}}&action=ctrlDevice&sn={sn}&pn={pn}&devcode={devcode}&devaddr={devaddr}&id=los_output_source_priority&val=2&i18n=en_US{CLIENT_SUFFIX}"
        }
    }

URL_CONFIG = get_url_config()

def get_billing_skip_days():
    raw = os.environ.get("BILLING_SKIP_DAYS", BILLING_SKIP_DAYS_DEFAULT)
    days = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            days.append(int(part))
    return days

def is_billing_skip_day(tz_name=None):
    """Checks if today is within billing skip dates (default 24th and 25th in Asia/Bangkok)."""
    tz_name = tz_name or os.environ.get("TIMEZONE", TIMEZONE_DEFAULT)
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.UTC
    now = datetime.now(tz)
    skip_days = get_billing_skip_days()
    return (now.day in skip_days, now.day)

def parse_priority_mode(data):
    """Extracts human-readable priority mode from ShineMonitor JSON response."""
    if not isinstance(data, dict):
        return None
    dat = data.get("dat")
    val = None
    if isinstance(dat, list) and len(dat) > 0 and isinstance(dat[0], dict):
        val = str(dat[0].get("val", ""))
    elif isinstance(dat, dict):
        val = str(dat.get("val", ""))

    modes = {
        "1": {"val": 1, "name": "SOLAR", "description": "Solar First", "icon": "☀️"},
        "2": {"val": 2, "name": "SBU", "description": "Solar-Battery-Utility", "icon": "🔋"},
        "0": {"val": 0, "name": "UTILITY", "description": "Utility First", "icon": "🔌"}
    }
    if val in modes:
        return modes[val]
    elif val:
        return {"val": val, "name": f"Mode {val}", "description": f"Output Priority {val}", "icon": "⚡"}
    return None

def send_line_debug(action_desc, status_code, response_data, is_success=True):
    """Sends detailed debug / notification message to LINE."""
    line_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', LINE_TOKEN)
    line_user_id = os.environ.get('LINE_USER_ID', LINE_USER_ID)
    
    if not line_token or not line_user_id:
        return

    icon = "✅" if is_success else "❌"
    
    try:
        formatted_json = json.dumps(response_data, indent=2, ensure_ascii=False)
    except Exception:
        formatted_json = str(response_data)

    message = (
        f"{icon} Inverter Task: {action_desc}\n"
        f"----------------------\n"
        f"HTTP Status: {status_code}\n"
        f"Body:\n{formatted_json}"
    )

    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {line_token}"}
    payload = {"to": line_user_id, "messages": [{"type": "text", "text": message}]}
    
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

def send_credentials_to_line():
    """Sends current environment credentials to LINE for recovery."""
    inverter_token = os.environ.get('INVERTER_TOKEN', '')
    line_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
    line_user_id = os.environ.get('LINE_USER_ID', '')

    if not line_token or not line_user_id:
        logger.error("LINE credentials missing from environment.")
        return

    message = (
        "🔐 [Inverter Automator] Recovered Secrets:\n\n"
        f"INVERTER_TOKEN:\n{inverter_token}\n\n"
        f"LINE_CHANNEL_ACCESS_TOKEN:\n{line_token}\n\n"
        f"LINE_USER_ID:\n{line_user_id}"
    )

    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {line_token}"}
    payload = {"to": line_user_id, "messages": [{"type": "text", "text": message}]}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        logger.info(f"Sent recovered secrets to LINE: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"Failed to send credentials to LINE: {e}")

def call_api(action: str, exit_on_failure: bool = False, force: bool = False) -> dict:
    """Executes inverter API call with retries and optional date check."""
    if action == 'recover-tokens':
        send_credentials_to_line()
        return {"success": True, "action": action, "message": "Credentials sent to your LINE chat"}

    inverter_token = os.environ.get('INVERTER_TOKEN', INVERTER_TOKEN)
    if not inverter_token:
        err_msg = "Error: INVERTER_TOKEN not found."
        logger.error(err_msg)
        if exit_on_failure:
            sys.exit(1)
        return {"success": False, "error": err_msg, "action": action}

    url_configs = get_url_config()
    if action not in url_configs:
        err_msg = f"Error: Unknown action '{action}'"
        logger.error(err_msg)
        if exit_on_failure:
            sys.exit(1)
        return {"success": False, "error": err_msg, "action": action}

    # Date Gate Check for set-solar (skips on billing adjustment days unless forced)
    if action == 'set-solar' and not force:
        is_skip, current_day = is_billing_skip_day()
        if is_skip:
            skip_msg = f"Skipped scheduled Solar task for billing period date: {current_day}"
            logger.info(skip_msg)
            return {
                "success": True,
                "skipped": True,
                "reason": skip_msg,
                "day": current_day,
                "action": action
            }

    config = url_configs.get(action)
    url = config['url'].format(token=inverter_token)
    description = config['description']
    session = make_session()
    
    attempts = MAX_RETRIES if action.startswith('set-') else 1

    for attempt in range(1, attempts + 1):
        try:
            logger.info(f"Executing: {description} (Attempt {attempt}/{attempts})")
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            
            try:
                data = response.json()
            except Exception:
                data = {"raw_text": response.text}

            if response.ok and data.get("err") == 0:
                logger.info(f"API Success: {data}")
                if action != 'read-status':
                    send_line_debug(description, response.status_code, data, is_success=True)
                
                parsed = parse_priority_mode(data) if action == 'read-status' else None
                return {
                    "success": True,
                    "skipped": False,
                    "action": action,
                    "description": description,
                    "status_code": response.status_code,
                    "data": data,
                    "parsed": parsed
                }
            else:
                logger.warning(f"API Failure: {data}")
                if attempt == attempts:
                    if action != 'read-status':
                        send_line_debug(description, response.status_code, data, is_success=False)
                    if exit_on_failure:
                        sys.exit(1)
                    return {
                        "success": False,
                        "skipped": False,
                        "action": action,
                        "description": description,
                        "status_code": response.status_code,
                        "data": data
                    }
                time.sleep(5)

        except Exception as e:
            error_info = {"exception": str(e)}
            logger.error(f"Request Exception: {e}")
            if attempt == attempts:
                if action != 'read-status':
                    send_line_debug(description, "EXCEPTION", error_info, is_success=False)
                if exit_on_failure:
                    sys.exit(1)
                return {
                    "success": False,
                    "skipped": False,
                    "action": action,
                    "description": description,
                    "status_code": "EXCEPTION",
                    "error": str(e),
                    "data": error_info
                }
            time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("No action provided. Usage: python inverter_control.py <read-status|set-solar|set-sbu> [--force]")
        sys.exit(1)
    
    action_arg = sys.argv[1]
    force_arg = "--force" in sys.argv or "-f" in sys.argv
    call_api(action_arg, exit_on_failure=True, force=force_arg)
