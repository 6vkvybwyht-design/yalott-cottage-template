"""Адмінка власника (/admin): заявки по кожному будинку, календар зайнятості всіх трьох
із закриттям діб, ціни окремо для кожного будинку (ціна за добу + знижки за тривалість),
періоди «ціна за домовленістю», ціни чану й бані, тестове сповіщення в Telegram."""

import re
import secrets
import time
from functools import wraps

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

import database as db_
import notifications
import pricing as P
import site_content

bp = Blueprint("admin", __name__, url_prefix="/admin")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped


def api_required(view):
    """Для JSON-запитів адмінки: потрібен вхід і CSRF-токен у заголовку."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return jsonify(ok=False, error="Сесія завершилась — увійдіть знову", login=True), 401
        if request.method == "POST":
            token = request.headers.get("X-CSRF-Token") or ""
            if not token or not secrets.compare_digest(token, session.get("csrf", "")):
                return jsonify(ok=False, error="Сесія застаріла — оновіть сторінку"), 400
        return view(*args, **kwargs)
    return wrapped


def _error(e):
    return jsonify(ok=False, error=str(e)), e.status


@bp.route("/login", methods=["GET", "POST"])
def login():
    db = db_.get_db()
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            flash("Сесія застаріла — спробуйте ще раз.", "error")
            return redirect(url_for("admin.login"))
        username = request.form.get("username", "").strip()
        user = db.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["admin_id"] = user["id"]
            session["admin_name"] = user["username"]
            return redirect(url_for("admin.index"))
        time.sleep(0.7)  # уповільнюємо підбір пароля
        flash("Неправильний логін або пароль.", "error")

    demo = db.execute("SELECT password_hash FROM admin_users WHERE username = ?",
                      (db_.DEMO_ADMIN[0],)).fetchone()
    show_demo = demo is not None and check_password_hash(demo["password_hash"], db_.DEMO_ADMIN[1])
    return render_template("admin/login.html", demo=db_.DEMO_ADMIN if show_demo else None)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@bp.get("/")
@login_required
def index():
    return render_template("admin/index.html", admin_name=session.get("admin_name"))


# ---------- JSON API для сторінки адмінки ----------

@bp.get("/api/data")
@api_required
def data():
    payload = db_.admin_data(db_.get_db())
    payload["today"] = current_app.extensions["fh_today"]()
    payload["telegram"] = notifications.is_configured()
    return jsonify(payload)


@bp.post("/api/status")
@api_required
def status():
    body = request.get_json(silent=True) or {}
    try:
        booking = db_.set_status(db_.get_db(), str(body.get("id", "")), str(body.get("status", "")))
    except db_.BookingError as e:
        return _error(e)
    return jsonify(ok=True, booking=booking)


def _object_ids(value):
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(o, int) and not isinstance(o, bool) and o in P.OBJECT_IDS for o in value):
        return None
    return value


@bp.post("/api/block-nights")
@api_required
def block_nights():
    body = request.get_json(silent=True) or {}
    dates, objects = body.get("dates"), _object_ids(body.get("objects"))
    if not isinstance(dates, list) or not all(isinstance(d, str) and DATE_RE.match(d) for d in dates):
        return jsonify(ok=False, error="Некоректні дати"), 400
    if objects is None:
        return jsonify(ok=False, error="Оберіть об'єкт"), 400
    db_.block_nights(db_.get_db(), dates, objects, bool(body.get("blocked")))
    return jsonify(ok=True)


def _price(value, required=True):
    if value in (None, "") and not required:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise db_.BookingError("Ціна має бути числом")
    if not 0 < n <= 1_000_000:
        raise db_.BookingError("Некоректна ціна")
    return n


def _object_id(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    if n not in P.OBJECT_IDS:
        raise db_.BookingError("Оберіть об'єкт")
    return n


@bp.post("/api/object-prices")
@api_required
def object_prices():
    """Ціна будинку за добу й знижки за тривалість: tiers = [{"nights": 2, "price": 2200}, ...]."""
    body = request.get_json(silent=True) or {}
    raw = body.get("tiers")
    try:
        object_id = _object_id(body.get("id"))
        if not isinstance(raw, list) or len(raw) > 6:
            raise db_.BookingError("Некоректні знижки")
        tiers = []
        for t in raw:
            if not isinstance(t, dict):
                raise db_.BookingError("Некоректні знижки")
            try:
                nights = int(t.get("nights"))
            except (TypeError, ValueError):
                raise db_.BookingError("Поріг знижки — число діб")
            tiers.append({"nights": nights, "price": _price(t.get("price"))})
        db_.save_object_prices(db_.get_db(), object_id, _price(body.get("price")), tiers)
    except db_.BookingError as e:
        return _error(e)
    return jsonify(ok=True)


@bp.post("/api/extra-price")
@api_required
def extra_price():
    body = request.get_json(silent=True) or {}
    try:
        db_.save_extra_price(db_.get_db(), str(body.get("key", "")), _price(body.get("price")))
    except db_.BookingError as e:
        return _error(e)
    return jsonify(ok=True)


@bp.post("/api/period")
@api_required
def period_save():
    """Період (свята): ціна за добу або «за домовленістю» (onRequest), для одного будинку чи всіх."""
    body = request.get_json(silent=True) or {}
    try:
        start, end = body.get("start"), body.get("end")
        if not (isinstance(start, str) and DATE_RE.match(start) and isinstance(end, str) and DATE_RE.match(end)):
            raise db_.BookingError("Вкажіть дати початку й кінця")
        if end < start:
            raise db_.BookingError("Кінець періоду раніше за початок")
        object_id = None if body.get("objectId") in (None, "", "all", 0) else _object_id(body.get("objectId"))
        price = None if body.get("onRequest") else _price(body.get("price"))
        data = {"objectId": object_id, "name": str(body.get("name") or "").strip()[:60],
                "start": start, "end": end, "price": price}
        period_id = body.get("id")
        period_id = int(period_id) if period_id not in (None, "") else None
        db_.save_period(db_.get_db(), data, period_id)
    except db_.BookingError as e:
        return _error(e)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Некоректний період"), 400
    return jsonify(ok=True)


@bp.post("/api/period-delete")
@api_required
def period_delete():
    body = request.get_json(silent=True) or {}
    try:
        db_.delete_period(db_.get_db(), int(body.get("id")))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Некоректний період"), 400
    return jsonify(ok=True)


@bp.post("/api/telegram-test")
@api_required
def telegram_test():
    ok, error = notifications.send_message(
        f"✅ <b>{site_content.SITE['name']}</b>: тестове сповіщення. Telegram налаштовано правильно.")
    return (jsonify(ok=True), 200) if ok else (jsonify(ok=False, error=error), 502)
