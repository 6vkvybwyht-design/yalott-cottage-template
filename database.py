"""Робота з базою SQLite: підключення, таблиці, початкові дані з конфігу (seed) та запити.

Хто за що відповідає:
  • конфіг (config/site.yaml) — назви, описи, фото, правила + ПОЧАТКОВІ ціни й параметри;
  • база — ціни, гості, одиниці, мінімум ночей, сезони, ціни послуг (після seed їх змінює адмінка),
    бронювання, закриті ночі, сповіщення, адміністратори.
"""

import json
import logging
import os
import secrets
import sqlite3
from datetime import date, timedelta

from flask import current_app, g

import pricing as P
from site_config import guests_gen

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIVE = ("new", "confirmed")
STATUSES = ("new", "confirmed", "cancelled")
SCHEMA_VERSION = 3
OWNER_SOURCES = ("owner", "demo")   # закриття, якими керує власник в адмінці


class BookingError(Exception):
    """Помилка, яку можна показати гостю чи власнику (з HTTP-статусом)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def site():
    """Конфіг поточного сайту (SiteConfig)."""
    return current_app.extensions["site"]


# ---------- Підключення ----------

def get_db():
    """Одне з'єднання на запит. isolation_level=None — транзакціями керуємо вручну."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


# ---------- Створення бази й початкові дані ----------

