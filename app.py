import os
import sys
import logging
import time
from datetime import datetime
from collections import deque
import threading
import pytz
from flask import Flask, jsonify, request, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

import inverter_control

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("inverter-automator")

# --- Configuration ---
PORT = int(os.environ.get("PORT", "10000"))
TIMEZONE_NAME = os.environ.get("TIMEZONE", "Asia/Bangkok")
try:
    TIMEZONE = pytz.timezone(TIMEZONE_NAME)
except Exception:
    TIMEZONE = pytz.timezone("Asia/Bangkok")
    TIMEZONE_NAME = "Asia/Bangkok"

# Schedules (Configurable via env vars, with defaults matching UTC+7 times)
# 04:00, 04:10, 04:20 Bangkok time = 21:00, 21:10, 21:20 UTC
SOLAR_HOURS = os.environ.get("SOLAR_CRON_HOUR", "4")
SOLAR_MINUTES = os.environ.get("SOLAR_CRON_MINUTE", "0,10,20")

# 18:30 Bangkok time = 11:30 UTC
SBU_HOURS = os.environ.get("SBU_CRON_HOUR", "18")
SBU_MINUTES = os.environ.get("SBU_CRON_MINUTE", "30")

# Status check every 4 hours
STATUS_HOURS = os.environ.get("STATUS_CRON_HOUR", "*/4")
STATUS_MINUTES = os.environ.get("STATUS_CRON_MINUTE", "0")

API_KEY = os.environ.get("API_KEY", "").strip()

# --- Application State ---
app = Flask(__name__)

SERVICE_START_TIME = datetime.now(pytz.UTC)
ping_counter = 0
last_ping_time = None
latest_inverter_status = {
    "mode": "Unknown",
    "description": "Not yet checked",
    "val": None,
    "icon": "⚡",
    "checked_at": None
}
activity_logs = deque(maxlen=60)
state_lock = threading.Lock()

def get_uptime_string():
    delta = datetime.now(pytz.UTC) - SERVICE_START_TIME
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)

def record_activity(action, trigger_type, result):
    with state_lock:
        now_local = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        is_skipped = result.get("skipped", False)
        is_success = result.get("success", False)
        
        if is_skipped:
            status = "skipped"
            message = result.get("reason", "Skipped by rule")
        elif is_success:
            status = "success"
            message = f"HTTP {result.get('status_code', 200)} OK"
            if result.get("parsed"):
                p = result["parsed"]
                message += f" ({p.get('name', '')}: {p.get('description', '')})"
        else:
            status = "failure"
            message = result.get("error") or str(result.get("data", "Failed"))
            
        activity_logs.appendleft({
            "timestamp": now_local,
            "action": action,
            "trigger": trigger_type,
            "status": status,
            "message": str(message)[:180],
            "raw": result
        })

def update_inverter_status_from_result(result):
    global latest_inverter_status
    if not result:
        return
    parsed = result.get("parsed")
    if parsed:
        with state_lock:
            latest_inverter_status = {
                "mode": parsed.get("name", "Unknown"),
                "description": parsed.get("description", "Unknown"),
                "val": parsed.get("val"),
                "icon": parsed.get("icon", "⚡"),
                "checked_at": datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            }

# --- Scheduled Task Callbacks ---
def scheduled_solar_task():
    logger.info("Executing scheduled SOLAR task")
    result = inverter_control.call_api('set-solar', exit_on_failure=False, force=False)
    record_activity('set-solar', 'scheduled', result)

def scheduled_sbu_task():
    logger.info("Executing scheduled SBU task")
    result = inverter_control.call_api('set-sbu', exit_on_failure=False, force=False)
    record_activity('set-sbu', 'scheduled', result)

def scheduled_status_task():
    logger.info("Executing scheduled STATUS check task")
    result = inverter_control.call_api('read-status', exit_on_failure=False, force=False)
    record_activity('read-status', 'scheduled', result)
    update_inverter_status_from_result(result)

# --- Scheduler Initialization ---
scheduler = BackgroundScheduler(timezone=TIMEZONE, misfire_grace_time=300)

scheduler.add_job(
    scheduled_solar_task,
    'cron',
    hour=SOLAR_HOURS,
    minute=SOLAR_MINUTES,
    id='job_set_solar',
    name='Solar Priority Switch'
)

