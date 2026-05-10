#!/usr/bin/env python3

import subprocess
import threading
import os
import re
import json
import time
import logging
from datetime import datetime
from flask import Flask, Response, request, send_from_directory

# -------------------------------------------------------
# Config
# -------------------------------------------------------
SCRIPT_PATH      = "/usr/local/bin/git-sync.sh"
REPO_PATH        = "/repo"          # internal mount point — hardcoded, never changes
DISPLAY_PATH     = os.environ.get("REPO_DISPLAY_PATH", "")
MAX_COMMIT_LEN   = 250
PORT             = 8585
STREAM_TIMEOUT   = 70               # slightly longer than the 60s bash timeout
AUTOSAVE_STARTUP_DELAY = 30         # seconds before first autosave run on startup

AUTOSAVE_ENABLED  = os.environ.get("AUTOSAVE_ENABLED", "false").lower() == "true"
AUTOSAVE_INTERVAL = os.environ.get("AUTOSAVE_INTERVAL", "24h")
AUTOSAVE_BRANCH   = os.environ.get("AUTOSAVE_BRANCH", "autosave")
MAIN_BRANCH       = os.environ.get("MAIN_BRANCH", "main")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Suppress Flask dev server banner
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__, static_folder=None)

# Server-side in-progress lock
_lock          = threading.Lock()
_running       = False
_last_autosave = None               # set after each successful autosave run


# -------------------------------------------------------
# Git repo introspection
# -------------------------------------------------------
def get_remote_repo():
    """Parse owner/repo from .git/config remote origin url.
    Handles both https://github.com/owner/repo.git
    and git@github.com:owner/repo.git formats.
    Returns 'owner/repo' string or None if unreadable.
    """
    git_config = os.path.join(REPO_PATH, ".git", "config")
    try:
        with open(git_config, "r") as f:
            content = f.read()
        # HTTPS format
        m = re.search(r'url\s*=\s*https://[^/]+/([^/\s]+/[^/\s]+?)(?:\.git)?\s*$', content, re.MULTILINE)
        if m:
            return m.group(1)
        # SSH format
        m = re.search(r'url\s*=\s*git@[^:]+:([^/\s]+/[^\s]+?)(?:\.git)?\s*$', content, re.MULTILINE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def get_current_branch():
    """Read active branch name from .git/HEAD.
    Returns branch name string or falls back to MAIN_BRANCH env var.
    """
    head_file = os.path.join(REPO_PATH, ".git", "HEAD")
    try:
        with open(head_file, "r") as f:
            content = f.read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
    except Exception:
        pass
    return MAIN_BRANCH


# -------------------------------------------------------
# Interval parser — supports 1h, 6h, 24h, 1d, 1w, 2w etc.
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
# Credential lock warning filter
# -------------------------------------------------------
SUPPRESSED_PATTERNS = [
    "unable to get credential storage lock",
    "credential storage lock",
]

def should_suppress(line):
    low = line.lower()
    return any(p in low for p in SUPPRESSED_PATTERNS)


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
        env["REPO_PATH"]       = REPO_PATH
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
                    line = line.rstrip()
                    if not should_suppress(line):
                        yield f"data: {json.dumps({'line': line})}\n\n"
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
def run_autosave():
    """Run a single autosave and update _last_autosave on success."""
    global _last_autosave
    log.info("Autosave: running scheduled push...")
    success = True
    try:
        for chunk in stream_script("autosave"):
            # check for error status in the final done event
            try:
                data = json.loads(chunk.replace("data: ", "").strip())
                if data.get("done") and data.get("status") == "error":
                    success = False
            except Exception:
                pass
    except Exception as e:
        log.error(f"Autosave error: {e}")
        success = False

    if success:
        _last_autosave = datetime.now().strftime("%Y-%m-%d %H:%M")
        log.info(f"Autosave complete at {_last_autosave}")
    else:
        log.warning("Autosave finished with errors — last autosave time not updated")


def autosave_worker(interval_seconds):
    log.info(f"Autosave enabled — interval: {AUTOSAVE_INTERVAL}, branch: {AUTOSAVE_BRANCH}")
    log.info(f"First autosave run in {AUTOSAVE_STARTUP_DELAY} seconds...")
    time.sleep(AUTOSAVE_STARTUP_DELAY)

    while True:
        run_autosave()
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
    """Expose repo info and runtime config to the UI."""
    return {
        "display_path":      DISPLAY_PATH or REPO_PATH,
        "remote_repo":       get_remote_repo(),
        "current_branch":    get_current_branch(),
        "autosave_enabled":  AUTOSAVE_ENABLED,
        "autosave_interval": AUTOSAVE_INTERVAL if AUTOSAVE_ENABLED else None,
        "autosave_branch":   AUTOSAVE_BRANCH   if AUTOSAVE_ENABLED else None,
        "last_autosave":     _last_autosave,
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
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -------------------------------------------------------
# Startup
# -------------------------------------------------------
def start_autosave():
    if AUTOSAVE_ENABLED:
        try:
            interval = parse_interval(AUTOSAVE_INTERVAL)
        except ValueError as e:
            log.error(f"Invalid AUTOSAVE_INTERVAL '{AUTOSAVE_INTERVAL}': {e}. Autosave disabled.")
            return
        t = threading.Thread(target=autosave_worker, args=(interval,), daemon=True)
        t.start()
    else:
        log.info("Autosave disabled.")


start_autosave()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