def init_db(path, cfg, with_demo=False, today=None):
    """Створює базу й таблиці, якщо їх ще немає, і доливає з конфігу те, чого в базі бракує."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = connect(path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "objects" in tables and "key" not in _columns(conn, "objects"):
            raise RuntimeError(
                f"База {path} створена старою версією сайту й несумісна із шаблоном. "
                f"Вкажіть інший файл у DATABASE_PATH або перейменуйте стару базу.")
        with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        report = seed(conn, cfg)
        if with_demo:
            seed_demo(conn, cfg, today or date.today())
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return report
    finally:
        conn.close()


def _season_key(s):
    return f"{s['object'] or '*'}|{s['name']}|{s['start']}|{s['end']}"


def seed(conn, cfg, reset=False):
    """Заливає конфіг у базу. Безпечно запускати скільки завгодно разів.

    Звичайний режим: додає лише те, чого в базі ще немає (нові об'єкти, послуги, сезони).
    Ціни й параметри, які вже є в базі (і, можливо, змінені в адмінці), НЕ чіпає.
    Сезон заливається один раз: якщо власник видалив його в адмінці, seed його не поверне.

    reset=True — свідоме скидання: ціни й параметри об'єктів, ціни послуг і ВСІ сезони
    беруться з конфігу заново. Бронювання й закриті ночі не змінюються ніколи.

    Повертає звіт: {"added": [...], "kept": [...], "updated": [...], "skipped": [...]}.
    """
    report = {"added": [], "kept": [], "updated": [], "skipped": []}
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = {r["key"]: r for r in conn.execute("SELECT * FROM objects")}
        for o in cfg.objects:
            values = (o["units"], o["price"], o["base_guests"], o["max_guests"], o["extra_guest_price"],
                      o["min_nights"], json.dumps(o["tiers"]))
            if o["key"] not in rows:
                conn.execute("INSERT INTO objects (units, price, base_guests, max_guests, extra_guest_price, "
                             "min_nights, tiers, key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*values, o["key"]))
                report["added"].append(f"об'єкт «{o['name']}» — {P.format_uah(o['price'])} / ніч")
            elif reset:
                conn.execute("UPDATE objects SET units = ?, price = ?, base_guests = ?, max_guests = ?, "
                             "extra_guest_price = ?, min_nights = ?, tiers = ? WHERE key = ?", (*values, o["key"]))
                report["updated"].append(f"об'єкт «{o['name']}» — ціни й параметри з конфігу")
            else:
                r = rows[o["key"]]
                note = "" if r["price"] == o["price"] else f" (у базі {P.format_uah(r['price'])}, у конфігу {P.format_uah(o['price'])})"
                report["kept"].append(f"об'єкт «{o['name']}»{note}")
            conn.execute("INSERT OR IGNORE INTO seed_log (kind, key) VALUES ('object', ?)", (o["key"],))
        for key in rows:
            if key not in cfg.object_by_key:
                report["skipped"].append(f"об'єкт «{key}» є в базі, але його немає в конфігу — на сайті прихований, "
                                         f"бронювання збережено")

        have = {r["key"] for r in conn.execute("SELECT key FROM extras")}
        for e in cfg.extras:
            values = (e["price"], json.dumps(e["guest_prices"]))
            if e["key"] not in have:
                conn.execute("INSERT INTO extras (price, guest_prices, key) VALUES (?, ?, ?)", (*values, e["key"]))
                report["added"].append(f"послуга «{e['name']}» — {P.format_uah(e['price'])}")
            elif reset:
                conn.execute("UPDATE extras SET price = ?, guest_prices = ? WHERE key = ?", (*values, e["key"]))
                report["updated"].append(f"послуга «{e['name']}» — ціна з конфігу")
            else:
                report["kept"].append(f"послуга «{e['name']}»")
            conn.execute("INSERT OR IGNORE INTO seed_log (kind, key) VALUES ('extra', ?)", (e["key"],))

        if reset:
            conn.execute("DELETE FROM periods")
            conn.execute("DELETE FROM seed_log WHERE kind = 'season'")
        ids = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM objects")}
        done = {r["key"] for r in conn.execute("SELECT key FROM seed_log WHERE kind = 'season'")}
        for s in cfg.seasons:
            key = _season_key(s)
            title = f"сезон «{s['name']}» {s['start']} – {s['end']}" + (f" ({s['object']})" if s["object"] else "")
            if key in done:
                report["kept"].append(title)
                continue
            object_id = ids[s["object"]] if s["object"] else None
            clash = conn.execute(
                "SELECT name FROM periods WHERE object_id IS ? AND start_date <= ? AND end_date >= ?",
                (object_id, s["end"], s["start"])).fetchone()
            if clash:
                report["skipped"].append(f"{title} — перетинається із сезоном «{clash['name']}», який уже є в базі")
                continue
            conn.execute("INSERT INTO periods (object_id, name, start_date, end_date, price) VALUES (?, ?, ?, ?, ?)",
                         (object_id, s["name"], s["start"], s["end"], s["price"]))
            conn.execute("INSERT INTO seed_log (kind, key) VALUES ('season', ?)", (key,))
            price = P.format_uah(s["price"]) if s["price"] else "за домовленістю"
            report["added"].append(f"{title} — {price}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return report


def seed_demo(conn, cfg, today):
    """DEMO_DATA=1: зайняті вихідні на 8 тижнів уперед і дві заявки — щоб показати клієнту живий сайт.

    Додається один раз і лише в базу без бронювань. Прибрати: python manage.py seed --clear-demo.
    """
    if conn.execute("SELECT 1 FROM seed_log WHERE kind = 'demo'").fetchone():
        return False
    if any(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("bookings", "blocked_nights")):
        return False
    rows = [r for r in conn.execute("SELECT * FROM objects ORDER BY id") if r["key"] in cfg.object_by_key]
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for i, r in enumerate(rows):
            for week in range(8):
                if (week + i) % 3 == 2:
                    continue  # ці вихідні лишаються вільними
                closed = max(1, r["units"] - (week + i) % 2)   # у кількох одиниць інколи лишається вільна
                for offset in (0, 1):
                    night = friday + timedelta(days=7 * week + offset)
                    conn.execute("INSERT OR IGNORE INTO blocked_nights (date, object_id, source, units, reason) "
                                 "VALUES (?, ?, 'demo', ?, 'Демо: зайнято')", (night.isoformat(), r["id"], closed))
        monday = today + timedelta(days=7 - today.weekday())
        guests = (("Олена (демо)", "+380 67 000 00 01", "new", 8), ("Андрій (демо)", "+380 50 000 00 02", "confirmed", 15))
        for i, (name, phone, status, shift) in enumerate(guests):
            r = rows[i % len(rows)]
            obj = _object_dict(cfg.object_by_key[r["key"]], r)
            start = monday + timedelta(days=shift)   # вівторок–четвер: не перетинається з вихідними
            data = {"checkIn": start.isoformat(), "checkOut": (start + timedelta(days=max(2, obj["minNights"]))).isoformat(),
                    "guests": obj["baseGuests"], "extras": [], "name": name, "phone": phone,
                    "comment": "Демо-заявка для показу адмінки."}
            _insert_booking(conn, cfg, obj, periods(conn), extras_list(conn, cfg), data, status=status, source="demo")
        conn.execute("INSERT INTO seed_log (kind, key) VALUES ('demo', '1')")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return True


def clear_demo(conn):
    """Прибирає демо-зайнятість і демо-заявки. Справжні бронювання не чіпає."""
    blocked = conn.execute("DELETE FROM blocked_nights WHERE source = 'demo'").rowcount
    bookings = conn.execute("DELETE FROM bookings WHERE source = 'demo'").rowcount
    conn.execute("INSERT OR IGNORE INTO seed_log (kind, key) VALUES ('demo', '1')")  # щоб не з'явилися знову
    return blocked, bookings


# ---------- Адміністратори ----------

DEMO_ADMIN = ("admin", "demo2026")


def ensure_admin(path):
    """Створює першого адміністратора з ADMIN_USERNAME / ADMIN_PASSWORD (з файлу .env).

    Без них — демо-доступ admin / demo2026. Якщо ADMIN_PASSWORD задали пізніше,
    а в базі ще стоїть демо-пароль, його буде замінено. Пароль, змінений командою
    set-password, файл .env не перезаписує.
    """
    from werkzeug.security import check_password_hash, generate_password_hash

    username = os.environ.get("ADMIN_USERNAME", "").strip() or DEMO_ADMIN[0]
    password = os.environ.get("ADMIN_PASSWORD", "")
    if password and len(password) < 8:
        log.warning("ADMIN_PASSWORD коротший за 8 символів — оберіть надійніший пароль.")

    conn = connect(path)
    try:
        if conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0] == 0:
            conn.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                         (username, generate_password_hash(password or DEMO_ADMIN[1])))
            if not password:
                log.warning("ADMIN_PASSWORD не задано — створено демо-доступ %s / %s.", *DEMO_ADMIN)
            return
        if not password:
            return
        user = conn.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
        if user is None:
            demo = conn.execute("SELECT * FROM admin_users WHERE username = ?", (DEMO_ADMIN[0],)).fetchone()
            if demo and check_password_hash(demo["password_hash"], DEMO_ADMIN[1]):
                conn.execute("UPDATE admin_users SET username = ?, password_hash = ? WHERE id = ?",
                             (username, generate_password_hash(password), demo["id"]))
        elif check_password_hash(user["password_hash"], DEMO_ADMIN[1]):
            conn.execute("UPDATE admin_users SET password_hash = ? WHERE id = ?",
                         (generate_password_hash(password), user["id"]))
    finally:
        conn.close()


def set_password(path, username, password):
    from werkzeug.security import generate_password_hash
    conn = connect(path)
    try:
        conn.execute(
            """INSERT INTO admin_users (username, password_hash) VALUES (?, ?)
               ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash""",
            (username, generate_password_hash(password)))
    finally:
        conn.close()


# ---------- Об'єкти й ціни ----------

def _tiers(raw):
    try:
        tiers = [{"nights": int(t["nights"]), "price": int(t["price"])} for t in json.loads(raw)]
    except (ValueError, TypeError, KeyError):
        return []
    return sorted(tiers, key=lambda t: t["nights"])


def _guest_prices(raw):
    try:
        tiers = [{"upTo": int(t["upTo"]), "price": int(t["price"])} for t in json.loads(raw)]
    except (ValueError, TypeError, KeyError):
        return []
    return sorted(tiers, key=lambda t: t["upTo"])


def guests_text(base, top):
    text = f"до {top} {guests_gen(top) if top != 1 else 'гостя'}"
    return text if base >= top else f"{text}, ціна за {base}"


def _object_dict(o, r):
    """Тексти з конфігу (o) + ціни й параметри з бази (r) → те, що потрібно для розрахунку й браузеру."""
    return {
        "id": r["id"], "key": o["key"], "slug": o["slug"], "name": o["name"], "short": o["short"], "tone": o["tone"],
        "units": r["units"], "price": r["price"], "tiers": _tiers(r["tiers"]),
        "baseGuests": r["base_guests"], "maxGuests": r["max_guests"], "extraGuestPrice": r["extra_guest_price"],
        "minNights": r["min_nights"], "guestsText": guests_text(r["base_guests"], r["max_guests"]),
        "checkIn": o["check_in"], "checkOut": o["check_out"],
    }


def objects(db, cfg=None):
    """Усі об'єкти сайту в порядку конфігу: {id: {...}}."""
    cfg = cfg or site()
    rows = {r["key"]: r for r in db.execute("SELECT * FROM objects")}
    out = {}
    for o in cfg.objects:
        r = rows.get(o["key"])
        if r is not None:
            out[r["id"]] = _object_dict(o, r)
    return out


def get_object(db, object_id):
    obj = objects(db).get(object_id)
    if obj is None:
        raise BookingError("Оберіть об'єкт")
    return obj


def objects_json(db):
    return {str(k): v for k, v in objects(db).items()}


def save_object_settings(db, object_id, data):
    """Ціна, знижки за тривалість, гості, одиниці, мінімум ночей — усе, що власник змінює в адмінці.

    tiers: [{"nights": 2, "price": 2200}, ...] — пороги ночей мають бути різні й більші за 1.
    """
    current = get_object(db, object_id)
    seen = set()
    for t in data["tiers"]:
        if t["nights"] < 2 or t["nights"] > 60:
            raise BookingError("Поріг знижки — від 2 до 60 ночей")
        if t["nights"] in seen:
            raise BookingError(f"Поріг «від {t['nights']} ночей» указано двічі")
        seen.add(t["nights"])
    base = data.get("baseGuests", current["baseGuests"])
    top = data.get("maxGuests", current["maxGuests"])
    if base > top:
        raise BookingError("Гостей у базовій ціні не може бути більше, ніж максимум гостей")
    db.execute(
        "UPDATE objects SET price = ?, tiers = ?, extra_guest_price = ?, min_nights = ?, base_guests = ?, "
        "max_guests = ?, units = ? WHERE id = ?",
        (data["price"], json.dumps(sorted(data["tiers"], key=lambda t: t["nights"])),
         data.get("extraGuestPrice", current["extraGuestPrice"]), data.get("minNights", current["minNights"]),
         base, top, data.get("units", current["units"]), object_id))


# ---------- Додаткові послуги ----------

def extras_list(db, cfg=None):
    """[{key, name, price, unit, unitLabel, guestPrices, …}] — описи з конфігу, ціни з бази."""
    cfg = cfg or site()
    rows = {r["key"]: r for r in db.execute("SELECT * FROM extras")}
    out = []
    for e in cfg.extras:
        r = rows.get(e["key"])
        if r is None:
            continue
        tiers = _guest_prices(r["guest_prices"])
        out.append({"key": e["key"], "name": e["name"], "description": e["description"], "icon": e["icon"],
                    "photo": e["photo"], "unit": e["unit"], "unitLabel": e["unit_label"], "price": r["price"],
                    "guestPrices": tiers, "priceFrom": min([t["price"] for t in tiers] or [r["price"]])})
    return out


def save_extra_price(db, key, price, guest_prices=None):
    if key not in site().extra_by_key:
        raise BookingError("Невідома послуга")
    if guest_prices is None:
        db.execute("UPDATE extras SET price = ? WHERE key = ?", (price, key))
        return
    last = 0
    for t in guest_prices:
        if t["upTo"] <= last:
            raise BookingError("Пороги «до N гостей» мають зростати")
        last = t["upTo"]
    db.execute("UPDATE extras SET price = ?, guest_prices = ? WHERE key = ?", (price, json.dumps(guest_prices), key))


# ---------- Сезони ----------

def period_to_dict(r):
    return {"id": r["id"], "objectId": r["object_id"], "name": r["name"], "start": r["start_date"],
            "end": r["end_date"], "price": r["price"]}


def periods(db):
    return [period_to_dict(r) for r in db.execute("SELECT * FROM periods ORDER BY start_date, object_id")]


def save_period(db, data, period_id=None):
    """Додає або змінює сезон. Сезони одного об'єкта (і «для всіх») не можуть перетинатися."""
    if data["objectId"] is not None:
        get_object(db, data["objectId"])
    db.execute("BEGIN IMMEDIATE")
    try:
        clash = db.execute(
            "SELECT name, start_date FROM periods WHERE object_id IS ? AND start_date <= ? AND end_date >= ? "
            "AND id IS NOT ?", (data["objectId"], data["end"], data["start"], period_id)).fetchone()
        if clash:
            raise BookingError(f"Сезон перетинається з «{clash['name'] or clash['start_date']}»", 409)
        values = (data["objectId"], data["name"], data["start"], data["end"], data["price"])
        if period_id:
            cur = db.execute("UPDATE periods SET object_id = ?, name = ?, start_date = ?, end_date = ?, price = ? "
                             "WHERE id = ?", (*values, period_id))
            if cur.rowcount == 0:
                raise BookingError("Сезон не знайдено", 404)
        else:
            period_id = db.execute("INSERT INTO periods (object_id, name, start_date, end_date, price) "
                                   "VALUES (?, ?, ?, ?, ?)", values).lastrowid
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return period_id


def delete_period(db, period_id):
    db.execute("DELETE FROM periods WHERE id = ?", (period_id,))


# ---------- Зайнятість ----------

def _code(prefix):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(8))


