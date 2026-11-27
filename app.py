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
from datetime import date, datetime, timedelta

import click
from flask import (Flask, Response, abort, jsonify, redirect, render_template, request, send_file, session,
                   url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

import database as db_
import demo
import design
import gallery
import notifications
import pricing as P
import security
import seo
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

def client_ip():
    """Справжня IP відвідувача. За вебсервером (Caddy, nginx PythonAnywhere) її підставляє ProxyFix
    з ОСТАННЬОГО запису X-Forwarded-For — того, що дописав наш вебсервер; підробити його відвідувач не може."""
    return request.remote_addr or "?"


def rate_limited():
    """Ліміт у базі, а не в пам'яті процесу: однаковий для всіх воркерів gunicorn і після перезапуску."""
    return security.booking_limited(db_.get_db(), client_ip())


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
    if not isinstance(body, dict):
        raise db_.BookingError("Некоректна заявка")
    for field in ("name", "phone", "comment", "checkIn", "checkOut"):
        if body.get(field) is not None and not isinstance(body.get(field), str):
            raise db_.BookingError("Некоректна заявка")
    name = security.clean_text(body.get("name"), 80)
    phone = security.clean_text(body.get("phone"), 32)
    if len(name) < 2:
        raise db_.BookingError("Вкажіть, будь ласка, ім'я")
    if not 9 <= len(re.sub(r"\D", "", phone)) <= 15 or not re.fullmatch(r"[\d\s()+\-.]+", phone):
        raise db_.BookingError("Вкажіть коректний номер телефону")

    object_id = body.get("objectId")
    obj = objects.get(_int(object_id)) if isinstance(object_id, (int, str)) and not isinstance(object_id, bool) else None
    if obj is None:
        raise db_.BookingError("Оберіть об'єкт для бронювання")

    check_in, check_out = body.get("checkIn"), body.get("checkOut")
    if not _is_date(check_in) or not _is_date(check_out) or check_out <= check_in:
        raise db_.BookingError("Оберіть дати заїзду та виїзду")
    if check_in < today:
        raise db_.BookingError("Дата заїзду вже минула")
    if check_out > (date.fromisoformat(today) + timedelta(days=BOOKING_HORIZON_DAYS)).isoformat():
        raise db_.BookingError("Бронювання відкрите лише на рік уперед")
    # Мінімальний термін (звичайний, на вихідні, особливі періоди з бази) перевіряє db_.create_booking.

    guests = body.get("guests")
    guests = guests if isinstance(guests, int) and not isinstance(guests, bool) else _int(guests if isinstance(guests, str) else None)
    if not 1 <= guests <= obj["maxGuests"]:
        raise db_.BookingError(f"«{obj['name']}»: від 1 до {obj['maxGuests']} гостей")
    extras = body.get("extras") or []
    if not isinstance(extras, list) or len(extras) > 50:
        extras = []
    extras = [k for k in extra_keys if k in [e for e in extras if isinstance(e, str)]]  # лише відомі, без повторів
    if body.get("rules") is not True:
        raise db_.BookingError("Підтвердьте, що ознайомилися з умовами бронювання")
    return {"objectId": obj["id"], "name": name, "phone": phone,
            "comment": security.clean_text(body.get("comment"), 500, multiline=True),
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
    css = "html[data-theme]{" + ";".join(rules) + "}\n" if rules else ""
    if brand.get("hero_focus"):
        # Точка фокусу банера (brand.hero_focus) — для вузького кадру на телефоні. Там вона важливіша за
        # прив'язку до кута з підписом у демо (subtle): інакше банер показує не те, заради чого фото обрано.
        # На широкому екрані кадр майже повний — лишаються правила теми й демо.
        css += ("@media (max-width:760px){html[data-theme] .hero-bg{object-position:"
                f"{brand['hero_focus']} !important}}}}\n")
    return css


def favicon_svg(brand):
    letter = (re.sub(r"[^\w]", "", brand["name"]) or "•")[0].upper()
    if brand["theme"] in design.PALETTES:
        bg = design.derive(design.PALETTES[brand["theme"]])["deep"]
    else:
        bg = brand["primary_color"] or {"dark": "#17181a", "wood": "#3a2a1d", "forest": "#16301f",
                                          "midnight": "#0d1a2e", "cabin": "#1d3326"}[brand["theme"]]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{bg}"/>'
            f'<text x="32" y="44" font-family="Georgia,serif" font-size="36" text-anchor="middle" '
            f'fill="{_contrast(bg)}">{letter}</text></svg>')


# ---------- Застосунок ----------

def create_app(test_config=None):
    test_config = dict(test_config or {})
    instance_path = os.environ.get("INSTANCE_PATH") or os.path.join(BASE_DIR, "instance")
    app = Flask(__name__, instance_path=instance_path)
    # SECRET_KEY — лише з .env: без нього сайт не стартує (security.require_secret_key пояснить, що робити).
    key = security.require_secret_key(test_config.pop("SECRET_KEY", None) or os.environ.get("SECRET_KEY"))
    if security.weak_secret_key(key):
        log.warning("SECRET_KEY коротший за 32 символи — замініть на довший (python manage.py check підкаже як).")

    # Конфіг клієнта. Помилка в ньому зупиняє запуск зі зрозумілим поясненням (python manage.py validate).
    site = site_config.load(test_config.pop("SITE_CONFIG", None))
    app.extensions["site"] = site

    app.config.update(
        SECRET_KEY=key,
        # Окрема база на кожен конфіг: site.yaml → instance/site.db, ramshill.yaml → instance/ramshill.db.
        DATABASE=os.environ.get("DATABASE_PATH") or os.path.join(instance_path, f"{site.key}.db"),
        DEMO_DATA=env_flag("DEMO_DATA", default=False),
        # Cookie входу: лише HTTPS (Secure), недоступна скриптам (HttpOnly), не йде з чужих сайтів (SameSite).
        # Для запуску на своєму комп'ютері по http:// — SESSION_COOKIE_SECURE=0 у .env.
        SESSION_COOKIE_SECURE=env_flag("SESSION_COOKIE_SECURE", default=True),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Вхід в адмінку діє 12 годин; потім — знову пароль (перевіряється й на сервері).
        PERMANENT_SESSION_LIFETIME=timedelta(hours=security.SESSION_HOURS),
        # Більший запит відхиляється одразу (форма бронювання — кілька сотень байтів).
        MAX_CONTENT_LENGTH=security.MAX_REQUEST_BYTES,
    )
    app.json.ensure_ascii = False
    app.config.update(test_config)
    # Сайт працює за ОДНИМ вебсервером (Caddy на VPS, nginx на PythonAnywhere): справжні IP відвідувача й https
    # беруться з X-Forwarded-For / X-Forwarded-Proto, які він додав. BEHIND_PROXY=0 — лише якщо gunicorn
    # відкритий в інтернет напряму (так робити не варто).
    if env_flag("BEHIND_PROXY", default=True):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # База й таблиці створюються автоматично; з конфігу доливається лише те, чого в базі ще немає.
    db_.init_db(app.config["DATABASE"], site, with_demo=app.config["DEMO_DATA"], today=now_local().date())
    db_.ensure_admin(app.config["DATABASE"], demo=app.config["DEMO_DATA"])
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
    # Тема дизайн-системи (design.PALETTES): свої стилі, локальні шрифти, анімації; старі теми — як були.
    ds = ({"preload": design.preload(brand["theme"]),
           "tone": "dark" if design.is_dark(design.PALETTES[brand["theme"]]["c60"]) else "light"}
          if brand["theme"] in design.PALETTES else None)

    demo_on = demo.enabled(site)
    # Адреса сайту для canonical, sitemap і Open Graph — SITE_URL з .env (https://домен, без «/» у кінці).
    # Без неї (чи в демо) — адреса з запиту: за Caddy це справжній домен і https (ProxyFix).
    site_url = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if site_url and not re.fullmatch(r"https?://[A-Za-z0-9.-]+(?::\d+)?", site_url):
        log.warning("SITE_URL=%r — не схоже на https://домен; беру адресу із запиту.", site_url)
        site_url = ""
    app.config["SITE_URL"] = "" if demo_on else site_url
    demo_id = demo.fingerprint(site, key) if demo_on else ""
    demo_hosts = ",".join(demo.host_hash(h) for h in demo.allowed_hosts(site)) if demo_on else ""

    def media_url(src, external=False):
        """Адреса фото. У демо — через /demo-img/: з вшитим водяним знаком, оригінали недоступні."""
        if demo_on:
            return url_for("demo_image", src=src, _external=external)
        return url_for("static", filename=src, _external=external)

    @app.context_processor
    def inject_globals():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(16)
        info = None
        if demo_on:
            grant = session.get("demo") if isinstance(session.get("demo"), dict) else {}
            until = grant.get("exp")
            info = {"id": demo_id, "hosts": demo_hosts, "mark": demo.invisible_mark(demo_id),
                    "domain": site.demo["domain"], "noindex": demo.NOINDEX,
                    "grid": site.demo["watermark"] == "grid", "watermark": site.demo["watermark"],
                    "until": datetime.fromtimestamp(until, TZ).strftime("%d.%m.%Y") if isinstance(until, int) else ""}
        return {"csrf_token": session["csrf"], "current_year": now_local().year, "site": site,
                "brand": brand, "contacts": site.contacts, "rules": site.rules, "sections": site.sections,
                "nav_objects": site.objects, "logo": logo, "logo_light": logo_light, "favicon": favicon,
                "theme_css": bool(overrides), "V": asset_version, "demo": info, "ds": ds}

    def photo_size(src):
        """(ширина, висота) фото — для width/height у <img>, щоб сторінка не «стрибала» під час завантаження."""
        return seo.image_size(os.path.join(BASE_DIR, "static"), src)

    def logo_width(src, height):
        """Ширина логотипа за висоти height — пропорційно до справжнього файлу (0, якщо розмір невідомий)."""
        w, h = photo_size(src)
        return round(w * height / h) if w and h else 0

    app.jinja_env.globals.update(thumb_for=gallery.thumb_for, photo_width=gallery.width, photo_size=photo_size,
                                 logo_width=logo_width,
                                 locality=seo.locality(site), plural=site_config.plural,
                                 guests_gen=site_config.guests_gen, media_url=media_url)
    app.extensions["fh_today"] = lambda: today_iso()  # київська дата для адмінки
    app.extensions["theme_css"] = overrides
    app.extensions["demo_id"] = demo_id
    app.extensions["media_url"] = media_url
    register_routes(app)
    if demo_on:
        register_demo(app, site, key)

    @app.after_request
    def add_security_headers(response):
        """Заголовки безпеки — на кожній відповіді, зокрема на сторінках помилок. Працюють і без Caddy."""
        admin = request.path.startswith("/admin")
        for name, value in security.security_headers(request.is_secure, admin=admin).items():
            response.headers.setdefault(name, value)
        if demo_on:      # демо ніде не індексується й не кешується спільними кешами
            response.headers["X-Robots-Tag"] = demo.NOINDEX
            if request.path.startswith("/demo-img/"):
                response.headers["Cache-Control"] = "private, max-age=3600"
            elif not request.path.startswith(("/static/css/", "/static/js/")):
                response.headers["Cache-Control"] = "private, no-store"
        return response

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
    return security.token_ok(request.headers.get("X-CSRF-Token"), session.get("csrf"))


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
                    weekend_price=p["weekendPrice"], weekend_min_nights=p["weekendMinNights"],
                    guests_text=p["guestsText"], photos=gallery.photos(o["folder"], o["name"]),
                    cover=gallery.cover(o))
        place = seo.locality(site)
        card["cover_alt"] = f"{o['name']} — {site.brand['name']}" + (f", {place}" if place else "")
        card["facts"] = object_facts(card)
        cards.append(card)
    return cards


