import os, json, secrets, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from flask import Flask, request, jsonify, session, send_file, Response
from flask_cors import CORS
from datetime import datetime
from io import BytesIO
import cgi
import requests
from requests.auth import HTTPBasicAuth
from collections import deque
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

# ================= PATHS =================
BASE_DIR = "/appdata"
APP_DIR = "/app"
STATIC_PATH = f"{BASE_DIR}/static"
APP_STATIC_PATH = f"{APP_DIR}/static"
LOG_PATH = f"{BASE_DIR}/logs"

CONFIG_PATH = f"{BASE_DIR}/settings.json"
DEFAULT_CONFIG_PATH = f"{APP_DIR}/default-settings.json"
API_LOG = f"{LOG_PATH}/api.log"
WEBHOOK_LOG = f"{LOG_PATH}/webhook.log"

os.makedirs(STATIC_PATH, exist_ok=True)
os.makedirs(LOG_PATH, exist_ok=True)

# ================= PORTS =================
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "9777"))
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# ================= DEFAULTS =================
DEFAULTS = {
    "plex_url": "",
    "plex_token": "",
    "unmanic_url": "http://localhost:8888",
    "unmanic_username": "",
    "unmanic_password": "",
    "startup_delay": 120,
    "ui_username": "admin",
    "ui_password": "admin",
    "auto_resume_enabled": True,
    "auto_start_timer": False,
    "webhook_keys": [],
    "plex_monitor_enabled": False,
    "plex_poll_interval": 10,
    "plex_servers": []
}
MIN_RESUME_DELAY = 60
MAX_RESUME_DELAY = 600

# ================= SETTINGS =================
def load_settings():
    if not os.path.exists(CONFIG_PATH):
        defaults = dict(DEFAULTS)
        if os.path.exists(DEFAULT_CONFIG_PATH):
            with open(DEFAULT_CONFIG_PATH) as f:
                defaults.update(json.load(f))
        save_settings(defaults)
    with open(CONFIG_PATH) as f:
        data = json.load(f)
    if "username" in data and "unmanic_username" not in data:
        data["unmanic_username"] = data["username"]
    if "password" in data and "unmanic_password" not in data:
        data["unmanic_password"] = data["password"]
    if "auto_start_timer" in data and "auto_resume_enabled" not in data:
        data["auto_resume_enabled"] = data["auto_start_timer"]
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    data["startup_delay"] = clamp_resume_delay(data.get("startup_delay", DEFAULTS["startup_delay"]))
    save_settings(data)
    return data

def clamp_resume_delay(value):
    return max(MIN_RESUME_DELAY, min(MAX_RESUME_DELAY, int(value)))

def save_settings(s):
    with open(CONFIG_PATH, "w") as f:
        json.dump(s, f, indent=2)

settings = load_settings()

def save_current_settings():
    save_settings(settings)

# ================= LOGGING =================
def rotate_log(path, max_lines=1000):
    if not os.path.exists(path):
        return
    with open(path, "r") as f:
        lines = f.readlines()
    if len(lines) > max_lines:
        with open(path, "w") as f:
            f.writelines(lines[-max_lines:])