def occupancy(db, exclude_code=None):
    """{id об'єкта: {ніч: скільки одиниць зайнято}} — активні бронювання + закриті ночі."""
    out = {}
    for r in db.execute("SELECT date, object_id, SUM(units) AS n FROM blocked_nights GROUP BY date, object_id"):
        out.setdefault(r["object_id"], {})[r["date"]] = r["n"]
    rows = db.execute("SELECT check_in, check_out, object_id FROM bookings WHERE status IN (?, ?) AND code IS NOT ?",
                      (*ACTIVE, exclude_code))
    for r in rows:
        nights = out.setdefault(r["object_id"], {})
        for n in P.nights_between(r["check_in"], r["check_out"]):
            nights[n] = nights.get(n, 0) + 1
    return out


def busy(db):
    """{id: set(ночей)} — ночі, коли зайняті ВСІ одиниці об'єкта (тобто забронювати не можна)."""
    occ = occupancy(db)
    return {oid: {n for n, count in occ.get(oid, {}).items() if count >= o["units"]}
            for oid, o in objects(db).items()}


def busy_json(db):
    return {str(o): sorted(n) for o, n in busy(db).items()}


# ---------- Бронювання ----------

def _insert_booking(db, cfg, obj, all_periods, all_extras, data, status="new", source="site"):
    q = P.quote(obj, all_periods, all_extras, data["checkIn"], data["checkOut"], data["guests"],
                data.get("extras", []), cfg.rules["prepayment_percent"])
    q["objectName"] = obj["name"]   # назва на момент заявки — лишиться, навіть якщо об'єкт перейменують
    code = _code(cfg.brand["booking_prefix"])
    db.execute(
        """INSERT INTO bookings (code, object_id, check_in, check_out, nights, guests, extras, guest_name,
               guest_phone, comment, price_on_request, total_price, prepayment, quote_json, status, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (code, obj["id"], data["checkIn"], data["checkOut"], q["nights"], q["guests"],
         json.dumps([e["key"] for e in q["extras"]]), data["name"], data["phone"], data.get("comment", ""),
         int(q["onRequest"]), q["total"], q["prepayment"], json.dumps(q, ensure_ascii=False), status, source))
    return code


def create_booking(db, data):
    """Атомарно перевіряє, чи є вільна одиниця, рахує ціну й зберігає заявку. Повертає бронювання (dict).

    BEGIN IMMEDIATE бере блокування запису на всю базу: дві одночасні заявки на останню вільну
    одиницю виконуються по черзі, і друга отримує «вже зайнято».
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        obj = get_object(db, data["objectId"])
        if not P.is_free(occupancy(db).get(obj["id"], {}), obj["units"], data["checkIn"], data["checkOut"]):
            raise BookingError(f"На жаль, «{obj['name']}» на ці дати вже зайнято. Оберіть інші дати.", 409)
        code = _insert_booking(db, site(), obj, periods(db), extras_list(db), data)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return get_booking(db, code)


def booking_to_dict(r, names=None):
    q = json.loads(r["quote_json"] or "{}")
    names = names or {}
    return {
        "id": r["code"], "status": r["status"], "source": r["source"],
        "objectId": r["object_id"],
        "objectName": names.get(r["object_id"]) or q.get("objectName") or f"Об'єкт {r['object_id']}",
        "name": r["guest_name"], "phone": r["guest_phone"], "comment": r["comment"],
        "checkIn": r["check_in"], "checkOut": r["check_out"], "nights": r["nights"], "guests": r["guests"],
        "extras": [e["name"] for e in q.get("extras", [])],
        "onRequest": bool(r["price_on_request"]), "total": r["total_price"], "prepayment": r["prepayment"],
        "price": q,
        "createdAt": r["created_at"],
    }


def _names(db):
    return {oid: o["name"] for oid, o in objects(db).items()}


def get_booking(db, code):
    r = db.execute("SELECT * FROM bookings WHERE code = ?", (code,)).fetchone()
    return booking_to_dict(r, _names(db)) if r else None


def set_status(db, code, status):
    """Єдина точка зміни статусу: нею користується адмінка, а у v2 — і Telegram-бот з кнопками."""
    if status not in STATUSES:
        raise BookingError("Невідомий статус")
    db.execute("BEGIN IMMEDIATE")
    try:
        b = get_booking(db, code)
        if b is None:
            raise BookingError("Бронювання не знайдено", 404)
        if b["status"] == "cancelled" and status != "cancelled":
            # відновлення — перевіряємо, чи ще є вільна одиниця на ці ночі
            units = objects(db).get(b["objectId"], {}).get("units", 1)
            taken = occupancy(db, exclude_code=code).get(b["objectId"], {})
            if not P.is_free(taken, units, b["checkIn"], b["checkOut"]):
                raise BookingError("Ці дати вже зайняті іншим бронюванням", 409)
        db.execute("UPDATE bookings SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                   "WHERE code = ?", (status, code))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return get_booking(db, code)


def block_nights(db, dates, object_ids, blocked, count=None):
    """Закриває / відкриває ночі вручну.

    blocked=True без count — закрити всі одиниці, що ще вільні; blocked=False — відкрити все закрите власником.
    count — закрити рівно стільки одиниць (для об'єктів із кількома одиницями; 0 = відкрити).
    """
    objs = objects(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        for o in object_ids:
            units = objs[o]["units"]
            for d in dates:
                db.execute("DELETE FROM blocked_nights WHERE date = ? AND object_id = ? AND source IN (?, ?)",
                           (d, o, *OWNER_SOURCES))
                if not blocked and count is None:
                    continue
                taken = occupancy(db).get(o, {}).get(d, 0)   # бронювання + закриття з інших джерел
                free = max(0, units - taken)
                n = free if count is None else min(max(0, count), free)
                if n > 0:
                    db.execute("INSERT INTO blocked_nights (date, object_id, source, units, reason) "
                               "VALUES (?, ?, 'owner', ?, 'Закрито власником')", (d, o, n))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def admin_data(db):
    objs = objects(db)
    blocked = {str(o): {} for o in objs}
    for r in db.execute("SELECT date, object_id, SUM(units) AS n FROM blocked_nights GROUP BY date, object_id"):
        blocked.setdefault(str(r["object_id"]), {})[r["date"]] = r["n"]
    names = {oid: o["name"] for oid, o in objs.items()}
    return {
        "bookings": [booking_to_dict(r, names) for r in db.execute("SELECT * FROM bookings ORDER BY check_in")],
        "blocked": blocked,
        "occupancy": {str(o): n for o, n in occupancy(db).items()},
        "busy": busy_json(db),
        "objects": {str(k): v for k, v in objs.items()},
        "periods": periods(db),
        "extras": extras_list(db),
        "config": site().public_rules(),
    }