def common_page_data(db, site, cards):
    extras = [dict(e, photo_src=gallery.find(site.media("extras"), e["photo"])) for e in db_.extras_list(db)]
    times = {(c["check_in"], c["check_out"]) for c in cards}
    rules, today = db_.min_stay_rules(db), today_iso()
    live = db_.objects(db)
    # Мінімальний термін біля форми: «Мінімальний термін бронювання — 2 ночі, на Новий рік — 5 ночей.»
    notes = {c["id"]: P.min_stay_note(live[c["id"]], rules, today) for c in cards}
    holidays = []   # для блоку «Умови»: особливі періоди, що ще не минули
    for c in cards:
        for r in P.applicable_rules(live[c["id"]], rules, today):
            if r["objectId"] is None and any(h["rule"] is r for h in holidays):
                continue
            phrase, after = P.rule_phrase(r), (date.fromisoformat(r["end"]) + timedelta(days=1)).isoformat()
            when = (f"ніч {P._ddmm(r['start'])}→{P._ddmm(after)}" if r["start"] == r["end"]
                    else f"хоч одну ніч з {P._ddmm(r['start'])} до {P._ddmm(after)}")
            holidays.append({"rule": r, "object": None if r["objectId"] is None else c["name"],
                             "text": f"{phrase[0].upper()}{phrase[1:]} — від {r['minNights']} "
                                     f"{P.nights_word(r['minNights'])}, якщо бронювання включає {when}."})
    return {"extras": extras, "same_times": len(times) <= 1, "min_stay_notes": notes, "min_stay_holidays": holidays,
            "min_nights_max": max((max(c["min_nights"], c["weekend_min_nights"] or 0) for c in cards), default=1)}


