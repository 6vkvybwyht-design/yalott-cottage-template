"""Сайт котеджу з онлайн-бронюванням (Flask + SQLite). Універсальний шаблон Yalott Studio.

Усе про конкретного клієнта — у config/site.yaml (див. site_config.py), секрети — у .env.

Запуск на своєму комп'ютері:  python app.py   →  http://localhost:5000
Інший конфіг (приклад):       SITE_CONFIG=config/examples/ramshill.yaml python app.py
"""

import glob
import logging
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta

import click
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for

import database as db_
import gallery
import notifications
import pricing as P
import site_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger(__name__)
BOOKING_HORIZON_DAYS = 365


def load_env_file(path):
    """Читає налаштування з файлу .env (рядки KEY=value).

    Змінні, вже задані в системі, мають пріоритет — файл їх не перезаписує.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


load_env_file(os.path.join(BASE_DIR, ".env"))


def env_flag(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on", "так")


def secret_key(instance_path):
    """SECRET_KEY з .env; якщо його немає — випадковий ключ, збережений у instance/secret_key."""
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    path = os.path.join(instance_path, "secret_key")
    os.makedirs(instance_path, exist_ok=True)
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
    except FileNotFoundError:
        key = ""
    if not key:
        key = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
    log.warning("SECRET_KEY не задано — використовую ключ з %s. На сервері задайте SECRET_KEY у .env.", path)
    return key


# ---------- Час: сайт працює за київським часом (сервер PythonAnywhere живе в UTC) ----------

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Kyiv"))
except Exception:  # немає бази часових поясів — працюємо за часом сервера
    TZ = None


def now_local():
    return datetime.now(TZ) if TZ else datetime.now()


def today_iso():
    return now_local().date().isoformat()


# ---------- Захист від спаму: не більше 10 заявок за 10 хвилин з однієї IP ----------

_hits = {}


def rate_limited():
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    now = time.time()
    recent = [t for t in _hits.get(ip, []) if now - t < 600]
    if len(recent) >= 10:
        return True
    recent.append(now)
    _hits[ip] = recent
    return False


# ---------- Перевірка форми бронювання ----------

def _is_date(s):
    try:
        date.fromisoformat(s)
        return isinstance(s, str) and len(s) == 10
    except (TypeError, ValueError):
        return False


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def validate_booking(body, objects, extra_keys, today):
    """Перевіряє заявку з форми. objects — db_.objects(): максимум гостей і мінімум ночей беруться з бази."""
    name = str(body.get("name") or "").strip()[:80]
    phone = str(body.get("phone") or "").strip()[:32]
    if len(name) < 2:
        raise db_.BookingError("Вкажіть, будь ласка, ім'я")
    if not 9 <= len(re.sub(r"\D", "", phone)) <= 15:
        raise db_.BookingError("Вкажіть коректний номер телефону")

    obj = objects.get(_int(body.get("objectId")))
    if obj is None:
        raise db_.BookingError("Оберіть об'єкт для бронювання")

    check_in, check_out = body.get("checkIn"), body.get("checkOut")
    if not _is_date(check_in) or not _is_date(check_out) or check_out <= check_in:
        raise db_.BookingError("Оберіть дати заїзду та виїзду")
    if check_in < today:
        raise db_.BookingError("Дата заїзду вже минула")
    if check_out > (date.fromisoformat(today) + timedelta(days=BOOKING_HORIZON_DAYS)).isoformat():
        raise db_.BookingError("Бронювання відкрите лише на рік уперед")
    if len(P.nights_between(check_in, check_out)) < obj["minNights"]:
        raise db_.BookingError(f"«{obj['name']}»: мінімальне бронювання — ночей: {obj['minNights']}")

    guests = _int(body.get("guests"))
    if not 1 <= guests <= obj["maxGuests"]:
        raise db_.BookingError(f"«{obj['name']}»: від 1 до {obj['maxGuests']} гостей")
    extras = body.get("extras") or []
    if not isinstance(extras, list):
        extras = []
    extras = [k for k in extra_keys if k in extras]  # лише відомі, без повторів
    if not body.get("rules"):
        raise db_.BookingError("Підтвердьте, що ознайомилися з умовами бронювання")
    return {"objectId": obj["id"], "name": name, "phone": phone,
            "comment": str(body.get("comment") or "").strip()[:500],
            "checkIn": check_in, "checkOut": check_out, "guests": guests, "extras": extras}


# ---------- Тема: кольори з конфігу ----------

def _contrast(hex_color):
    """Колір тексту (темний чи світлий), який читається на цьому тлі."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return "#16130f" if 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b) > 0.4 else "#ffffff"


