import json, time, functools
from flask import (Flask, render_template, jsonify, Response,
                   request, redirect, url_for, session)
from .state import network_state
from tas.engine import TASConfig
from tas.cbs import CBSConfig

PASSWORD = "tuetuetue"
SECRET_KEY = "vtsnSecretKey2026"

def create_app(tas_store=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = SECRET_KEY

    def login_required(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            if request.form.get("password") == PASSWORD:
                session["logged_in"] = True
                return redirect(url_for("index"))
            error = "Wrong password"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear(); return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        return render_template("index.html")

    @app.route("/api/nodes")
    @login_required
    def get_nodes():
        return jsonify(network_state.get_snapshot())

    @app.route("/api/report", methods=["POST"])
    def report():
        data = request.get_json()
        if data:
            network_state.update_node(
                node_id=data.get("node_id","unknown"),
                role=data.get("role","unknown"),
                offset_ms=data.get("offset_ms"),
                ip=data.get("ip", request.remote_addr))
        return jsonify({"ok": True})

    @app.route("/api/stream")
    @login_required
    def stream():
        def gen():
            while True:
                yield f"data: {json.dumps(network_state.get_snapshot())}\n\n"
                time.sleep(1)
        return Response(gen(), mimetype="text/event-stream")

    @app.route("/api/tas/ports")
    @login_required
    def tas_ports():
        if not tas_store: return jsonify({"error":"TAS not available"}), 404
        return jsonify({pid: cfg.to_dict()
                        for pid, cfg in tas_store.get_all_tas().items()})

    @app.route("/api/tas/<port_id>", methods=["GET"])
    @login_required
    def tas_get(port_id):
        if not tas_store: return jsonify({"error":"TAS not available"}), 404
        return jsonify(tas_store.get_tas(port_id).to_dict())

    @app.route("/api/tas/<port_id>", methods=["POST"])
    @login_required
    def tas_set(port_id):
        if not tas_store: return jsonify({"error":"TAS not available"}), 404
        data = request.get_json()
        if not data: return jsonify({"ok":False,"error":"No data"}), 400
        try:
            ok, msg = tas_store.update_tas(port_id, TASConfig.from_dict(data))
            return jsonify({"ok": ok, "msg": msg})
        except Exception as e:
            return jsonify({"ok":False,"error":str(e)}), 400

    @app.route("/api/tas/<port_id>/reset", methods=["POST"])
    @login_required
    def tas_reset(port_id):
        if not tas_store: return jsonify({"error":"TAS not available"}), 404
        ok, msg = tas_store.reset_tas(port_id)
        return jsonify({"ok":ok,"msg":msg,"config":tas_store.get_tas(port_id).to_dict()})

    @app.route("/api/cbs/ports")
    @login_required
    def cbs_ports():
        if not tas_store: return jsonify({"error":"CBS not available"}), 404
        return jsonify({pid: cfg.to_dict()
                        for pid, cfg in tas_store.get_all_cbs().items()})

    @app.route("/api/cbs/<port_id>", methods=["GET"])
    @login_required
    def cbs_get(port_id):
        if not tas_store: return jsonify({"error":"CBS not available"}), 404
        return jsonify(tas_store.get_cbs(port_id).to_dict())

    @app.route("/api/cbs/<port_id>", methods=["POST"])
    @login_required
    def cbs_set(port_id):
        if not tas_store: return jsonify({"error":"CBS not available"}), 404
        data = request.get_json()
        if not data: return jsonify({"ok":False,"error":"No data"}), 400
        try:
            ok, msg = tas_store.update_cbs(port_id, CBSConfig.from_dict(data))
            return jsonify({"ok": ok, "msg": msg})
        except Exception as e:
            return jsonify({"ok":False,"error":str(e)}), 400

    @app.route("/api/cbs/<port_id>/reset", methods=["POST"])
    @login_required
    def cbs_reset(port_id):
        if not tas_store: return jsonify({"error":"CBS not available"}), 404
        ok, msg = tas_store.reset_cbs(port_id)
        return jsonify({"ok":ok,"msg":msg,"config":tas_store.get_cbs(port_id).to_dict()})

    @app.route("/api/drift/flush", methods=["POST"])
    @login_required
    def drift_flush():
        from .state import network_state
        if network_state._drift_logger:
            network_state._drift_logger.flush()
            f = network_state._drift_logger.get_last_file()
            return jsonify({"ok": True, "file": f})
        return jsonify({"ok": False, "error": "Drift logger not running"})

    @app.route("/api/drift/status")
    @login_required
    def drift_status():
        from .state import network_state
        if network_state._drift_logger:
            dl = network_state._drift_logger
            with dl._lock:
                counts = {nid: len(s) for nid, s in dl._data.items()}
            return jsonify({
                "ok":       True,
                "samples":  counts,
                "last_file": dl.get_last_file(),
                "interval_s": dl.interval_s,
            })
        return jsonify({"ok": False})

    return app
