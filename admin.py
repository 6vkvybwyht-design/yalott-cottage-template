"""Адмінка власника (/admin): заявки по кожному об'єкту, календар зайнятості із закриттям ночей,
ціни й параметри кожного об'єкта (ціна за ніч, доплата за гостей, мінімум ночей, знижки за тривалість),
сезони, ціни додаткових послуг, тестове сповіщення в Telegram."""

import html
import logging
import re
import secrets
from functools import wraps

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import database as db_
import notifications
import security

bp = Blueprint("admin", __name__, url_prefix="/admin")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
log = logging.getLogger(__name__)
# Хеш для перевірки пароля неіснуючого логіна: відповідь займає стільки ж часу, як для справжнього,
# тож за часом відповіді не можна дізнатися, які логіни існують.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


def _pwv(password_hash):
    return security.password_version(password_hash, current_app.secret_key)


def logged_in():
    """Чи дійсний вхід: користувач є в базі, і пароль не змінювався після входу. Інакше сесія очищається.
    Строк дії (12 год) стежить Flask: cookie «постійної» сесії сама спливає після PERMANENT_SESSION_LIFETIME."""
    admin_id = session.get("admin_id")
    if not admin_id:
        return False
    user = db_.get_db().execute("SELECT password_hash FROM admin_users WHERE id = ?", (admin_id,)).fetchone()
    if user is None or not security.token_ok(session.get("pwv"), _pwv(user["password_hash"])):
        session.clear()
        return False
    return True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped


def api_required(view):
    """Для JSON-запитів адмінки: потрібен вхід і CSRF-токен у заголовку."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not logged_in():
            return jsonify(ok=False, error="Сесія завершилась — увійдіть знову", login=True), 401
        if request.method == "POST":
            if not security.token_ok(request.headers.get("X-CSRF-Token"), session.get("csrf")):
                return jsonify(ok=False, error="Сесія застаріла — оновіть сторінку"), 400
        return view(*args, **kwargs)
    return wrapped


def _error(e):
    return jsonify(ok=False, error=str(e)), e.status


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Вхід. Захист від підбору пароля: 5 невдалих спроб з однієї IP або 10 на один логін за 15 хв →
    пауза 15 хв. Лічильник — у базі (спільний для всіх воркерів); без sleep, який блокував би сайт."""
    db = db_.get_db()
    status = 200
    if request.method == "POST":
        if not security.token_ok(request.form.get("csrf"), session.get("csrf")):
            flash("Сесія застаріла — спробуйте ще раз.", "error")
            return redirect(url_for("admin.login"))
        username = security.clean_text(request.form.get("username"), 80)
        ip = request.remote_addr or "?"
        wait = security.login_blocked(db, ip, username)
        if wait:
            log.warning("Вхід в адмінку тимчасово заблоковано: IP %s, логін %r (забагато невдалих спроб)", ip, username)
            flash(f"Забагато невдалих спроб. Спробуйте через {max(1, round(wait / 60))} хв.", "error")
            status = 429
        else:
            user = db.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
            ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, request.form.get("password") or "")
            if user and ok:
                security.clear_login_failures(db, ip, username)
                demo_grant = session.get("demo")      # доступ до демо за посиланням лишається після входу
                session.clear()
                if demo_grant:
                    session["demo"] = demo_grant
                session.permanent = True   # вхід діє 12 год (PERMANENT_SESSION_LIFETIME), потім — знову пароль
                session["admin_id"] = user["id"]
                session["admin_name"] = user["username"]
                session["pwv"] = _pwv(user["password_hash"])
                session["csrf"] = secrets.token_urlsafe(16)   # новий токен після входу
                return redirect(url_for("admin.index"))
            security.record_login_failure(db, ip, username)
            log.warning("Невдалий вхід в адмінку: IP %s, логін %r", ip, username)
            flash("Неправильний логін або пароль.", "error")
            status = 401

    # Демо-доступ показуємо лише на демо-сайті (DEMO_DATA=1) і лише поки стоїть демо-пароль.
    show_demo = False
    if current_app.config.get("DEMO_DATA"):
        demo = db.execute("SELECT password_hash FROM admin_users WHERE username = ?", (db_.DEMO_ADMIN[0],)).fetchone()
        show_demo = demo is not None and check_password_hash(demo["password_hash"], db_.DEMO_ADMIN[1])
    return render_template("admin/login.html", demo=db_.DEMO_ADMIN if show_demo else None), status