def log(path, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(path, "a") as f:
        f.write(line + "\n")
    rotate_log(path)

def tail_log(path, lines=1000):
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return list(deque(f, maxlen=lines))

# ================= UNMANIC API =================
def auth_unmanic():
    if settings["unmanic_username"]:
        return HTTPBasicAuth(
            settings["unmanic_username"],
            settings["unmanic_password"]
        )
    return None

def api_call(method, path):
    url = settings["unmanic_url"].rstrip("/") + path
    log(API_LOG, f"{method} {url}")
    try:
        r = requests.request(method, url, auth=auth_unmanic(), timeout=10)
        log(API_LOG, f"-> {r.status_code}")
        return r
    except Exception as e:
        log(API_LOG, f"ERROR {e}")
        return None

def get_workers():
    r = api_call("GET", "/unmanic/api/v2/workers/status")
    if r and r.ok:
        return r.json().get("workers_status", [])
    return []

def test_unmanic_connection():
    r = api_call("GET", "/unmanic/api/v2/workers/status")
    if r and r.ok:
        workers = r.json().get("workers_status", [])
        return {"ok": True, "message": f"Connected. {len(workers)} workers found."}
    if r is not None:
        return {"ok": False, "message": f"HTTP {r.status_code}"}
    return {"ok": False, "message": "Connection failed"}

def pause_all():
    log(WEBHOOK_LOG, "[SUCCESS] Pause all workers")
    r = api_call("POST", "/unmanic/api/v2/workers/worker/pause/all")
    return bool(r and r.ok)

def resume_all():
    log(WEBHOOK_LOG, "[SUCCESS] Resume all workers")
    r = api_call("POST", "/unmanic/api/v2/workers/worker/resume/all")
    return bool(r and r.ok)

def webhook_key_allowed(handler):
    keys = settings.get("webhook_keys", [])
    if not keys:
        return True

    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    supplied = (qs.get("key") or qs.get("api_key") or qs.get("token") or [""])[0]

    auth = handler.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        supplied = auth.split(" ", 1)[1].strip()

    return any(item.get("key") == supplied for item in keys)

# ================= PLEX MONITOR =================
plex_monitor_state = {
    "enabled": False,
    "active": False,
    "last_check": None,
    "servers": []
}
plex_monitor_lock = threading.Lock()

def plex_sessions(server):
    url = server["url"].rstrip("/") + "/status/sessions"
    try:
        r = requests.get(
            url,
            params={"X-Plex-Token": server.get("token", "")},
            timeout=10
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        playing = 0
        paused = 0
        total = int(root.attrib.get("size", "0") or 0)

        for item in root:
            player = item.find("Player")
            state = (player.attrib.get("state", "") if player is not None else "").lower()
            if state in {"playing", "buffering"}:
                playing += 1
            elif state == "paused":
                paused += 1

        return {
            "id": server.get("id"),
            "name": server.get("name", "Plex"),
            "ok": True,
            "playing": playing,
            "paused": paused,
            "total": total,
            "error": ""
        }
    except Exception as e:
        return {
            "id": server.get("id"),
            "name": server.get("name", "Plex"),
            "ok": False,
            "playing": 0,
            "paused": 0,
            "total": 0,
            "error": str(e)
        }

def test_plex_connection(server):
    result = plex_sessions(server)
    if result["ok"]:
        result["message"] = f"Connected. {result['total']} active sessions."
    else:
        result["message"] = result["error"]
    return result

def poll_plex_servers():
    enabled = bool(settings.get("plex_monitor_enabled"))
    servers = [
        s for s in settings.get("plex_servers", [])
        if s.get("enabled", True) and s.get("url") and s.get("token")
    ]

    results = [plex_sessions(server) for server in servers] if enabled else []
    active = any(item["playing"] > 0 for item in results if item["ok"])

    with plex_monitor_lock:
        was_active = plex_monitor_state["active"]
        plex_monitor_state.update({
            "enabled": enabled,
            "active": active,
            "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "servers": results
        })

    if not enabled or not servers:
        return

    if active and not was_active:
        log(WEBHOOK_LOG, "[PLEX MONITOR] Playback detected")
        cancel_timer()
        pause_all()
    elif not active and was_active:
        log(WEBHOOK_LOG, "[PLEX MONITOR] No active playback")
        schedule_resume()

def plex_monitor_loop():
    while True:
        poll_plex_servers()
        interval = max(5, int(settings.get("plex_poll_interval", 10) or 10))
        time.sleep(interval)

# ================= TIMER =================
generation = 0
timer_start = None
lock = threading.Lock()

def cancel_timer():
    global generation, timer_start
    with lock:
        generation += 1
        timer_start = None
    log(WEBHOOK_LOG, "[SYSTEM] Timer cancelled")

def schedule_resume():
    global generation, timer_start

    if not settings.get("auto_resume_enabled", True):
        log(WEBHOOK_LOG, "[IGNORED] Auto resume disabled")
        return

    with lock:
        generation += 1
        my_gen = generation
        timer_start = time.time()

    log(WEBHOOK_LOG, f"[SYSTEM] Resume scheduled in {settings['startup_delay']}s")

    def worker():
        global timer_start
        time.sleep(settings["startup_delay"])
        with lock:
            if my_gen != generation:
                return
            timer_start = None
        resume_all()
        log(WEBHOOK_LOG, "[SUCCESS] Resume executed")

    threading.Thread(target=worker, daemon=True).start()

# ================= WEBHOOK SERVER =================
class WebhookHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/test":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK\n")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if not webhook_key_allowed(self):
            log(WEBHOOK_LOG, "[DENIED] Missing or invalid webhook API key")
            self.send_response(401)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        ct = self.headers.get("Content-Type", "")

        try:
            if "multipart/form-data" in ct:
                fs = cgi.FieldStorage(
                    fp=BytesIO(body),
                    environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ct}
                )
                data = json.loads(fs["payload"].value)
            else:
                data = json.loads(body.decode())
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        event = data.get("event", "")
        log(WEBHOOK_LOG, f"[PLEX] {event}")

        PLAY_EVENTS = {"media.play", "media.resume", "media.start"}
        STOP_EVENTS = {"media.pause", "media.stop", "media.scrobble"}

        if event in PLAY_EVENTS:
            cancel_timer()
            pause_all()
        elif event in STOP_EVENTS:
            schedule_resume()
        else:
            log(WEBHOOK_LOG, f"[IGNORED] {event}")

        self.send_response(200)
        self.end_headers()

    def log_message(self, *_):
        pass