scheduler.add_job(
    scheduled_sbu_task,
    'cron',
    hour=SBU_HOURS,
    minute=SBU_MINUTES,
    id='job_set_sbu',
    name='SBU Priority Switch'
)

scheduler.add_job(
    scheduled_status_task,
    'cron',
    hour=STATUS_HOURS,
    minute=STATUS_MINUTES,
    id='job_read_status',
    name='Output Status Query'
)

if not scheduler.running:
    scheduler.start()
    logger.info(f"APScheduler started in timezone: {TIMEZONE_NAME}")
    for j in scheduler.get_jobs():
        logger.info(f" - Configured Job '{j.id}': {j.name} (Next run: {j.next_run_time})")

# Run initial status check in background after 5s
def initial_status_check():
    time.sleep(5)
    logger.info("Running startup initial inverter status check...")
    res = inverter_control.call_api('read-status', exit_on_failure=False, force=True)
    record_activity('read-status', 'startup', res)
    update_inverter_status_from_result(res)

threading.Thread(target=initial_status_check, daemon=True).start()

# --- Helper Functions for Endpoints ---
def check_api_key():
    if not API_KEY:
        return True
    provided = request.headers.get("X-API-Key") or request.args.get("key") or request.form.get("key")
    return provided == API_KEY

def get_next_job_runs():
    runs = {}
    for j in scheduler.get_jobs():
        if j.next_run_time:
            local_time = j.next_run_time.astimezone(TIMEZONE)
            delta = j.next_run_time - datetime.now(TIMEZONE)
            total_sec = delta.total_seconds()
            if total_sec <= 0:
                time_until = "due now"
            else:
                mins = int(total_sec // 60)
                hrs, rem_mins = divmod(mins, 60)
                time_until = f"in {hrs}h {rem_mins}m" if hrs > 0 else f"in {rem_mins}m"
            runs[j.id] = {
                "name": j.name,
                "next_run": local_time.strftime("%Y-%m-%d %H:%M:%S"),
                "time_until": time_until
            }
        else:
            runs[j.id] = {"name": j.name, "next_run": "Paused", "time_until": ""}
    return runs

# --- Routes ---

@app.route('/health')
@app.route('/ping')
def health():
    """UptimeRobot Keep-Alive Endpoint."""
    global ping_counter, last_ping_time
    with state_lock:
        ping_counter += 1
        last_ping_time = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    now_local = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    return jsonify({
        "status": "healthy",
        "service": "inverter-automator",
        "alive_24_7": True,
        "uptime": get_uptime_string(),
        "pings_received": ping_counter,
        "last_ping": last_ping_time,
        "timezone": TIMEZONE_NAME,
        "current_time": now_local,
        "scheduler_active": scheduler.running
    }), 200

@app.route('/api/status')
def api_status():
    """Returns complete JSON status of the service and scheduler."""
    is_skip, current_day = inverter_control.is_billing_skip_day(TIMEZONE_NAME)
    now_local = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    now_utc = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    return jsonify({
        "service": "inverter-automator",
        "uptime": get_uptime_string(),
        "timezone": TIMEZONE_NAME,
        "current_time_local": now_local,
        "current_time_utc": now_utc,
        "pings_received": ping_counter,
        "last_ping": last_ping_time,
        "inverter_mode": latest_inverter_status,
        "billing_gate": {
            "current_day": current_day,
            "skip_days": inverter_control.get_billing_skip_days(),
            "skip_active": is_skip
        },
        "next_scheduled_runs": get_next_job_runs(),
        "scheduler_running": scheduler.running,
        "recent_activities": list(activity_logs)
    })

@app.route('/api/trigger', methods=['GET', 'POST'])
def api_trigger():
    """Manual trigger endpoint for inverter actions."""
    if not check_api_key():
        return jsonify({"success": False, "error": "Unauthorized: Invalid or missing API key"}), 401

    action = request.args.get("action") or request.form.get("action") or (request.json.get("action") if request.is_json else None)
    force = request.args.get("force", "false").lower() in ("true", "1") or (request.json.get("force") if request.is_json else False)

    if not action:
        return jsonify({"success": False, "error": "Missing 'action' parameter (read-status, set-solar, set-sbu)"}), 400

    if action not in ('read-status', 'set-solar', 'set-sbu'):
        return jsonify({"success": False, "error": f"Invalid action '{action}'. Must be read-status, set-solar, or set-sbu"}), 400

    result = inverter_control.call_api(action, exit_on_failure=False, force=force)
    record_activity(action, 'manual', result)
    
    if action == 'read-status':
        update_inverter_status_from_result(result)

    return jsonify(result)

@app.route('/api/logs')
def api_logs():
    """Returns recent activity logs."""
    return jsonify(list(activity_logs))

# --- Web Dashboard Template ---
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚡ Inverter Automator</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220%22%3E<text y=%2226%22 font-size=%2228%22>⚡</text></svg>">
    <style>
        :root {
            --bg: #0b0f19;
            --surface: #131b2e;
            --surface-hover: #1c2742;
            --border: #233152;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --solar: #f59e0b;
            --sbu: #10b981;
            --utility: #3b82f6;
            --danger: #ef4444;
            --card-glow: rgba(59, 130, 246, 0.08);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
        body { background-color: var(--bg); color: var(--text-primary); min-height: 100vh; padding: 24px 16px; }
        .container { max-width: 1040px; margin: 0 auto; }
        
        /* Header */
        header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }
        .brand { display: flex; align-items: center; gap: 12px; }
        .logo { font-size: 32px; background: linear-gradient(135deg, #fbbf24, #f59e0b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        h1 { font-size: 24px; font-weight: 700; }
        .subtitle { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
        .header-badges { display: flex; gap: 8px; flex-wrap: wrap; }
        .badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 9999px; font-size: 12px; font-weight: 600; }
        .badge-alive { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
        .badge-render { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
        .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background-color: #10b981; box-shadow: 0 0 10px #10b981; animation: pulse 2s infinite; }
        @keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.85); } 100% { opacity: 1; transform: scale(1); } }
        
        /* UptimeRobot Notice */
        .ping-banner { background: rgba(30, 41, 59, 0.6); border: 1px solid var(--border); border-radius: 12px; padding: 12px 18px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: var(--text-secondary); flex-wrap: wrap; gap: 10px; }
        .ping-banner strong { color: var(--text-primary); }
        
        /* Grid Layout */
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 20px; box-shadow: 0 4px 20px var(--card-glow); transition: transform 0.2s, border-color 0.2s; }
        .card:hover { transform: translateY(-2px); border-color: rgba(96, 165, 250, 0.4); }
        .card-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; }
        .card-value { font-size: 22px; font-weight: 700; color: var(--text-primary); margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
        .card-sub { font-size: 13px; color: var(--text-secondary); }
        
        /* Action Controls */
        .controls-card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 22px; margin-bottom: 24px; }
        .controls-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; }
        .controls-header h2 { font-size: 18px; font-weight: 600; }
        .btn-group { display: flex; flex-wrap: wrap; gap: 12px; }
        .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 20px; border-radius: 10px; font-size: 14px; font-weight: 600; border: none; cursor: pointer; transition: all 0.2s; text-decoration: none; }
        .btn-solar { background: linear-gradient(135deg, #f59e0b, #d97706); color: #fff; }
        .btn-solar:hover { filter: brightness(1.15); box-shadow: 0 0 15px rgba(245, 158, 11, 0.4); }
        .btn-sbu { background: linear-gradient(135deg, #10b981, #059669); color: #fff; }
        .btn-sbu:hover { filter: brightness(1.15); box-shadow: 0 0 15px rgba(16, 185, 129, 0.4); }
        .btn-status { background: var(--surface-hover); border: 1px solid var(--border); color: var(--text-primary); }
        .btn-status:hover { background: #273557; border-color: #3b82f6; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .force-checkbox-wrap { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); cursor: pointer; user-select: none; }
        .force-checkbox-wrap input { width: 16px; height: 16px; accent-color: var(--solar); cursor: pointer; }
        
        /* Feedback Toast */
        #feedback-toast { display: none; padding: 12px 18px; border-radius: 10px; margin-top: 16px; font-size: 13px; font-weight: 500; animation: fadeIn 0.3s; }
        .toast-success { background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #34d399; }
        .toast-failure { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #f87171; }
        .toast-skipped { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); color: #fbbf24; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }

        /* Activity Table */
        .logs-card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 22px; }
        .logs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
        .logs-header h2 { font-size: 18px; font-weight: 600; }
        .table-wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
        th { padding: 12px 14px; background: rgba(15, 23, 42, 0.6); color: var(--text-secondary); font-weight: 600; border-bottom: 1px solid var(--border); }
        td { padding: 12px 14px; border-bottom: 1px solid rgba(35, 49, 82, 0.4); color: var(--text-primary); }
        tr:hover td { background-color: var(--surface-hover); }
        .badge-status { padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
        .status-success { background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .status-failure { background: rgba(239, 68, 68, 0.2); color: #f87171; }
        .status-skipped { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
        .tag-trigger { padding: 2px 6px; border-radius: 4px; font-size: 11px; background: rgba(148, 163, 184, 0.15); color: #94a3b8; }
        
        footer { margin-top: 32px; text-align: center; font-size: 12px; color: var(--text-secondary); }
        footer a { color: #60a5fa; text-decoration: none; }
        footer a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <div class="brand">
                <div class="logo">⚡</div>
                <div>
                    <h1>Inverter Automator</h1>
                    <div class="subtitle">Autonomous Solar Inverter Controller • Render 24/7 Engine</div>
                </div>
            </div>
            <div class="header-badges">
                <span class="badge badge-alive"><div class="pulse-dot"></div> 24/7 Active</span>
                <span class="badge badge-render">Uptime: {{ uptime }}</span>
            </div>
        </header>

        <!-- Keep-Alive Banner -->
        <div class="ping-banner">
            <div>
                <strong>📡 UptimeRobot Keep-Alive:</strong> 
                <span>{{ ping_counter }} pings received</span> • 
                <span>Last ping: {{ last_ping or 'Waiting for first ping' }}</span>
            </div>
            <div>Timezone: <strong>{{ timezone_name }}</strong></div>
        </div>

        <!-- Metric Cards Grid -->
        <div class="grid">
            <!-- Inverter Status -->
            <div class="card">
                <div class="card-title">
                    <span>Inverter Output Mode</span>
                    <span>{{ inverter_mode.icon }}</span>
                </div>
                <div class="card-value">
                    {{ inverter_mode.mode }}
                </div>
                <div class="card-sub">
                    {{ inverter_mode.description }} • <span style="font-size:11px;">Checked: {{ inverter_mode.checked_at or 'Pending' }}</span>
                </div>
            </div>

            <!-- Next Solar Run -->
            <div class="card">
                <div class="card-title">
                    <span>☀️ Next Solar Switch</span>
                    <span>{{ solar_schedule_label }}</span>
                </div>
                <div class="card-value" style="color: var(--solar);">
                    {{ next_runs.get('job_set_solar', {}).get('next_run', 'Paused') }}
                </div>
                <div class="card-sub">
                    {{ next_runs.get('job_set_solar', {}).get('time_until', '') }}
                </div>
            </div>

            <!-- Next SBU Run -->
            <div class="card">
                <div class="card-title">
                    <span>🔋 Next SBU Switch</span>
                    <span>{{ sbu_schedule_label }}</span>
                </div>
                <div class="card-value" style="color: var(--sbu);">
                    {{ next_runs.get('job_set_sbu', {}).get('next_run', 'Paused') }}
                </div>
                <div class="card-sub">
                    {{ next_runs.get('job_set_sbu', {}).get('time_until', '') }}
                </div>
            </div>

            <!-- Billing Gate Status -->
            <div class="card">
                <div class="card-title">
                    <span>📅 Billing Gate (Days 24–25)</span>
                    <span>Day {{ billing_day }}</span>
                </div>
                <div class="card-value" style="font-size: 18px;">
                    {% if billing_skip_active %}
                        <span style="color: var(--solar);">⚠️ Auto-Skip Active</span>
                    {% else %}
                        <span style="color: var(--sbu);">✅ Normal Schedule</span>
                    {% endif %}
                </div>
                <div class="card-sub">
                    {% if billing_skip_active %}
                        Today is day {{ billing_day }} (Billing period). Solar tasks auto-skip.
                    {% else %}
                        Days {{ skip_days_str }} skip solar mode automatically.
                    {% endif %}
                </div>
            </div>
        </div>

        <!-- Manual Controls -->
        <div class="controls-card">
            <div class="controls-header">
                <h2>🎛️ Manual Override & Controls</h2>
                <label class="force-checkbox-wrap">
                    <input type="checkbox" id="force-checkbox">
                    <span>Override billing skip (Force)</span>
                </label>
            </div>
            
            <div class="btn-group">
                <button class="btn btn-solar" onclick="triggerAction('set-solar')">
                    ☀️ Switch to Solar (val=1)
                </button>
                <button class="btn btn-sbu" onclick="triggerAction('set-sbu')">
                    🔋 Switch to SBU (val=2)
                </button>
                <button class="btn btn-status" onclick="triggerAction('read-status')">
                    📊 Query Inverter Status
                </button>
            </div>

            <div id="feedback-toast"></div>
        </div>

        <!-- Activity History -->
        <div class="logs-card">
            <div class="logs-header">
                <h2>📋 Recent Activity Log</h2>
                <button class="btn btn-status" style="padding: 6px 12px; font-size: 12px;" onclick="window.location.reload()">
                    🔄 Refresh
                </button>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Time ({{ timezone_name }})</th>
                            <th>Action</th>
                            <th>Trigger</th>
                            <th>Status</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody id="logs-tbody">
                        {% for log in logs %}
                        <tr>
                            <td>{{ log.timestamp }}</td>
                            <td><strong>{{ log.action }}</strong></td>
                            <td><span class="tag-trigger">{{ log.trigger }}</span></td>
                            <td>
                                <span class="badge-status status-{{ log.status }}">{{ log.status }}</span>
                            </td>
                            <td>{{ log.message }}</td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="5" style="text-align: center; color: var(--text-secondary); padding: 24px;">
                                No recent activity yet. Scheduled tasks will appear here.
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Footer -->
        <footer>
            Inverter Automator • Kept alive by UptimeRobot • Powered by Render Web Service
        </footer>
    </div>

    <script>
        async function triggerAction(action) {
            const toast = document.getElementById('feedback-toast');
            const force = document.getElementById('force-checkbox').checked;
            
            toast.style.display = 'block';
            toast.className = 'toast-skipped';
            toast.innerHTML = '⏳ Executing ' + action + '... Please wait...';

            try {
                const response = await fetch(`/api/trigger?action=${encodeURIComponent(action)}&force=${force}`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.skipped) {
                    toast.className = 'toast-skipped';
                    toast.innerHTML = '⚠️ Skipped: ' + (data.reason || 'Billing period protection active.');
                } else if (data.success) {
                    toast.className = 'toast-success';
                    toast.innerHTML = '✅ Success: ' + action + ' executed successfully!';
                } else {
                    toast.className = 'toast-failure';
                    toast.innerHTML = '❌ Failed: ' + (data.error || JSON.stringify(data.data || 'Unknown error'));
                }
                
                // Auto reload page after 2 seconds to refresh cards
                setTimeout(() => {
                    window.location.reload();
                }, 2200);

            } catch (err) {
                toast.className = 'toast-failure';
                toast.innerHTML = '❌ Network error: ' + err.message;
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    """Web Dashboard UI."""
    is_skip, current_day = inverter_control.is_billing_skip_day(TIMEZONE_NAME)
    skip_days_str = ", ".join(str(d) for d in inverter_control.get_billing_skip_days())
    solar_mins_display = SOLAR_MINUTES if "," in SOLAR_MINUTES else SOLAR_MINUTES.zfill(2)
    sbu_mins_display = SBU_MINUTES.zfill(2) if SBU_MINUTES.isdigit() else SBU_MINUTES
    solar_label = f"{SOLAR_HOURS.zfill(2)}:{solar_mins_display} ({TIMEZONE_NAME})"
    sbu_label = f"{SBU_HOURS.zfill(2)}:{sbu_mins_display} ({TIMEZONE_NAME})"
    
    return render_template_string(
        DASHBOARD_HTML,
        uptime=get_uptime_string(),
        ping_counter=ping_counter,
        last_ping=last_ping_time,
        timezone_name=TIMEZONE_NAME,
        solar_schedule_label=solar_label,
        sbu_schedule_label=sbu_label,
        inverter_mode=latest_inverter_status,
        next_runs=get_next_job_runs(),
        billing_day=current_day,
        billing_skip_active=is_skip,
        skip_days_str=skip_days_str,
        logs=list(activity_logs)
    )

if __name__ == '__main__':
    logger.info(f"Starting Inverter Automator Web Server on port {PORT}...")
    app.run(host='0.0.0.0', port=PORT)