@bp.post("/logout")
def logout():
    # CSRF і тут: інакше чужий сайт міг би «викидати» власника з адмінки.
    if security.token_ok(request.form.get("csrf"), session.get("csrf")):
        demo_grant = session.get("demo")
        session.clear()
        if demo_grant:
            session["demo"] = demo_grant
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
    known = db_.objects(db_.get_db())
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(o, int) and not isinstance(o, bool) and o in known for o in value):
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
    count = body.get("count")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 50):
        return jsonify(ok=False, error="Некоректна кількість"), 400
    db_.block_nights(db_.get_db(), dates, objects, bool(body.get("blocked")), count)
    return jsonify(ok=True)


def _price(value, required=True, low=1):
    """Будь-яке ціле число в гривнях: 4500, 20000, 12345. Крок не обмежується."""
    if value in (None, "") and not required:
        return None
    try:
        n = int(str(value).replace(" ", "").replace("\u00a0", ""))
    except (TypeError, ValueError):
        raise db_.BookingError("Ціна має бути цілим числом")
    if n < low:
        raise db_.BookingError("Ціна має бути більшою за 0" if low == 1 else f"Ціна не може бути меншою за {low}")
    if n > 1_000_000:
        raise db_.BookingError("Завелика ціна — до 1 000 000 грн")
    return n


def _number(body, key, low, high, label):
    """Необов'язкове ціле поле (гості, одиниці, мінімум ночей): None, якщо його не надіслали."""
    if body.get(key) in (None, ""):
        return None
    try:
        n = int(body[key])
    except (TypeError, ValueError):
        raise db_.BookingError(f"{label}: потрібне ціле число")
    if not low <= n <= high:
        raise db_.BookingError(f"{label}: від {low} до {high}")
    return n


def _object_id(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    if n not in db_.objects(db_.get_db()):
        raise db_.BookingError("Оберіть об'єкт")
    return n


@bp.post("/api/object-prices")
@api_required
def object_prices():
    """Ціна об'єкта за ніч, доплата за гостей, мінімум ночей, знижки за тривалість:
    tiers = [{"nights": 2, "price": 2200}, ...]."""
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
                raise db_.BookingError("Поріг знижки — число ночей")
            tiers.append({"nights": nights, "price": _price(t.get("price"))})
        data = {"price": _price(body.get("price")), "tiers": tiers}
        if body.get("extraGuestPrice") not in (None, ""):
            data["extraGuestPrice"] = _price(body.get("extraGuestPrice"), low=0)
        for key, low, high, label in (("minNights", 1, 30, "Мінімум ночей"), ("baseGuests", 1, 50, "Гостей у ціні"),
                                      ("maxGuests", 1, 50, "Максимум гостей"), ("units", 1, 50, "Кількість одиниць")):
            n = _number(body, key, low, high, label)
            if n is not None:
                data[key] = n
        db_.save_object_settings(db_.get_db(), object_id, data)
    except db_.BookingError as e:
        return _error(e)
    return jsonify(ok=True)


@bp.post("/api/extra-price")
@api_required
def extra_price():
    body = request.get_json(silent=True) or {}
    try:
        tiers = body.get("guestPrices")
        if tiers is not None:
            if not isinstance(tiers, list) or len(tiers) > 8 or not all(isinstance(t, dict) for t in tiers):
                raise db_.BookingError("Некоректні ціни за кількістю гостей")
            tiers = [{"upTo": _number(t, "upTo", 1, 50, "Гостей") or 0, "price": _price(t.get("price"))} for t in tiers]
        db_.save_extra_price(db_.get_db(), str(body.get("key", "")), _price(body.get("price")), tiers)
    except db_.BookingError as e:
        return _error(e)
    return jsonify(ok=True)


@bp.post("/api/period")
@api_required
def period_save():
    """Сезон (свята): ціна за ніч або «за домовленістю» (onRequest), для одного об'єкта чи всіх."""
    body = request.get_json(silent=True) or {}
    try:
        start, end = body.get("start"), body.get("end")
        if not (isinstance(start, str) and DATE_RE.match(start) and isinstance(end, str) and DATE_RE.match(end)):
            raise db_.BookingError("Вкажіть дати початку й кінця")
        if end < start:
            raise db_.BookingError("Кінець сезону раніше за початок")
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
        return jsonify(ok=False, error="Некоректний сезон"), 400
    return jsonify(ok=True)


@bp.post("/api/period-delete")
@api_required
def period_delete():
    body = request.get_json(silent=True) or {}
    try:
        db_.delete_period(db_.get_db(), int(body.get("id")))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Некоректний сезон"), 400
    return jsonify(ok=True)


@bp.post("/api/telegram-test")
@api_required
def telegram_test():
    ok, error = notifications.send_message(
        f"✅ <b>{html.escape(db_.site().brand['name'])}</b>: тестове сповіщення. Telegram налаштовано правильно.")
    return (jsonify(ok=True), 200) if ok else (jsonify(ok=False, error=error), 502)