def theme_overrides(brand):
    """CSS, що перевизначає змінні теми кольорами з конфігу (brand.primary_color / accent_color)."""
    rules = []
    if brand["primary_color"]:
        rules += [f"--primary:{brand['primary_color']}", f"--on-primary:{_contrast(brand['primary_color'])}"]
    if brand["accent_color"]:
        rules.append(f"--accent:{brand['accent_color']}")
    return "html[data-theme]{" + ";".join(rules) + "}" if rules else ""


def favicon_svg(brand):
    letter = (re.sub(r"[^\w]", "", brand["name"]) or "•")[0].upper()
    bg = brand["primary_color"] or {"dark": "#17181a", "wood": "#3a2a1d", "forest": "#16301f"}[brand["theme"]]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{bg}"/>'
            f'<text x="32" y="44" font-family="Georgia,serif" font-size="36" text-anchor="middle" '
            f'fill="{_contrast(bg)}">{letter}</text></svg>')


# ---------- Застосунок ----------

def create_app(test_config=None):
    test_config = dict(test_config or {})
    instance_path = os.environ.get("INSTANCE_PATH") or os.path.join(BASE_DIR, "instance")
    app = Flask(__name__, instance_path=instance_path)

    # Конфіг клієнта. Помилка в ньому зупиняє запуск зі зрозумілим поясненням (python manage.py validate).
    site = site_config.load(test_config.pop("SITE_CONFIG", None))
    app.extensions["site"] = site

    app.config.update(
        SECRET_KEY=secret_key(instance_path),
        # Окрема база на кожен конфіг: site.yaml → instance/site.db, ramshill.yaml → instance/ramshill.db.
        DATABASE=os.environ.get("DATABASE_PATH") or os.path.join(instance_path, f"{site.key}.db"),
        DEMO_DATA=env_flag("DEMO_DATA", default=False),
        SESSION_COOKIE_SAMESITE="Lax",
        # На HTTPS-сервері cookie входу передаються лише захищеним каналом.
        SESSION_COOKIE_SECURE=env_flag("SESSION_COOKIE_SECURE"),
    )
    app.json.ensure_ascii = False
    app.config.update(test_config)

    # База й таблиці створюються автоматично; з конфігу доливається лише те, чого в базі ще немає.
    db_.init_db(app.config["DATABASE"], site, with_demo=app.config["DEMO_DATA"], today=now_local().date())
    db_.ensure_admin(app.config["DATABASE"])
    app.teardown_appcontext(db_.close_db)

    @app.template_filter("uah")
    def uah(value):
        return P.format_uah(value)

    @app.template_filter("udate")
    def udate(iso):
        d = date.fromisoformat(iso)
        return f"{d.day:02d}.{d.month:02d}"

    # Версія стилів і скриптів для посилань (?v=…): після оновлення сайту браузер
    # не віддасть старий style.css разом з новою сторінкою.
    asset_version = "?v=" + str(max(int(os.path.getmtime(f)) for f in glob.glob(
        os.path.join(BASE_DIR, "static", "*", "*.*")) if f.endswith((".css", ".js"))))
    brand = site.brand
    logo = brand["logo"] if gallery.exists(brand["logo"]) else None
    logo_light = brand["logo_light"] if gallery.exists(brand["logo_light"]) else logo
    favicon = brand["favicon"] if gallery.exists(brand["favicon"]) else None
    overrides = theme_overrides(brand)

    @app.context_processor
    def inject_globals():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(16)
        return {"csrf_token": session["csrf"], "current_year": now_local().year, "site": site,
                "brand": brand, "contacts": site.contacts, "rules": site.rules, "sections": site.sections,
                "nav_objects": site.objects, "logo": logo, "logo_light": logo_light, "favicon": favicon,
                "theme_overrides": overrides, "V": asset_version}

    app.jinja_env.globals.update(thumb_for=gallery.thumb_for, plural=site_config.plural,
                                 guests_gen=site_config.guests_gen)
    app.extensions["fh_today"] = lambda: today_iso()  # київська дата для адмінки
    register_routes(app)

    import admin
    app.register_blueprint(admin.bp)

    @app.cli.command("set-password")
    @click.argument("username")
    @click.password_option()
    def set_password_command(username, password):
        """Створити адміністратора або змінити йому пароль."""
        db_.set_password(app.config["DATABASE"], username, password)
        print("Пароль збережено для", username)

    return app


def csrf_ok():
    token = request.headers.get("X-CSRF-Token") or ""
    return bool(token) and secrets.compare_digest(token, session.get("csrf", ""))


def object_facts(o):
    """Короткі факти для картки: гості, спальні, санвузли, кількість одиниць."""
    pl = site_config.plural
    facts = [("users", o["guests_text"])]
    if o.get("bedrooms"):
        facts.append(("bed", f"{o['bedrooms']} {pl(o['bedrooms'], 'спальня', 'спальні', 'спалень')}"))
    if o.get("bathrooms"):
        facts.append(("bath", f"{o['bathrooms']} {pl(o['bathrooms'], 'санвузол', 'санвузли', 'санвузлів')}"))
    if o["units"] > 1:
        facts.append(("chalets", f"{o['units']} {pl(o['units'], 'однаковий', 'однакові', 'однакових')}"))
    return facts


