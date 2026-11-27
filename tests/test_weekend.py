"""Ціна й мінімум ночей на вихідні (необов'язкові поля об'єкта weekend_price / weekend_min_nights).

Ніч вихідних — ніч із п'ятниці на суботу та із суботи на неділю. Без цих полів усе працює як раніше.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import date, timedelta

import pytest
import yaml

import database as db_
import pricing as P
import site_config
from conftest import CONFIGS, ROOT

HOUSE = {"id": 1, "price": 3500, "tiers": [], "baseGuests": 4, "extraGuestPrice": 0,
         "minNights": 1, "weekendPrice": 4500, "weekendMinNights": 2}
FRIDAY = "2026-11-13"


def after(iso, nights):
    return (date.fromisoformat(iso) + timedelta(days=nights)).isoformat()


# ---------- формула ----------

def test_friday_and_saturday_nights_use_weekend_price():
    q = P.quote(HOUSE, [], [], "2026-11-12", "2026-11-16", 2)       # чт, пт, сб, нд
    assert q["total"] == 3500 + 4500 + 4500 + 3500
    assert [(line["kind"], line["count"]) for line in q["lines"]] == [("base", 2), ("weekend", 2)]


def test_without_weekend_price_nothing_changes():
    plain = dict(HOUSE, weekendPrice=None, weekendMinNights=None)
    assert P.quote(plain, [], [], FRIDAY, after(FRIDAY, 2), 2)["total"] == 7000
    assert P.min_nights_for(plain, FRIDAY, after(FRIDAY, 1)) == 1


def test_season_beats_weekend_price():
    season = {"objectId": None, "name": "Свята", "start": FRIDAY, "end": FRIDAY, "price": 9000}
    assert P.quote(HOUSE, [season], [], FRIDAY, after(FRIDAY, 2), 2)["total"] == 9000 + 4500


def test_min_price_counts_weekend_price():
    assert P.min_price(HOUSE) == 3500
    assert P.min_price(dict(HOUSE, price=5000, weekendPrice=4800)) == 4800


def test_weekend_minimum_only_when_stay_has_friday_or_saturday_night():
    assert P.min_nights_for(HOUSE, FRIDAY, after(FRIDAY, 1)) == 2            # пт → сб
    assert P.min_nights_for(HOUSE, "2026-11-14", "2026-11-15") == 2          # сб → нд
    assert P.min_nights_for(HOUSE, "2026-11-15", "2026-11-16") == 1          # нд → пн
    assert P.min_nights_for(HOUSE, "2026-11-10", "2026-11-11") == 1          # вт → ср
    assert P.min_nights_for(dict(HOUSE, minNights=3), FRIDAY, after(FRIDAY, 3)) == 3   # звичайний більший


@pytest.mark.skipif(not shutil.which("node"), reason="немає node — перевірка браузерного розрахунку пропущена")
def test_browser_pricing_matches_server():
    """static/js/pricing.js рахує вихідні так само, як pricing.py."""
    cases = [("2026-11-12", "2026-11-16"), (FRIDAY, after(FRIDAY, 1)), ("2026-11-15", "2026-11-17"), (FRIDAY, after(FRIDAY, 9))]
    script = """
      global.window = {}; require(process.argv[1]);
      const P = window.FHPricing.make({prepaymentPercent: 30}, {"1": %s}, [], []);
      const out = %s.map(([a, b]) => [P.quote(1, a, b, 2, []).total, P.minNightsFor(1, a, b), P.dayPrice(1, a)]);
      out.push(P.minPrice(1), P.minNightsFrom(1, "%s"), P.minNightsFrom(1, "2026-11-12"));
      console.log(JSON.stringify(out));
    """ % (json.dumps(HOUSE), json.dumps(cases), FRIDAY)
    res = subprocess.run(["node", "-e", script, os.path.join(ROOT, "static", "js", "pricing.js")],
                         capture_output=True, text=True, check=True)
    expected = [[P.quote(HOUSE, [], [], a, b, 2)["total"], P.min_nights_for(HOUSE, a, b),
                 4500 if P.is_weekend(a) else 3500] for a, b in cases]
    expected += [P.min_price(HOUSE), 2, 1]
    assert json.loads(res.stdout) == expected


# ---------- конфіг і сайт ----------

def weekend_config(folder, **fields):
    with open(CONFIGS["ramshill"], encoding="utf-8") as f:
        raw = yaml.load(f, Loader=site_config._Loader)
    raw["objects"][1].update(fields or {"weekend_price": 7000, "weekend_min_nights": 2})
    path = os.path.join(folder, "weekend.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True)
    return path


@pytest.fixture
def weekend_site(make_site):
    folder = tempfile.mkdtemp(prefix="weekend-cfg-")
    yield make_site(weekend_config(folder))
    shutil.rmtree(folder, ignore_errors=True)


def test_config_validation(tmp_path):
    raw = yaml.safe_load(open(weekend_config(tmp_path, weekend_price=0, weekend_min_nights="два"), encoding="utf-8"))
    errors, _ = site_config.validate(raw, check_photos=False)
    assert any("weekend_price" in e for e in errors) and any("weekend_min_nights" in e for e in errors)
    raw = yaml.safe_load(open(weekend_config(tmp_path, min_nights=3, weekend_min_nights=2), encoding="utf-8"))
    errors, warnings = site_config.validate(raw, check_photos=False)
    assert not errors and any("weekend_min_nights" in w for w in warnings)


def test_booking_uses_weekend_price_and_minimum(weekend_site):
    s = weekend_site
    r = s.book("small", FRIDAY, after(FRIDAY, 1))
    assert r.status_code == 400 and r.get_json()["error"].startswith(
        "Якщо серед ночей є п'ятниця чи субота, мінімальний термін бронювання — 2 ночі. Ви обрали 1 ніч")
    assert s.total("small", FRIDAY, after(FRIDAY, 2)) == 2 * 7000
    assert s.total("small", "2026-11-10", "2026-11-11") == 6000            # будні — як раніше
    assert s.total("big", "2026-11-20", "2026-11-21") == 8500              # в іншого об'єкта вихідних немає


def test_pages_show_weekend_price(weekend_site, ramshill):
    html = weekend_site.html("/small")
    assert "Ніч у пт і сб" in html and "7 000 грн" in html and "Мінімум на вихідні" in html
    assert "пт і сб" not in ramshill.html("/") and "пт і сб" not in ramshill.html("/small")
    data = weekend_site.get("/api/availability")["objects"][str(weekend_site.ids["small"])]
    assert data["weekendPrice"] == 7000 and data["weekendMinNights"] == 2


def test_admin_sets_and_clears_weekend_price(ramshill):
    s, oid = ramshill, ramshill.ids["small"]
    base = {"id": oid, "price": 6000, "tiers": []}
    assert s.admin("object-prices", **base, weekendPrice="4500", weekendMinNights="2").status_code == 200
    assert s.total("small", FRIDAY, after(FRIDAY, 2)) == 2 * 4500
    assert s.admin("object-prices", **base, weekendPrice="0").status_code == 400
    assert s.admin("object-prices", **base, weekendPrice="", weekendMinNights="").status_code == 200
    assert s.total("small", "2026-11-20", "2026-11-21") == 6000
    assert s.admin("object-prices", **base).status_code == 200            # поля не надіслано — не змінюються


def test_old_database_gets_new_columns_without_losing_data(tmp_path):
    """База зі старої версії шаблону (без колонок вихідних): колонки доливаються, дані на місці."""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
      CREATE TABLE objects (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE,
        units INTEGER NOT NULL DEFAULT 1, price INTEGER NOT NULL, base_guests INTEGER NOT NULL,
        max_guests INTEGER NOT NULL, extra_guest_price INTEGER NOT NULL DEFAULT 0,
        min_nights INTEGER NOT NULL DEFAULT 1, tiers TEXT NOT NULL DEFAULT '[]');
      INSERT INTO objects (key, price, base_guests, max_guests) VALUES ('big', 9100, 4, 8);""")
    conn.commit()
    conn.close()
    cfg = site_config.load(CONFIGS["ramshill"])
    db_.init_db(path, cfg)
    db_.init_db(path, cfg)                                                  # повторний запуск — без помилок
    conn = db_.connect(path)
    row = conn.execute("SELECT * FROM objects WHERE key = 'big'").fetchone()
    assert row["price"] == 9100 and row["weekend_price"] is None and row["weekend_min_nights"] is None
    conn.close()
