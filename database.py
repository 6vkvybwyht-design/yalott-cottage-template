"""Робота з базою SQLite: підключення, створення таблиць, початкові дані та запити."""

import json
import logging
import os
import secrets
import sqlite3

from flask import current_app, g

import pricing as P
import site_content

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_FILE = os.path.join(BASE_DIR, "data", "seed.json")
ACTIVE = ("new", "confirmed")
STATUSES = ("new", "confirmed", "cancelled")


class BookingError(Exception):
    """Помилка, яку можна показати гостю чи власнику (з HTTP-статусом)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


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



SCHEMA_VERSION = 2


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_v1(conn):
    """База першої версії (будні/вихідні) → версія 2 (знижки за тривалість, чан і баня).

    Бронювання, закриті доби, сповіщення й адміни зберігаються. Ціни будинків беруться
    нові — з site_content.py; старі сезони замінюються періодами з data/seed.json.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN")
    conn.execute("DROP TABLE IF EXISTS seasons")
    conn.execute("DROP TABLE IF EXISTS objects")
    if "bookings" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
        conn.execute("ALTER TABLE bookings RENAME TO bookings_v1")
    conn.execute("COMMIT")
    conn.execute("PRAGMA foreign_keys = ON")
    log.warning("Базу оновлено до версії %s: ціни будинків — з site_content.py.", SCHEMA_VERSION)


def init_db(path, with_demo=True, seed_path=SEED_FILE):
    """Створює базу й таблиці, якщо їх ще немає. Нову базу заповнює стартовими цінами й даними з seed.json."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = connect(path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "objects" in tables and "tiers" not in _columns(conn, "objects"):
            _migrate_v1(conn)
        with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.execute("BEGIN")
        # Стартові ціни з site_content.py — лише для будинків і послуг, яких ще немає в базі.
        for o in site_content.OBJECTS:
            tiers = [{"nights": n, "price": p} for n, p in o.get("tiers", [])]
            conn.execute("INSERT OR IGNORE INTO objects (id, price, tiers) VALUES (?, ?, ?)",
                         (o["id"], o["price"], json.dumps(tiers)))
        for e in site_content.EXTRAS:
            conn.execute("INSERT OR IGNORE INTO extras (key, price) VALUES (?, ?)", (e["key"], e["price"]))
        if "bookings_v1" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
            conn.execute("""INSERT OR IGNORE INTO bookings (code, object_id, check_in, check_out, nights, guests,
                                guest_name, guest_phone, comment, total_price, prepayment, quote_json, status,
                                created_at, updated_at)
                            SELECT code, object_id, check_in, check_out, nights, guests, guest_name, guest_phone,
                                comment, total_price, prepayment, quote_json, status, created_at, updated_at
                            FROM bookings_v1""")
            conn.execute("DROP TABLE bookings_v1")
        seed = {}
        if os.path.exists(seed_path):
            with open(seed_path, encoding="utf-8") as f:
                seed = json.load(f)
        if conn.execute("SELECT COUNT(*) FROM periods").fetchone()[0] == 0:
            for p in seed.get("periods", []):
                if p.get("object") is None or p.get("object") in P.OBJECT_IDS:
                    conn.execute("INSERT INTO periods (object_id, name, start_date, end_date, price) "
                                 "VALUES (?, ?, ?, ?, ?)",
                                 (p.get("object"), p.get("name", ""), p["start"], p["end"], p.get("price")))
        empty = all(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
                    for t in ("bookings", "blocked_nights"))
        if with_demo and empty:
            for key, nights in seed.get("demo", {}).get("blockedNights", {}).items():
                if not key.isdigit() or int(key) not in P.OBJECT_IDS:
                    continue
                for d in nights:
                    conn.execute("INSERT OR IGNORE INTO blocked_nights (date, object_id, reason) VALUES (?, ?, ?)",
                                 (d, int(key), "Демо: зайнято"))
        conn.execute("COMMIT")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        conn.close()



# ---------- Адміністратори ----------

DEMO_ADMIN = ("admin", "forsethouse2026")


def ensure_admin(path):
    """Створює першого адміністратора з ADMIN_USERNAME / ADMIN_PASSWORD (з файлу .env).

    Без них — демо-доступ admin / forsethouse2026. Якщо ADMIN_PASSWORD задали пізніше,
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


# ---------- Будинки й ціни ----------

