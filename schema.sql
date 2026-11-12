-- Структура бази даних приватної садиби Forest House (SQLite), версія 2.
-- Створюється автоматично під час першого запуску сайту; базу версії 1 database.py оновлює сам.
-- Будинки: 1 — Апартаменти Green, 2 — Двоповерховий котедж, 3 — Будинок А-фрейм (див. site_content.py).

PRAGMA foreign_keys = ON;

-- Ціни будинків. Власник змінює їх в адмінці (вкладка «Ціни»).
-- price — ціна за добу; tiers — знижка за тривалість, JSON: [{"nights": 2, "price": 2200}, ...].
CREATE TABLE IF NOT EXISTS objects (
    id     INTEGER PRIMARY KEY,
    price  INTEGER NOT NULL CHECK (price > 0),
    tiers  TEXT    NOT NULL DEFAULT '[]'
);

-- Періоди (свята, сезон). object_id NULL — для всіх будинків.
-- price NULL — «ціна за домовленістю»: сайт не рахує суму, а пише «Уточніть ціну у власника».
CREATE TABLE IF NOT EXISTS periods (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id   INTEGER REFERENCES objects(id),
    name        TEXT    NOT NULL DEFAULT '',
    start_date  TEXT    NOT NULL,              -- YYYY-MM-DD, перша доба
    end_date    TEXT    NOT NULL,              -- YYYY-MM-DD, остання доба (включно)
    price       INTEGER CHECK (price IS NULL OR price > 0),
    CHECK (end_date >= start_date)
);

-- Додаткові послуги (чан, баня): ціна за вечір. Назви — у site_content.py.
CREATE TABLE IF NOT EXISTS extras (
    key    TEXT    PRIMARY KEY,
    price  INTEGER NOT NULL CHECK (price > 0)
);

-- Бронювання. Займає доби обраного будинку з check_in до check_out (не включно).
-- Статуси: new (нова заявка), confirmed (підтверджено), cancelled (скасовано).
CREATE TABLE IF NOT EXISTS bookings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT    NOT NULL UNIQUE,         -- FH-XXXXXXXX
    object_id         INTEGER NOT NULL REFERENCES objects(id),
    check_in          TEXT    NOT NULL,
    check_out         TEXT    NOT NULL,
    nights            INTEGER NOT NULL,
    guests            INTEGER NOT NULL,
    extras            TEXT    NOT NULL DEFAULT '[]',   -- JSON: ["chan", "banya"]
    guest_name        TEXT    NOT NULL,
    guest_phone       TEXT    NOT NULL,
    comment           TEXT    NOT NULL DEFAULT '',
    price_on_request  INTEGER NOT NULL DEFAULT 0,      -- 1 = є доби «за домовленістю»
    total_price       INTEGER,                         -- NULL, якщо ціна за домовленістю
    prepayment        INTEGER,
    quote_json        TEXT    NOT NULL DEFAULT '{}',   -- повний розрахунок на момент заявки
    status            TEXT    NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'confirmed', 'cancelled')),
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (check_out > check_in)
);
CREATE INDEX IF NOT EXISTS idx_bookings_dates ON bookings (object_id, status, check_in, check_out);

-- Доби, які власник закрив вручну, окремо для кожного будинку.
CREATE TABLE IF NOT EXISTS blocked_nights (
    date       TEXT    NOT NULL,                  -- YYYY-MM-DD
    object_id  INTEGER NOT NULL REFERENCES objects(id),
    reason     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (date, object_id)
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
