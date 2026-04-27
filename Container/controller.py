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
    "auto_start_timer": False
}

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
    save_settings(data)
    return data

def save_settings(s):
    with open(CONFIG_PATH, "w") as f:
        json.dump(s, f, indent=2)

settings = load_settings()

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

def pause_all():
    log(WEBHOOK_LOG, "[SUCCESS] Pause all workers")
    r = api_call("POST", "/unmanic/api/v2/workers/worker/pause/all")
    return bool(r and r.ok)

def resume_all():
    log(WEBHOOK_LOG, "[SUCCESS] Resume all workers")
    r = api_call("POST", "/unmanic/api/v2/workers/worker/resume/all")
    return bool(r and r.ok)

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
    local_path = os.path.join(STATIC_PATH, name)
    if os.path.exists(local_path):
        return local_path
    return os.path.join(APP_STATIC_PATH, name)

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

@app.route("/api/workers")
def api_workers():
    if require_auth():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(get_workers())

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
        }
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "startup_delay":
                value = max(0, int(value))
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
    return jsonify(data)

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

app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
