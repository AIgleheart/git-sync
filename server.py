#!/usr/bin/env python3

import subprocess
import threading
import os
import json
import time
import logging
from flask import Flask, Response, request, send_from_directory

# -------------------------------------------------------
# Config
# -------------------------------------------------------
SCRIPT_PATH      = "/usr/local/bin/git-sync.sh"
MAX_COMMIT_LEN   = 250
PORT             = 8585
STREAM_TIMEOUT   = 70   # seconds — slightly longer than the 60s bash timeout

AUTOSAVE_ENABLED  = os.environ.get("AUTOSAVE_ENABLED", "false").lower() == "true"
AUTOSAVE_INTERVAL = os.environ.get("AUTOSAVE_INTERVAL", "24h")
AUTOSAVE_BRANCH   = os.environ.get("AUTOSAVE_BRANCH", "autosave")
MAIN_BRANCH       = os.environ.get("MAIN_BRANCH", "main")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)

# Server-side in-progress lock
_lock    = threading.Lock()
_running = False


# -------------------------------------------------------
# Interval parser — supports 1h, 6h, 24h, 1w, 2w etc.
# -------------------------------------------------------
def parse_interval(s):
    s = s.strip().lower()
    if s.endswith("w"):
        return int(s[:-1]) * 7 * 24 * 3600
    if s.endswith("d"):
        return int(s[:-1]) * 24 * 3600
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 60
    raise ValueError(f"Unknown interval format: {s}")


# -------------------------------------------------------
# Core: run script and stream output
# -------------------------------------------------------
def stream_script(action, commit_msg=""):
    global _running

    with _lock:
        if _running:
            def _busy():
                yield f"data: {json.dumps({'line': 'ERROR: A git operation is already in progress. Please wait.', 'done': True, 'status': 'error'})}\n\n"
            return _busy()
        _running = True

    def generate():
        global _running
        cmd = ["bash", SCRIPT_PATH, action]
        if action in ("push", "autosave") and commit_msg:
            cmd.append(commit_msg)

        env = os.environ.copy()
        env["MAIN_BRANCH"]     = MAIN_BRANCH
        env["AUTOSAVE_BRANCH"] = AUTOSAVE_BRANCH

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            try:
                for line in proc.stdout:
                    yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
                proc.wait(timeout=STREAM_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                yield f"data: {json.dumps({'line': 'ERROR: Operation timed out server-side.', 'done': True, 'status': 'error'})}\n\n"
                return

            status = "success" if proc.returncode == 0 else "error"
            yield f"data: {json.dumps({'done': True, 'status': status})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'line': f'ERROR: {str(e)}', 'done': True, 'status': 'error'})}\n\n"
        finally:
            with _lock:
                _running = False

    return generate()


# -------------------------------------------------------
# Autosave scheduler
# -------------------------------------------------------
def autosave_worker(interval_seconds):
    log.info(f"Autosave enabled — interval: {AUTOSAVE_INTERVAL}, branch: {AUTOSAVE_BRANCH}")
    # Wait one full interval before first run so startup isn't noisy
    time.sleep(interval_seconds)
    while True:
        log.info("Autosave: running scheduled push...")
        try:
            # Consume the generator fully to actually run the script
            for _ in stream_script("autosave"):
                pass
        except Exception as e:
            log.error(f"Autosave error: {e}")
        time.sleep(interval_seconds)


# -------------------------------------------------------
# Routes
# -------------------------------------------------------
@app.route("/")
def index():
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return send_from_directory(static_dir, "index.html")


@app.route("/status")
def status():
    """Expose config to the UI."""
    return {
        "repo_path":         os.environ.get("REPO_PATH", "/repo"),
        "main_branch":       MAIN_BRANCH,
        "autosave_enabled":  AUTOSAVE_ENABLED,
        "autosave_interval": AUTOSAVE_INTERVAL if AUTOSAVE_ENABLED else None,
        "autosave_branch":   AUTOSAVE_BRANCH   if AUTOSAVE_ENABLED else None,
    }


@app.route("/run/<action>")
def run_action(action):
    if action not in ("push", "pull"):
        return {"error": "invalid action"}, 400

    commit_msg = request.args.get("msg", "").strip()

    if action == "push" and not commit_msg:
        return Response(
            iter([f"data: {json.dumps({'line': 'ERROR: Commit message is required.', 'done': True, 'status': 'error'})}\n\n"]),
            mimetype="text/event-stream"
        )

    if action == "push" and len(commit_msg) > MAX_COMMIT_LEN:
        return Response(
            iter([f"data: {json.dumps({'line': f'ERROR: Commit message exceeds {MAX_COMMIT_LEN} character limit ({len(commit_msg)} chars).', 'done': True, 'status': 'error'})}\n\n"]),
            mimetype="text/event-stream"
        )

    return Response(
        stream_script(action, commit_msg),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -------------------------------------------------------
# Startup
# -------------------------------------------------------
if __name__ == "__main__":
    if AUTOSAVE_ENABLED:
        try:
            interval = parse_interval(AUTOSAVE_INTERVAL)
        except ValueError as e:
            log.error(f"Invalid AUTOSAVE_INTERVAL '{AUTOSAVE_INTERVAL}': {e}. Autosave disabled.")
            interval = None

        if interval:
            t = threading.Thread(target=autosave_worker, args=(interval,), daemon=True)
            t.start()
    else:
        log.info("Autosave disabled.")

    app.run(host="0.0.0.0", port=PORT, debug=False)
