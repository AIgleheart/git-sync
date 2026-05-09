#!/usr/bin/env python3

import subprocess
import threading
import queue
import os
from flask import Flask, Response, request, send_from_directory
import json

app = Flask(__name__, static_folder="static")

SCRIPT_PATH = "/usr/local/bin/git-sync.sh"


def stream_script(action, commit_msg=""):
    """Run git-sync.sh and yield output lines as SSE events."""
    cmd = ["bash", SCRIPT_PATH, action]
    if action == "push" and commit_msg:
        cmd.append(commit_msg)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip("\n")
            yield f"data: {json.dumps({'line': line})}\n\n"

        proc.wait()
        status = "success" if proc.returncode == 0 else "error"
        yield f"data: {json.dumps({'done': True, 'status': status})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'line': f'ERROR: {str(e)}', 'done': True, 'status': 'error'})}\n\n"


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/run/<action>")
def run_action(action):
    if action not in ("push", "pull"):
        return {"error": "invalid action"}, 400

    commit_msg = request.args.get("msg", "").strip()
    
    # Sanity check: prevent massive payloads
    if action == "push" and len(commit_msg) > 255:
        return {"error": "Commit message exceeds 255 characters"}, 400

    if action == "push" and not commit_msg:
        return {"error": "commit message required for push"}, 400

    return Response(
        stream_script(action, commit_msg),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8585, debug=False)