def object_cards(db, site):
    """Тексти з конфігу + актуальні ціни й параметри з бази + фото з папок."""
    live = {o["key"]: o for o in db_.objects(db).values()}
    cards = []
    for o in site.objects:
        p = live.get(o["key"])
        if p is None:
            continue
        card = dict(o, id=p["id"], price=p["price"], tiers=p["tiers"], price_from=P.min_price(p),
                    units=p["units"], base_guests=p["baseGuests"], max_guests=p["maxGuests"],
                    extra_guest_price=p["extraGuestPrice"], min_nights=p["minNights"],
                    guests_text=p["guestsText"], photos=gallery.photos(o["folder"], o["name"]),
                    cover=gallery.cover(o))
        card["facts"] = object_facts(card)
        cards.append(card)
    return cards


def common_page_data(db, site, cards):
    extras = [dict(e, photo_src=gallery.find(site.media("extras"), e["photo"])) for e in db_.extras_list(db)]
    times = {(c["check_in"], c["check_out"]) for c in cards}
    return {"extras": extras, "same_times": len(times) <= 1,
            "min_nights_max": max((c["min_nights"] for c in cards), default=1)}


def register_routes(app):
    site = app.extensions["site"]

    @app.get("/")
    def index():
        db = db_.get_db()
        cards = object_cards(db, site)
        if not cards:
            abort(404)
        featured = next((c for c in cards if c["featured"]), None)
        hero = gallery.first(site.media("hero")) or (featured or cards[0])["cover"]
        og = site.seo["og_image"] if gallery.exists(site.seo["og_image"]) else hero
        return render_template("index.html", objects=cards, featured=featured, selected=None, hero=hero,
                               og_image=og, price_from=min(c["price_from"] for c in cards),
                               periods=db_.periods(db), gallery_photos=gallery.photos(site.media("gallery")),
                               **common_page_data(db, site, cards))

    @app.get("/<slug>")
    def object_page(slug):
        if slug == "admin":  # /admin без скісної риски
            return redirect(url_for("admin.index"))
        if slug not in site.object_by_key:
            abort(404)
        db = db_.get_db()
        cards = object_cards(db, site)
        obj = next((c for c in cards if c["slug"] == slug), None)
        if obj is None:
            abort(404)
        return render_template("object.html", obj=obj, objects=cards, selected=obj,
                               og_image=obj["cover"] or gallery.first(site.media("hero")),
                               periods=[p for p in db_.periods(db) if p["objectId"] in (None, obj["id"])],
                               **common_page_data(db, site, cards))

    @app.get("/favicon.svg")
    def favicon():
        return Response(favicon_svg(site.brand), mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/robots.txt")
    def robots():
        return Response("User-agent: *\nDisallow: /admin/\nDisallow: /api/\n", mimetype="text/plain")

    @app.get("/api/availability")
    def availability():
        db = db_.get_db()
        today = today_iso()
        last = (date.fromisoformat(today) + timedelta(days=BOOKING_HORIZON_DAYS)).isoformat()
        return jsonify(busy=db_.busy_json(db), objects=db_.objects_json(db), periods=db_.periods(db),
                       extras=db_.extras_list(db), config=site.public_rules(), today=today, lastDate=last)

    @app.post("/api/bookings")
    def book():
        if not csrf_ok():
            return jsonify(ok=False, error="Сесія застаріла. Оновіть сторінку та спробуйте ще раз."), 400
        body = request.get_json(silent=True) or {}
        if body.get("website"):  # приховане поле-пастка для ботів
            return jsonify(ok=False, error="Помилка"), 400
        if rate_limited():
            return jsonify(ok=False, error="Забагато заявок. Спробуйте пізніше або зателефонуйте нам."), 429
        db = db_.get_db()
        try:
            data = validate_booking(body, db_.objects(db), list(site.extra_by_key), today_iso())
            booking = db_.create_booking(db, data)
        except db_.BookingError as e:
            return jsonify(ok=False, error=str(e)), e.status
        notification_id = notifications.queue(db, booking, site.brand["name"])
        notifications.send_async(app.config["DATABASE"], notification_id)
        return jsonify(ok=True, booking=booking), 201

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith(("/api/", "/admin/api/")):
            return jsonify(ok=False, error="Not found"), 404
        return render_template("404.html"), 404


def _create_default_app():
    try:
        return create_app()
    except site_config.ConfigError as exc:
        raise SystemExit(f"\n{exc}\n\nВиправте конфіг і перевірте: python manage.py validate\n")


# Для wsgi-сервера (gunicorn, PythonAnywhere) і запуску `python app.py`.
app = None if os.environ.get("YALOTT_NO_APP") == "1" else _create_default_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
