from flask import Blueprint, jsonify

from app.services import update_checker

bp = Blueprint("update", __name__)


@bp.get("/check")
def check():
    try:
        result = update_checker.check_for_update()
    except update_checker.UpdateCheckError as exc:
        return jsonify(error=str(exc)), 502
    result["frozen"] = update_checker.is_frozen()
    return jsonify(result)


@bp.post("/install")
def install():
    try:
        update_checker.install_update()
    except update_checker.UpdateInstallError as exc:
        return jsonify(error=str(exc)), 400
    except update_checker.UpdateCheckError as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(status="installing")