def _tiers(raw):
    try:
        tiers = [{"nights": int(t["nights"]), "price": int(t["price"])} for t in json.loads(raw)]
    except (ValueError, TypeError, KeyError):
        return []
    return sorted(tiers, key=lambda t: t["nights"])


def objects(db):
    """Ціни й правила всіх будинків: {id: {...}} — те, що потрібно для розрахунку (і браузеру)."""
    rows = {r["id"]: r for r in db.execute("SELECT * FROM objects")}
    out = {}
    for o in site_content.OBJECTS:
        r = rows.get(o["id"])
        if r is None:
            continue
        out[o["id"]] = {
            "id": o["id"], "slug": o["slug"], "name": o["name"], "short": o["short"], "tone": o["tone"],
            "price": r["price"], "tiers": _tiers(r["tiers"]),
            "maxGuests": o["max_guests"], "guestsText": o["guests_text"],
        }
    return out


def get_object(db, object_id):
    obj = objects(db).get(object_id)
    if obj is None:
        raise BookingError("Оберіть будинок")
    return obj


def objects_json(db):
    return {str(k): v for k, v in objects(db).items()}


def save_object_prices(db, object_id, price, tiers):
    """tiers: [{"nights": 2, "price": 2200}, ...] — пороги діб мають бути різні й більші за 1."""
    get_object(db, object_id)
    seen = set()
    for t in tiers:
        if t["nights"] < 2 or t["nights"] > 60:
            raise BookingError("Поріг знижки — від 2 до 60 діб")
        if t["nights"] in seen:
            raise BookingError(f"Поріг «від {t['nights']} діб» указано двічі")
        seen.add(t["nights"])
    db.execute("UPDATE objects SET price = ?, tiers = ? WHERE id = ?",
               (price, json.dumps(sorted(tiers, key=lambda t: t["nights"])), object_id))


# ---------- Чан і баня ----------

def extras_prices(db):
    rows = {r["key"]: r["price"] for r in db.execute("SELECT key, price FROM extras")}
    return {e["key"]: rows[e["key"]] for e in site_content.EXTRAS if e["key"] in rows}


def extras_json(db):
    prices = extras_prices(db)
    return [{"key": e["key"], "name": e["name"], "price": prices[e["key"]]}
            for e in site_content.EXTRAS if e["key"] in prices]


def save_extra_price(db, key, price):
    if key not in site_content.EXTRA_BY_KEY:
        raise BookingError("Невідома послуга")
    db.execute("INSERT INTO extras (key, price) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET price = excluded.price",
               (key, price))


# ---------- Періоди (свята) ----------

def period_to_dict(r):
    return {"id": r["id"], "objectId": r["object_id"], "name": r["name"], "start": r["start_date"],
            "end": r["end_date"], "price": r["price"]}


def periods(db):
    return [period_to_dict(r) for r in db.execute("SELECT * FROM periods ORDER BY start_date, object_id")]


def save_period(db, data, period_id=None):
    """Додає або змінює період. Періоди одного будинку (і «для всіх») не можуть перетинатися."""
    if data["objectId"] is not None:
        get_object(db, data["objectId"])
    db.execute("BEGIN IMMEDIATE")
    try:
        clash = db.execute(
            "SELECT name, start_date FROM periods WHERE object_id IS ? AND start_date <= ? AND end_date >= ? "
            "AND id IS NOT ?", (data["objectId"], data["end"], data["start"], period_id)).fetchone()
        if clash:
            raise BookingError(f"Період перетинається з «{clash['name'] or clash['start_date']}»", 409)
        values = (data["objectId"], data["name"], data["start"], data["end"], data["price"])
        if period_id:
            cur = db.execute("UPDATE periods SET object_id = ?, name = ?, start_date = ?, end_date = ?, price = ? "
                             "WHERE id = ?", (*values, period_id))
            if cur.rowcount == 0:
                raise BookingError("Період не знайдено", 404)
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


# ---------- Зайняті доби ----------

def _code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "FH-" + "".join(secrets.choice(alphabet) for _ in range(8))


def busy(db, exclude_code=None):
    """{1: set(ночей), 2: ..., 3: ...} — активні бронювання + доби, закриті власником."""
    out = {o: set() for o in P.OBJECT_IDS}
    for r in db.execute("SELECT date, object_id FROM blocked_nights"):
        out.setdefault(r["object_id"], set()).add(r["date"])
    rows = db.execute("SELECT check_in, check_out, object_id FROM bookings WHERE status IN (?, ?) AND code IS NOT ?",
                      (*ACTIVE, exclude_code))
    for r in rows:
        out.setdefault(r["object_id"], set()).update(P.nights_between(r["check_in"], r["check_out"]))
    return out