# ================= WEB APP =================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
CORS(app)

def require_auth():
    return not session.get("auth")

def static_file(name):
    app_path = os.path.join(APP_STATIC_PATH, name)
    if os.path.exists(app_path):
        return app_path
    local_path = os.path.join(STATIC_PATH, name)
    if os.path.exists(local_path):
        return local_path
    return app_path

@app.route("/")
def index():
    return send_file(static_file("ui.html"))

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/favicon.ico")
def favicon():
    ico = static_file("favicon.ico")
    return send_file(ico) if os.path.exists(ico) else ("", 204)

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    if (
        data.get("username") == settings["ui_username"] and
        data.get("password") == settings["ui_password"]
    ):
        session["auth"] = True
        return jsonify({"success": True})
    return jsonify({"error": "invalid"}), 401

@app.route("/logout")
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/api/session")
def api_session():
    return jsonify({"authenticated": bool(session.get("auth"))})

@app.route("/api/workers")
def api_workers():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(get_workers())

@app.route("/api/test/unmanic", methods=["POST"])
def api_test_unmanic():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(test_unmanic_connection())

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    global settings
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401

    if request.method == "POST":
        updates = request.get_json(silent=True) or {}
        allowed = {
            "unmanic_url",
            "unmanic_username",
            "unmanic_password",
            "plex_url",
            "plex_token",
            "startup_delay",
            "ui_username",
            "ui_password",
            "auto_resume_enabled",
            "auto_start_timer",
            "plex_monitor_enabled",
            "plex_poll_interval",
        }
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "startup_delay":
                value = clamp_resume_delay(value)
            elif key == "plex_poll_interval":
                value = max(5, int(value))
            settings[key] = value
        if "auto_start_timer" in updates:
            settings["auto_resume_enabled"] = bool(settings["auto_start_timer"])
        if "auto_resume_enabled" in updates:
            settings["auto_start_timer"] = bool(settings["auto_resume_enabled"])
        save_settings(settings)
        return jsonify({"success": True})

    data = dict(settings)
    data["auto_start_timer"] = bool(data.get("auto_start_timer", data.get("auto_resume_enabled", True)))
    data["auto_resume_enabled"] = bool(data.get("auto_resume_enabled", data["auto_start_timer"]))
    data["webhook_port"] = WEBHOOK_PORT
    return jsonify(data)

