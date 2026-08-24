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


@bp.get("/pending-result")
def pending_result():
    """Раз в запуск приложения — не применилось ли обновление, запущенное
    перед ЭТИМ стартом (см. update_checker.consume_pending_update_result).
    Фронт вызывает один раз при загрузке и показывает тост с результатом."""
    return jsonify(update_checker.consume_pending_update_result())


@bp.post("/download")
def download():
    try:
        update_checker.start_download()
    except update_checker.UpdateInstallError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(update_checker.get_download_state())


@bp.get("/progress")
def progress():
    return jsonify(update_checker.get_download_state())


@bp.post("/cancel")
def cancel():
    update_checker.cancel_download()
    return jsonify(update_checker.get_download_state())


@bp.post("/apply")
def apply():
    try:
        update_checker.apply_update()
    except update_checker.UpdateInstallError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(status="applying")