def hero_for(site, cards):
    """Фото банера: media/hero/ або обкладинка головного (першого) об'єкта."""
    featured = next((c for c in cards if c["featured"]), None)
    return gallery.first(site.media("hero")) or (featured or (cards[0] if cards else {})).get("cover")


def base_url(app):
    """https://домен сайту без «/» у кінці: SITE_URL з .env або адреса з запиту."""
    return app.config.get("SITE_URL") or request.url_root.rstrip("/")


def page_info(app, title, description, path, og=None, og_alt="", json_ld=(), noindex=False):
    """Усе для <head>: title, description, canonical, Open Graph, JSON-LD (див. seo.py і _base.html)."""
    base = base_url(app)
    return {"title": title, "description": description, "canonical": base + path, "site_url": base,
            "og_image": base + url_for("og_image", name=og) if og else "", "og_alt": og_alt,
            "json_ld": [x for x in json_ld if x], "noindex": noindex}


def absolute_images(app, srcs):
    media_url, base = app.extensions["media_url"], base_url(app)
    return [base + media_url(s) for s in srcs if s]


def register_routes(app):
    site = app.extensions["site"]
    static_dir = os.path.join(BASE_DIR, "static")

    @app.get("/")
    def index():
        db = db_.get_db()
        cards = object_cards(db, site)
        if not cards:
            abort(404)
        featured = next((c for c in cards if c["featured"]), None)
        hero = hero_for(site, cards)
        hero_mobile = gallery.first(site.media("hero") + "/mobile")   # вертикальне фото для телефона (необов'язково)
        price_from = min(c["price_from"] for c in cards)
        title, description = seo.home_meta(site, price_from)
        images = absolute_images(app, [hero] + [c["cover"] for c in cards])
        page = page_info(app, title, description, "/", og="home" if og_source(site, cards, "home") else None,
                         og_alt=f"{site.brand['full_name']} — {seo.locality(site)}".strip(" —"),
                         json_ld=[seo.lodging(site, base_url(app), cards, images)])
        return render_template("index.html", objects=cards, featured=featured, selected=None, hero=hero,
                               hero_mobile=hero_mobile, page=page, price_from=price_from,
                               periods=db_.periods(db), gallery_photos=gallery.photos(site.media("gallery"),
                                                                                       site.brand["name"]),
                               **common_page_data(db, site, cards))

    @app.get(f"/{seo.CONTACTS_SLUG}")
    def contacts_page():
        db = db_.get_db()
        cards = object_cards(db, site)
        title, description = seo.contacts_meta(site)
        base = base_url(app)
        images = absolute_images(app, [hero_for(site, cards)] + [c["cover"] for c in cards])
        page = page_info(app, title, description, f"/{seo.CONTACTS_SLUG}",
                         og=seo.CONTACTS_SLUG if og_source(site, cards, seo.CONTACTS_SLUG) else None,
                         og_alt=f"{site.brand['full_name']} — як доїхати",
                         json_ld=[seo.lodging(site, base, cards, images),
                                  seo.breadcrumbs(base, site.brand["name"], [(f"/{seo.CONTACTS_SLUG}", "Контакти")])])
        return render_template("contacts.html", objects=cards, selected=None, page=page,
                               booking_href=url_for("index") + "#booking")

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
        title, description = seo.object_meta(site, obj)
        base = base_url(app)
        images = absolute_images(app, [obj["cover"]] + [p["src"] for p in obj["photos"]])
        page = page_info(app, title, description, f"/{slug}", og=slug if og_source(site, cards, slug) else None,
                         og_alt=obj["cover_alt"],
                         json_ld=[seo.accommodation(site, base, obj, list(dict.fromkeys(images))),
                                  seo.breadcrumbs(base, site.brand["name"], [(f"/{slug}", obj["name"])])])
        return render_template("object.html", obj=obj, objects=cards, selected=obj, page=page,
                               periods=[p for p in db_.periods(db) if p["objectId"] in (None, obj["id"])],
                               **common_page_data(db, site, cards))

    def og_source(site_, cards, name):
        """Фото для картинки соцмереж: своє (seo.og_image) / обкладинка котеджу / банер."""
        if name == "home" and gallery.exists(site_.seo["og_image"]):
            return site_.seo["og_image"]
        if name in site_.object_by_key:
            card = next((c for c in cards if c["slug"] == name), None)
            if card and card["cover"]:
                return card["cover"]
        return hero_for(site_, cards)

    @app.get("/og/<name>.jpg")
    def og_image(name):
        """Картинка для Viber, Telegram, Facebook: JPEG 1200×630 з фото сторінки (кеш у instance/og-cache)."""
        if name not in ("home", seo.CONTACTS_SLUG) and name not in site.object_by_key:
            abort(404)
        src = og_source(site, object_cards(db_.get_db(), site), name)
        if not src:
            abort(404)
        focus = site.brand.get("hero_focus", "") if src == hero_for(site, object_cards(db_.get_db(), site)) else ""
        path = seo.og_image(os.path.join(static_dir, src), os.path.join(app.instance_path, "og-cache"), focus)
        return send_file(path, mimetype="image/jpeg", max_age=86400, conditional=True)

    @app.get("/sitemap.xml")
    def sitemap():
        if demo.enabled(site):          # демо не індексується
            abort(404)
        cards = object_cards(db_.get_db(), site)
        base, config_file = base_url(app), site.path
        hero = hero_for(site, cards)
        pages = [{"loc": f"{base}/", "lastmod": seo.lastmod(config_file, os.path.join(static_dir, site.media("hero"))),
                  "images": absolute_images(app, [hero] + [c["cover"] for c in cards]
                                            + [p["src"] for p in gallery.photos(site.media("gallery"))])}]
        pages += [{"loc": f"{base}/{c['slug']}", "lastmod": seo.lastmod(config_file, os.path.join(static_dir, c["folder"])),
                   "images": absolute_images(app, list(dict.fromkeys([c["cover"]] + [p["src"] for p in c["photos"]])))}
                  for c in cards]
        pages.append({"loc": f"{base}/{seo.CONTACTS_SLUG}", "lastmod": seo.lastmod(config_file), "images": []})
        return Response(seo.sitemap_xml(pages), mimetype="application/xml")

    @app.get("/favicon.svg")
    def favicon():
        return Response(favicon_svg(site.brand), mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/theme.css")
    def theme_css():
        """Свої кольори з конфігу (brand.primary_color / accent_color) — окремим файлом, а не вбудованим <style>:
        Content-Security-Policy забороняє вбудовані стилі й скрипти."""
        return Response(app.extensions["theme_css"], mimetype="text/css",
                        headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/robots.txt")
    def robots():
        # звичайний сайт — індексувати все, крім адмінки й API, і ось карта сайту; демо — нічого
        return Response(seo.robots_txt(base_url(app), closed=demo.enabled(site)), mimetype="text/plain")

    @app.get("/api/availability")
    def availability():
        db = db_.get_db()
        today = today_iso()
        last = (date.fromisoformat(today) + timedelta(days=BOOKING_HORIZON_DAYS)).isoformat()
        return jsonify(busy=db_.busy_json(db), objects=db_.objects_json(db), periods=db_.periods(db),
                       minStay=db_.min_stay_rules(db), extras=db_.extras_list(db), config=site.public_rules(), today=today, lastDate=last)

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
        name = ("🧪 ДЕМО · " if demo.enabled(site) else "") + site.brand["name"]
        notification_id = notifications.queue(db, booking, name)
        notifications.send_async(app.config["DATABASE"], notification_id)
        return jsonify(ok=True, booking=booking), 201

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith(("/api/", "/admin/api/")):
            return jsonify(ok=False, error="Not found"), 404
        return render_template("404.html"), 404


def register_demo(app, site, secret):
    """Демо-режим (demo.enabled у конфігу): доступ за посиланням, пароль, фото з водяним знаком, свій домен."""
    cache_dir = os.path.join(app.instance_path, "demo-cache")
    static_dir = os.path.join(BASE_DIR, "static")

    def locked(reason, status=403):
        return render_template("demo_locked.html", reason=reason, studio=site.studio), status

    @app.before_request
    def demo_gate():
        if not demo.host_ok(site, request.host):
            return locked("domain")
        path = request.path
        # оригінали фото в демо не віддаються — лише через /demo-img/ з водяним знаком
        if path.startswith("/static/media/") and not path.startswith("/static/media/brand/"):
            abort(404)
        if demo.is_open_path(path):
            return None
        reason = demo.access(site, session, secret)
        if reason == "password":
            return redirect(url_for("demo_password"))
        if reason:
            if path.startswith(("/api/", "/admin/api/")):
                return jsonify(ok=False, error="Демо-доступ завершився. Відкрийте посилання ще раз."), 403
            return locked(reason)
        return None

    @app.get("/demo/<token>")
    def demo_enter(token):
        reason, expires = demo.read_link_token(site, secret, token)
        if reason:
            return locked(reason)
        session["demo"] = {"v": site.demo["link_version"], "exp": expires,
                           "pw": session.get("demo", {}).get("pw", "") if isinstance(session.get("demo"), dict) else ""}
        session.permanent = True
        return redirect(url_for("demo_password") if demo.access(site, session, secret) == "password" else url_for("index"))

    @app.route("/demo/password", methods=["GET", "POST"])
    def demo_password():
        grant = session.get("demo")
        if not isinstance(grant, dict) or demo.access(site, session, secret) not in (None, "password"):
            return locked(demo.access(site, session, secret) or "no-link")
        if not demo.password():
            return redirect(url_for("index"))
        error, status = "", 200
        if request.method == "POST":
            db = db_.get_db()
            ip = client_ip()
            if not security.token_ok(request.form.get("csrf"), session.get("csrf")):
                error, status = "Сесія застаріла — спробуйте ще раз.", 400
            elif security.wait_seconds(db, "demo-ip", ip, demo.DEMO_PASSWORD_ATTEMPTS, security.LOGIN_WINDOW):
                error, status = "Забагато спроб. Спробуйте пізніше.", 429
            elif security.token_ok(request.form.get("password"), demo.password()):
                grant["pw"] = demo.password_mark(secret)
                session["demo"] = grant
                return redirect(url_for("index"))
            else:
                security.record(db, "demo-ip", ip)
                error, status = "Неправильний пароль.", 401
        return render_template("demo_locked.html", reason="password", error=error, studio=site.studio), status

    @app.get("/demo-img/<path:src>")
    def demo_image(src):
        path = demo.cached_watermark(static_dir, cache_dir, src, app.extensions["demo_id"], site.demo["domain"],
                                     site.demo["watermark"])
        if path is None:
            abort(404)
        return send_file(path, mimetype="image/webp", max_age=0, conditional=True)


def _create_default_app():
    try:
        return create_app()
    except security.SecurityConfigError as exc:
        raise SystemExit(f"\n{exc}\n")
    except site_config.ConfigError as exc:
        raise SystemExit(f"\n{exc}\n\nВиправте конфіг і перевірте: python manage.py validate\n")


# Для wsgi-сервера (gunicorn, PythonAnywhere) і запуску `python app.py`.
app = None if os.environ.get("YALOTT_NO_APP") == "1" else _create_default_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