@app.route("/api/plex-servers", methods=["GET", "POST"])
def api_plex_servers():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401

    settings.setdefault("plex_servers", [])
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        url = str(data.get("url", "")).strip()
        token = str(data.get("token", "")).strip()
        if not name or not url or not token:
            return jsonify({"error": "name, url, and token required"}), 400
        server = {
            "id": secrets.token_hex(8),
            "name": name,
            "url": url,
            "token": token,
            "enabled": bool(data.get("enabled", True))
        }
        settings["plex_servers"].append(server)
        save_current_settings()
        return jsonify(server), 201

    return jsonify(settings["plex_servers"])

@app.route("/api/plex-servers/<server_id>", methods=["DELETE"])
def api_delete_plex_server(server_id):
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401

    settings["plex_servers"] = [
        item for item in settings.get("plex_servers", [])
        if item.get("id") != server_id
    ]
    save_current_settings()
    return jsonify({"success": True})

@app.route("/api/plex-servers/<server_id>/test", methods=["POST"])
def api_test_plex_server(server_id):
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401

    server = next(
        (item for item in settings.get("plex_servers", []) if item.get("id") == server_id),
        None
    )
    if not server:
        return jsonify({"ok": False, "message": "Plex server not found"}), 404
    return jsonify(test_plex_connection(server))

@app.route("/api/plex-monitor/status")
def api_plex_monitor_status():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401
    with plex_monitor_lock:
        return jsonify(dict(plex_monitor_state))

@app.route("/api/webhook-keys", methods=["GET", "POST"])
def api_webhook_keys():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401

    settings.setdefault("webhook_keys", [])
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        item = {
            "name": name,
            "key": secrets.token_urlsafe(32),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        settings["webhook_keys"].append(item)
        save_current_settings()
        return jsonify(item), 201

    return jsonify(settings["webhook_keys"])

@app.route("/api/webhook-keys/<key>", methods=["DELETE"])
def api_delete_webhook_key(key):
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401

    settings["webhook_keys"] = [
        item for item in settings.get("webhook_keys", [])
        if item.get("key") != key
    ]
    save_current_settings()
    return jsonify({"success": True})

@app.route("/api/action/<cmd>", methods=["POST"])
def api_action(cmd):
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401
    cancel_timer()
    if cmd == "pause":
        return jsonify({"success": pause_all()})
    if cmd == "resume":
        return jsonify({"success": resume_all()})
    return jsonify({"success": False})

@app.route("/api/timer")
def api_timer():
    with lock:
        if timer_start is None:
            return jsonify({"active": False})
        remaining = max(
            0,
            settings["startup_delay"] - int(time.time() - timer_start)
        )
        return jsonify({
            "active": True,
            "remaining": remaining,
            "total": settings["startup_delay"]
        })

@app.route("/api/logs/api")
def api_log_view():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401
    return Response("".join(reversed(tail_log(API_LOG))), mimetype="text/plain")

@app.route("/api/logs/webhook")
def webhook_log_view():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401
    return Response("".join(reversed(tail_log(WEBHOOK_LOG))), mimetype="text/plain")

# ================= STARTUP =================
log(WEBHOOK_LOG, "=== CONTROLLER STARTED ===")

if settings.get("auto_start_timer"):
    schedule_resume()

threading.Thread(
    target=lambda: HTTPServer(
        ("0.0.0.0", WEBHOOK_PORT),
        WebhookHandler
    ).serve_forever(),
    daemon=True
).start()

threading.Thread(target=plex_monitor_loop, daemon=True).start()

app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
