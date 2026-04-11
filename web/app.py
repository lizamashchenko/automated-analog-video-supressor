import argparse
import json
import os
import sys
import threading
from queue import Empty, Full, Queue

from flask import Flask, Response, jsonify, render_template, request, send_file

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from detector import Detector
from utils.config import load as load_config

app = Flask(__name__)

_detector: Detector | None = None
_detector_lock = threading.Lock()
_clients: list[Queue] = []
_clients_lock = threading.Lock()

def _broadcast(event_type: str, data: dict):
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait({"type": event_type, "data": data})
            except Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)

@app.route("/")
def index():
    cfg = load_config()
    return render_template("index.html", cfg = cfg)

@app.route("/stream")
def stream():
    q: Queue = Queue(maxsize = 500)
    with _clients_lock:
        _clients.append(q)

    def generate():
        try:
            while True:
                try:
                    event = q.get(timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except Empty:
                    yield ": keepalive\n\n"

        finally:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.route("/start", methods = ["POST"])
def start():
    global _detector
    body = request.json or {}

    cfg = load_config()

    if "device" in body:
        cfg["device"]["type"] = body["device"]
    if "file_path" in body and body["file_path"]:
        cfg["device"]["file_path"] = body["file_path"]
    if "metadata_path" in body and body["metadata_path"]:
        cfg["device"]["metadata_path"] = body["metadata_path"]
    if "classifier" in body:
        cfg["detection"]["active_classifier"] = body["classifier"]
    if "min_freq" in body:
        cfg["sdr"]["min_freq"] = float(body["min_freq"]) * 1e6
    if "max_freq" in body:
        cfg["sdr"]["max_freq"] = float(body["max_freq"]) * 1e6
    if "verbosity" in body:
        cfg["logging"]["verbosity"] = int(body["verbosity"])

    cfg["sweeps"] = int(body.get("sweeps", 0))
    run_name = body.get("run_name") or None

    with _detector_lock:
        if _detector and _detector.is_running():
            return jsonify({"error": "Already running"}), 400
     
        _detector = Detector(cfg, on_event = _broadcast)
        _detector.start(run_name = run_name)

    return jsonify({"ok": True})

@app.route("/stop", methods = ["POST"])
def stop():
    global _detector

    with _detector_lock:
        if _detector:
            threading.Thread(target = _detector.stop, daemon = True).start()

    return jsonify({"ok": True})

@app.route("/status")
def status():
    running = _detector is not None and _detector.is_running()
    return jsonify({"running": running})

@app.route("/logs/<path:filepath>")
def serve_log_file(filepath):
    root = os.path.dirname(os.path.dirname(__file__))
    full_path = os.path.join(root, "logs", filepath)
    
    if os.path.exists(full_path):
        return send_file(full_path)
    
    return "Not found", 404

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type = int, default = 5000)
    parser.add_argument("--host", default = "127.0.0.1")
    args = parser.parse_args()
    app.run(host = args.host, port = args.port, debug = False, threaded = True)
