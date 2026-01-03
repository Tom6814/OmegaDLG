import os
import json
import sys
from pathlib import Path
from flask import Flask, request, send_from_directory, jsonify, Response
import threading
import queue
from contextlib import redirect_stdout, redirect_stderr

ROOT_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR))
WEBAPP_DIR = BASE_DIR / "webapp"
DIST_DIR = WEBAPP_DIR / "dist"
STATIC_DIR = DIST_DIR if DIST_DIR.exists() else WEBAPP_DIR
sys.path.insert(0, str(ROOT_DIR))
from main import (
    run_bulk,
    run_single,
    derive_series_name,
    ensure_series_dirs,
    chapter_pdf,
    chapter_label_from_url,
    make_session,
)

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

TASKS = {}

class QueueWriter:
    def __init__(self, q):
        self.q = q
    def write(self, buf):
        if not buf:
            return
        try:
            self.q.put(buf)
        except Exception:
            pass
    def flush(self):
        pass

def _start_async(data):
    task_id = f"t{len(TASKS)+1}"
    q = queue.Queue()
    TASKS[task_id] = {"queue": q, "done": False, "result": None}

    def _runner():
        session = make_session()
        mode = data.get("mode")
        series_url = data.get("series_url")
        chapter_url = data.get("chapter_url")
        series_name = data.get("series_name")
        chapter_num = data.get("chapter_num")
        force = bool(data.get("force", False))
        workers = int(data.get("workers", 6))
        max_retries = int(data.get("max_retries", 3))
        verbose = bool(data.get("verbose", False))

        q.put(f"Starting {mode} task\n")
        try:
            with redirect_stdout(QueueWriter(q)), redirect_stderr(QueueWriter(q)):
                if mode == "series" and series_url:
                    run_bulk(
                        session,
                        series_url,
                        series_name=series_name,
                        force=force,
                        workers=workers,
                        max_retries=max_retries,
                        verbose=verbose,
                    )
                    series_dir = derive_series_name(series_url, series_name)
                    pdf_dir = os.path.join(series_dir, "Chapters")
                    pdfs = []
                    if os.path.isdir(pdf_dir):
                        for f in sorted(os.listdir(pdf_dir)):
                            if f.lower().endswith(".pdf"):
                                pdfs.append(os.path.join(pdf_dir, f))
                    TASKS[task_id]["result"] = {
                        "ok": True,
                        "mode": "series",
                        "series_dir": series_dir,
                        "pdfs": pdfs,
                    }
                elif mode == "chapter" and chapter_url:
                    run_single(
                        session,
                        chapter_url,
                        series_name=series_name,
                        chapter_num=chapter_num,
                        force=force,
                        workers=workers,
                        max_retries=max_retries,
                        verbose=verbose,
                    )
                    series_dir = derive_series_name(chapter_url, series_name)
                    lbl = str(chapter_num or chapter_label_from_url(chapter_url) or "custom")
                    pdf_path = chapter_pdf(series_dir, lbl)
                    TASKS[task_id]["result"] = {
                        "ok": True,
                        "mode": "chapter",
                        "series_dir": series_dir,
                        "label": lbl,
                        "pdf": pdf_path if os.path.exists(pdf_path) else None,
                    }
                else:
                    TASKS[task_id]["result"] = {"ok": False, "error": "invalid_params"}
        except Exception as e:
            TASKS[task_id]["result"] = {"ok": False, "error": str(e)}
        finally:
            TASKS[task_id]["done"] = True
            q.put("Task finished\n")

    threading.Thread(target=_runner, daemon=True).start()
    return task_id

@app.post("/api/start")
def api_start():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400
    task_id = _start_async(data)
    return jsonify({"ok": True, "task_id": task_id})

@app.get("/api/stream/<task_id>")
def api_stream(task_id):
    t = TASKS.get(task_id)
    if not t:
        return Response("", status=404)

    def gen():
        yield "retry: 1500\n\n"
        q = t["queue"]
        while True:
            try:
                msg = q.get(timeout=0.5)
                msg = msg.replace("\r", "")
                for line in msg.splitlines():
                    yield f"data: {line}\n\n"
            except queue.Empty:
                pass
            if t["done"] and q.empty():
                yield f"event: end\ndata: {json.dumps(t['result'])}\n\n"
                break
    return Response(gen(), mimetype="text/event-stream")

@app.get("/")
def index():
    return app.send_static_file("index.html")

@app.post("/api/run")
def api_run():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    mode = data.get("mode")
    series_url = data.get("series_url")
    chapter_url = data.get("chapter_url")
    series_name = data.get("series_name")
    chapter_num = data.get("chapter_num")
    force = bool(data.get("force", False))
    workers = int(data.get("workers", 6))
    max_retries = int(data.get("max_retries", 3))
    verbose = bool(data.get("verbose", False))

    session = make_session()

    if mode == "series" and series_url:
        try:
            run_bulk(
                session,
                series_url,
                series_name=series_name,
                force=force,
                workers=workers,
                max_retries=max_retries,
                verbose=verbose,
            )
            series_dir = derive_series_name(series_url, series_name)
            pdf_dir = os.path.join(series_dir, "Chapters")
            pdfs = []
            if os.path.isdir(pdf_dir):
                for f in sorted(os.listdir(pdf_dir)):
                    if f.lower().endswith(".pdf"):
                        pdfs.append(os.path.join(pdf_dir, f))
            return jsonify({
                "ok": True,
                "mode": "series",
                "series_dir": series_dir,
                "pdfs": pdfs,
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    if mode == "chapter" and chapter_url:
        try:
            run_single(
                session,
                chapter_url,
                series_name=series_name,
                chapter_num=chapter_num,
                force=force,
                workers=workers,
                max_retries=max_retries,
                verbose=verbose,
            )
            series_dir = derive_series_name(chapter_url, series_name)
            lbl = str(chapter_num or chapter_label_from_url(chapter_url) or "custom")
            pdf_path = chapter_pdf(series_dir, lbl)
            return jsonify({
                "ok": True,
                "mode": "chapter",
                "series_dir": series_dir,
                "label": lbl,
                "pdf": pdf_path if os.path.exists(pdf_path) else None,
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": False, "error": "invalid_params"}), 400

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8000
    print(f"GUI server running at http://{host}:{port}/")
    app.run(host=host, port=port, debug=False)