def busy_json(db):
    return {str(o): sorted(n) for o, n in busy(db).items()}


# ---------- Бронювання ----------

def create_booking(db, data):
    """Атомарно перевіряє, чи вільний будинок, рахує ціну й зберігає заявку. Повертає бронювання (dict)."""
    db.execute("BEGIN IMMEDIATE")
    try:
        obj = get_object(db, data["objectId"])
        if not P.is_free(busy(db).get(obj["id"], set()), data["checkIn"], data["checkOut"]):
            raise BookingError(f"На жаль, «{obj['name']}» на ці дати вже зайнято. Оберіть інші дати.", 409)
        q = P.quote(obj, periods(db), extras_prices(db), data["checkIn"], data["checkOut"], data["guests"],
                    data.get("extras", []))
        code = _code()
        db.execute(
            """INSERT INTO bookings (code, object_id, check_in, check_out, nights, guests, extras, guest_name,
                   guest_phone, comment, price_on_request, total_price, prepayment, quote_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, obj["id"], data["checkIn"], data["checkOut"], q["nights"], q["guests"],
             json.dumps([e["key"] for e in q["extras"]]), data["name"], data["phone"], data.get("comment", ""),
             int(q["onRequest"]), q["total"], q["prepayment"], json.dumps(q, ensure_ascii=False)))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return get_booking(db, code)


def booking_to_dict(r):
    obj = site_content.OBJECT_BY_ID.get(r["object_id"], {})
    keys = json.loads(r["extras"] or "[]")
    return {
        "id": r["code"], "status": r["status"],
        "objectId": r["object_id"], "objectName": obj.get("name", f"Будинок {r['object_id']}"),
        "name": r["guest_name"], "phone": r["guest_phone"], "comment": r["comment"],
        "checkIn": r["check_in"], "checkOut": r["check_out"], "nights": r["nights"], "guests": r["guests"],
        "extras": [site_content.EXTRA_BY_KEY[k]["name"] for k in keys if k in site_content.EXTRA_BY_KEY],
        "onRequest": bool(r["price_on_request"]), "total": r["total_price"], "prepayment": r["prepayment"],
        "price": json.loads(r["quote_json"] or "{}"),
        "createdAt": r["created_at"],
    }


def get_booking(db, code):
    r = db.execute("SELECT * FROM bookings WHERE code = ?", (code,)).fetchone()
    return booking_to_dict(r) if r else None


def set_status(db, code, status):
    if status not in STATUSES:
        raise BookingError("Невідомий статус")
    db.execute("BEGIN IMMEDIATE")
    try:
        b = get_booking(db, code)
        if b is None:
            raise BookingError("Бронювання не знайдено", 404)
        if b["status"] == "cancelled" and status != "cancelled":
            # відновлення — перевіряємо, чи ночі ще ніхто не зайняв
            if not P.is_free(busy(db, exclude_code=code).get(b["objectId"], set()), b["checkIn"], b["checkOut"]):
                raise BookingError("Ці дати вже зайняті іншим бронюванням", 409)
        db.execute("UPDATE bookings SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                   "WHERE code = ?", (status, code))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return get_booking(db, code)


def block_nights(db, dates, object_ids, blocked):
    for d in dates:
        for o in object_ids:
            if blocked:
                db.execute("INSERT OR IGNORE INTO blocked_nights (date, object_id, reason) "
                           "VALUES (?, ?, 'Закрито власником')", (d, o))
            else:
                db.execute("DELETE FROM blocked_nights WHERE date = ? AND object_id = ?", (d, o))


def admin_data(db):
    blocked = {str(o): [] for o in P.OBJECT_IDS}
    for r in db.execute("SELECT date, object_id FROM blocked_nights ORDER BY date"):
        blocked.setdefault(str(r["object_id"]), []).append(r["date"])
    return {
        "bookings": [booking_to_dict(r) for r in db.execute("SELECT * FROM bookings ORDER BY check_in")],
        "blocked": blocked,
        "busy": busy_json(db),
        "objects": objects_json(db),
        "periods": periods(db),
        "extras": extras_json(db),
        "config": P.CONFIG,
    }
