from flask import Blueprint, jsonify, request

from app.services import performance_settings

bp = Blueprint("performance", __name__)


@bp.get("")
def get_performance():
    return jsonify(performance_settings.effective_settings())


@bp.put("")
def update_performance():
    body = request.get_json(force=True) or {}
    mode = body.get("mode", "auto")
    if mode not in ("auto", "manual"):
        return jsonify(error="mode должен быть auto или manual"), 400
    updates = {"mode": mode}
    if mode == "manual":
        try:
            workers = int(body.get("workers"))
            timeout = int(body.get("timeout_seconds"))
        except (TypeError, ValueError):
            return jsonify(error="workers и timeout_seconds должны быть числами"), 400
        if not 1 <= workers <= 4 or not 30 <= timeout <= 600:
            return jsonify(error="workers: 1-4, timeout_seconds: 30-600"), 400
        updates.update(workers=workers, timeout_seconds=timeout)
    else:
        updates.update(workers=None, timeout_seconds=None)
    performance_settings.save_settings(updates)
    return jsonify(performance_settings.effective_settings())
