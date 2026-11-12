-- Структура бази даних сайту (SQLite), версія 3.
-- Створюється автоматично під час першого запуску; початкові дані — з config/site.yaml (python manage.py seed).

PRAGMA foreign_keys = ON;

-- Об'єкти: усе, що впливає на ціну й доступність. Початкові значення — з конфігу, далі їх змінює
-- власник в адмінці (вкладка «Ціни»), і конфіг їх БІЛЬШЕ НЕ перезаписує.
-- Назви, описи, фото — у конфігу (key = id об'єкта в config/site.yaml).
CREATE TABLE IF NOT EXISTS objects (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    key               TEXT    NOT NULL UNIQUE,
    units             INTEGER NOT NULL DEFAULT 1 CHECK (units >= 1),       -- скільки однакових одиниць
    price             INTEGER NOT NULL CHECK (price > 0),                  -- базова ціна за ніч
    base_guests       INTEGER NOT NULL CHECK (base_guests >= 1),           -- гостей у базовій ціні
    max_guests        INTEGER NOT NULL CHECK (max_guests >= base_guests),
    extra_guest_price INTEGER NOT NULL DEFAULT 0 CHECK (extra_guest_price >= 0),  -- за гостя понад базу, за ніч
    min_nights        INTEGER NOT NULL DEFAULT 1 CHECK (min_nights >= 1),
    tiers             TEXT    NOT NULL DEFAULT '[]'   -- знижка за тривалість, JSON: [{"nights": 3, "price": 4000}]
);

-- Сезони (новорічні свята тощо). object_id NULL — для всіх об'єктів.
-- price NULL — «ціна за домовленістю»: сайт не рахує суму, а пише «Уточніть ціну у власника».
CREATE TABLE IF NOT EXISTS periods (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id   INTEGER REFERENCES objects(id),
    name        TEXT    NOT NULL DEFAULT '',
    start_date  TEXT    NOT NULL,              -- YYYY-MM-DD, перша ніч
    end_date    TEXT    NOT NULL,              -- YYYY-MM-DD, остання ніч (включно)
    price       INTEGER CHECK (price IS NULL OR price > 0),
    CHECK (end_date >= start_date)
);

-- Додаткові послуги: ціна й ціни залежно від кількості гостей. Назви й описи — у конфігу.
CREATE TABLE IF NOT EXISTS extras (
    key           TEXT    PRIMARY KEY,
    price         INTEGER NOT NULL CHECK (price > 0),
    guest_prices  TEXT    NOT NULL DEFAULT '[]'    -- JSON: [{"upTo": 2, "price": 2500}, {"upTo": 4, "price": 3000}]
);

-- Бронювання. Займає ОДНУ одиницю об'єкта на ночі з check_in до check_out (не включно).
-- Статуси: new (нова заявка), confirmed (підтверджено), cancelled (скасовано).
CREATE TABLE IF NOT EXISTS bookings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT    NOT NULL UNIQUE,         -- RH-XXXXXXXX
    object_id         INTEGER NOT NULL REFERENCES objects(id),
    check_in          TEXT    NOT NULL,
    check_out         TEXT    NOT NULL,
    nights            INTEGER NOT NULL,
    guests            INTEGER NOT NULL,
    extras            TEXT    NOT NULL DEFAULT '[]',   -- JSON: ["chan", "banya"]
    guest_name        TEXT    NOT NULL,
    guest_phone       TEXT    NOT NULL,
    comment           TEXT    NOT NULL DEFAULT '',
    price_on_request  INTEGER NOT NULL DEFAULT 0,      -- 1 = є ночі «за домовленістю»
    total_price       INTEGER,                         -- NULL, якщо ціна за домовленістю
    prepayment        INTEGER,
    quote_json        TEXT    NOT NULL DEFAULT '{}',   -- повний розрахунок на момент заявки
    status            TEXT    NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'confirmed', 'cancelled')),
    -- Звідки бронювання: site (форма на сайті), demo (DEMO_DATA). v2: ical:<назва>, admin, bot.
    source            TEXT    NOT NULL DEFAULT 'site',
    -- v2, онлайн-оплата (LiqPay / WayForPay / mono): зараз не використовується.
    payment_status    TEXT    NOT NULL DEFAULT 'none',  -- none | pending | paid | refunded
    payment_ref       TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (check_out > check_in)
);
CREATE INDEX IF NOT EXISTS idx_bookings_dates ON bookings (object_id, status, check_in, check_out);

-- Ночі, закриті без бронювання: units — скільки одиниць об'єкта закрито цієї ночі.
-- source: owner (власник в адмінці), demo (DEMO_DATA). v2: ical:<назва> — синхронізація з Booking/Airbnb
-- зможе перезаписувати лише свої рядки, не чіпаючи закриття власника.
CREATE TABLE IF NOT EXISTS blocked_nights (
    date       TEXT    NOT NULL,                  -- YYYY-MM-DD
    object_id  INTEGER NOT NULL REFERENCES objects(id),
    source     TEXT    NOT NULL DEFAULT 'owner',
    units      INTEGER NOT NULL DEFAULT 1 CHECK (units >= 1),
    reason     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (date, object_id, source)
);

-- Черга сповіщень у Telegram: нічого не губиться, якщо Telegram недоступний.
CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_code TEXT    NOT NULL DEFAULT '',
    channel      TEXT    NOT NULL DEFAULT 'telegram',
    message      TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'skipped')),
    error        TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    sent_at      TEXT
);

-- Адміністратори. Пароль зберігається лише як хеш.
CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Журнал seed: що з конфігу вже було записано в базу. Кожен запис заливається РІВНО ОДИН раз,
-- тому повторний seed не повертає видалений в адмінці сезон і не перезаписує змінену ціну.
CREATE TABLE IF NOT EXISTS seed_log (
    kind       TEXT NOT NULL,     -- object | extra | season | demo
    key        TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (kind, key)
);
