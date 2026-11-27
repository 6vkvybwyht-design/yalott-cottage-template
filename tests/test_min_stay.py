"""Мінімальний термін бронювання: звичайний мінімум об'єкта (min_nights), на вихідні (weekend_min_nights) і
періоди з особливим мінімумом (розділ min_stay конфігу → таблиця min_stay_rules, далі — адмінка), напр.
«якщо бронювання включає ніч 31.12→01.01 — щонайменше 5 ночей».

Перевіряється: правила й тексти українською, конфіг, одноразовий seed (і в старій базі), відмова сервера,
плашка біля форми, адмінка, старі бронювання й ціни без змін, збіг браузерного й серверного розрахунку.
"""

import json
import os
import random
import shutil
import subprocess
import tempfile
from datetime import date, timedelta

import pytest
import yaml

import app as app_module
import database as db_
import pricing as P
import site_config
from conftest import CONFIGS, ROOT

NY = {"id": 1, "objectId": None, "name": "Новий рік", "start": "2026-12-31", "end": "2026-12-31", "minNights": 5}
HOUSE = {"id": 1, "minNights": 2}
NOTE = "Мінімальний термін бронювання — 2 ночі, на Новий рік — 5 ночей."


def ok(obj, rules, a, b):
    return len(P.nights_between(a, b)) >= P.min_nights_for(obj, a, b, rules)


# ---------- правила й тексти ----------

def test_nights_word():
    assert [P.nights_word(n) for n in (1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 101)] == \
        ["ніч", "ночі", "ночі", "ночей", "ночей", "ночей", "ночей", "ніч", "ночі", "ночей", "ніч"]


def test_new_year_night_needs_five_nights():
    cases = {
        ("2026-12-29", "2026-12-31"): True,    # 2 ночі, новорічну ніч не зачеплено
        ("2026-12-29", "2027-01-01"): False,   # 3 ночі з новорічною
        ("2026-12-29", "2027-01-02"): False,
        ("2026-12-29", "2027-01-03"): True,    # 5
        ("2026-12-31", "2027-01-02"): False,
        ("2026-12-27", "2027-01-01"): True,    # 5, остання — новорічна
        ("2027-01-01", "2027-01-03"): True,    # після свята — звичайні 2
        ("2026-12-30", "2026-12-31"): False,   # 1 ніч — менше за звичайний мінімум
    }
    for (a, b), expected in cases.items():
        assert ok(HOUSE, [NY], a, b) == expected, (a, b)
    s = P.min_stay(HOUSE, [NY], "2026-12-29", "2027-01-01")
    assert (s["required"], s["kind"], s["rule"]["name"], s["night"]) == (5, "rule", "Новий рік", "2026-12-31")


def test_rules_per_object_weekend_and_overlaps():
    only_2 = {"objectId": 2, "name": "Травневі", "start": "2027-05-01", "end": "2027-05-03", "minNights": 3}
    wide = {"objectId": None, "name": "", "start": "2027-05-02", "end": "2027-05-02", "minNights": 4}
    assert P.min_nights_for(HOUSE, "2027-04-27", "2027-04-29", [only_2]) == 2                  # інший об'єкт
    assert P.min_nights_for(dict(HOUSE, id=2), "2027-04-30", "2027-05-02", [only_2]) == 3
    assert P.min_nights_for(dict(HOUSE, id=2), "2027-05-01", "2027-05-03", [only_2, wide]) == 4  # більший
    weekend = dict(HOUSE, minNights=1, weekendMinNights=3)
    assert P.min_stay(weekend, [], "2026-11-13", "2026-11-14")["kind"] == "weekend"
    assert P.min_stay(weekend, [dict(NY, start="2026-11-13", end="2026-11-13")], "2026-11-13", "2026-11-14")["required"] == 5
    assert P.min_nights_for({"id": 1, "minNights": 1}, "2026-12-31", "2027-01-01") == 1          # без правил — як було


def test_note_and_messages():
    assert P.min_stay_note(HOUSE, [NY], "2026-11-03") == NOTE
    assert P.min_stay_note(HOUSE, [NY], "2027-01-02") == "Мінімальний термін бронювання — 2 ночі."      # минуло
    assert P.min_stay_note({"id": 1, "minNights": 1}, [], "2026-11-03") == ""                          # обмежень немає
    assert P.min_stay_note({"id": 1, "minNights": 1, "weekendMinNights": 2}, [dict(NY, name="")], "2026-11-03") == \
        "Мінімальний термін бронювання — 1 ніч, на вихідні — 2 ночі, з 31.12 до 01.01 — 5 ночей."
    s = P.min_stay(HOUSE, [NY], "2026-12-29", "2027-01-01")
    assert P.min_stay_message(s, 3) == ("На Новий рік мінімальний термін бронювання — 5 ночей: ваші дати включають ніч "
                                        "31.12→01.01. Ви обрали 3 ночі — додайте ще 2 ночі або оберіть інші дати.")
    s = P.min_stay(HOUSE, [NY], "2026-11-16", "2026-11-17")
    assert P.min_stay_message(s, 1) == ("Мінімальний термін бронювання — 2 ночі. Ви обрали 1 ніч — додайте ще 1 ніч "
                                        "або оберіть інші дати.")


# ---------- конфіг ----------

def ny_config(folder, min_nights=2, min_stay=None):
    """ramshill: звичайний мінімум 2 ночі для кожного об'єкта і Новий рік — 5 ночей."""
    with open(CONFIGS["ramshill"], encoding="utf-8") as f:
        raw = yaml.load(f, Loader=site_config._Loader)
    for o in raw["objects"]:
        o["min_nights"] = min_nights
    raw["min_stay"] = min_stay if min_stay is not None else [
        {"name": "Новий рік", "start": "2026-12-31", "end": "2026-12-31", "min_nights": 5}]
    path = os.path.join(folder, "ny.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True)
    return path


def test_config_validation(tmp_path):
    def errors(min_stay):
        raw = yaml.safe_load(open(ny_config(tmp_path, min_stay=min_stay), encoding="utf-8"))
        return "\n".join(site_config.validate(raw, check_photos=False)[0])
    assert errors([{"name": "Новий рік", "start": "2026-12-31", "end": "2026-12-31", "min_nights": 5}]) == ""
    assert errors([{"start": "2027-05-01", "end": "2027-05-03", "min_nights": 3, "object": "small"}]) == ""
    assert "неправильна дата" in errors([{"start": "2026-13-31", "end": "2026-12-31", "min_nights": 5}])
    assert "раніше за першу" in errors([{"start": "2027-01-02", "end": "2026-12-31", "min_nights": 5}])
    assert "min_nights" in errors([{"start": "2026-12-31", "end": "2026-12-31", "min_nights": 0}])
    assert "min_nights" in errors([{"start": "2026-12-31", "end": "2026-12-31", "min_nights": "п'ять"}])
    assert "min_nights" in errors([{"start": "2026-12-31", "end": "2026-12-31"}])
    assert "немає об'єкта" in errors([{"start": "2026-12-31", "end": "2026-12-31", "min_nights": 5, "object": "nope"}])
    assert site_config.validate(site_config.read_yaml(CONFIGS["site"]), check_photos=False)[0] == []


# ---------- seed ----------

def rules_in(path):
    conn = db_.connect(path)
    try:
        return db_.min_stay_rules(conn)
    finally:
        conn.close()


def test_shipped_config_seeds_new_year_rule_once(make_site):
    s = make_site("site")
    rules = rules_in(s.db_path)
    assert [(r["objectId"], r["name"], r["start"], r["end"], r["minNights"]) for r in rules] == \
        [(None, "Новий рік", "2026-12-31", "2026-12-31", 5)]
    app_module.create_app({"SITE_CONFIG": CONFIGS["site"], "DATABASE": s.db_path})          # перезапуск сайту
    assert len(rules_in(s.db_path)) == 1                                                     # без дублів
    conn = db_.connect(s.db_path)
    conn.execute("DELETE FROM min_stay_rules")
    conn.close()
    app_module.create_app({"SITE_CONFIG": CONFIGS["site"], "DATABASE": s.db_path})
    assert rules_in(s.db_path) == []                                                         # видалене не повертається
    assert rules_in(make_site("ramshill").db_path) == []                                     # без розділу — нічого


def test_existing_database_gets_table_and_rule(make_site):
    """База сайту, створена до цієї функції: після оновлення шаблону таблиця й період з'являються, бронювання ціле."""
    s = make_site("site")
    assert s.book("a-frame", "2026-11-10", "2026-11-11").status_code == 201
    conn = db_.connect(s.db_path)
    conn.execute("DROP TABLE min_stay_rules")
    conn.execute("DELETE FROM seed_log WHERE kind = 'min_stay'")
    prices = [tuple(r) for r in conn.execute("SELECT * FROM periods ORDER BY id")]
    conn.close()
    app_module.create_app({"SITE_CONFIG": CONFIGS["site"], "DATABASE": s.db_path})
    assert [r["name"] for r in rules_in(s.db_path)] == ["Новий рік"]
    conn = db_.connect(s.db_path)
    try:
        assert [tuple(r) for r in conn.execute("SELECT * FROM periods ORDER BY id")] == prices
        assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1
    finally:
        conn.close()


# ---------- сайт і сервер ----------

@pytest.fixture
def ny_site(make_site):
    folder = tempfile.mkdtemp(prefix="ny-cfg-")
    yield make_site(ny_config(folder))
    shutil.rmtree(folder, ignore_errors=True)


def test_server_rejects_short_stays(ny_site):
    s = ny_site
    r = s.book("big", "2026-11-16", "2026-11-17")
    assert r.status_code == 400
    assert r.get_json()["error"] == "Мінімальний термін бронювання — 2 ночі. Ви обрали 1 ніч — додайте ще 1 ніч або оберіть інші дати."
    r = s.book("big", "2026-12-29", "2027-01-01")
    assert r.status_code == 400 and r.get_json()["error"].startswith(
        "На Новий рік мінімальний термін бронювання — 5 ночей: ваші дати включають ніч 31.12→01.01. Ви обрали 3 ночі")
    s.login()
    assert s.get("/admin/api/data")["bookings"] == []                       # нічого не збережено


def test_valid_stays_accepted_and_prices_unchanged(ny_site, ramshill):
    s = ny_site
    assert s.book("big", "2026-12-29", "2026-12-31").status_code == 201     # без новорічної ночі — 2
    assert s.book("small", "2026-12-27", "2027-01-01").status_code == 201   # 5 ночей з новорічною
    assert s.book("small", "2027-01-01", "2027-01-03").status_code == 201
    for a, b in (("2026-11-16", "2026-11-18"), ("2026-12-26", "2027-01-02")):
        assert s.total("big", a, b) == ramshill.total("big", a, b)          # ціна — як без правила


def test_page_note_rules_block_and_api(ny_site, make_site):
    s = ny_site
    for url in ("/", "/big"):
        html = s.html(url)
        assert f'<span id="min-stay-note">{NOTE}</span>' in html, url
        assert "На Новий рік — від 5 ночей, якщо бронювання включає ніч 31.12→01.01." in html
    data = s.get("/api/availability")
    assert [(r["start"], r["end"], r["minNights"]) for r in data["minStay"]] == [("2026-12-31", "2026-12-31", 5)]
    plain = make_site("ramshill").html("/")                                  # обмежень немає — плашка прихована
    assert '<p class="min-stay-note" hidden>' in plain and "Новий рік — від" not in plain
    assert "Мінімальний термін бронювання — 1 ніч, на Новий рік — 5 ночей." in make_site("site").html("/")


def test_admin_rules_crud_and_validation(ny_site):
    s = ny_site
    s.login()
    ny = s.client.get("/admin/api/data").get_json()["minStay"][0]
    r = s.admin("min-stay", id=ny["id"], name="Новий рік", objectId="all", start=ny["start"], end=ny["end"], minNights="7")
    assert r.status_code == 200, r.get_json()
    assert "бронювання — 7 ночей" in s.book("big", "2026-12-27", "2027-01-01").get_json()["error"]
    r = s.admin("min-stay", name="травневі", objectId=s.ids["big"], start="2027-05-01", end="2027-05-03", minNights=4)
    assert r.status_code == 200, r.get_json()
    assert s.book("big", "2027-04-30", "2027-05-02").status_code == 400
    assert s.book("small", "2027-04-30", "2027-05-02").status_code == 201   # інший об'єкт — звичайний мінімум
    assert "на травневі — 4 ночі" in s.html("/big") and "на травневі" not in s.html("/small")
    assert s.admin("min-stay-delete", id=ny["id"]).status_code == 200
    assert s.book("big", "2026-12-30", "2027-01-02").status_code == 201     # без правила — 3 ночі можна
    for body, code in [(dict(start="2027-02-10", end="2027-02-01", minNights=3), 400),
                       (dict(start="2027-02-xx", end="2027-02-11", minNights=3), 400),
                       (dict(start="2027-02-30", end="2027-03-01", minNights=3), 400),
                       (dict(start="2027-02-10", end="2027-02-11", minNights=0), 400),
                       (dict(start="2027-02-10", end="2027-02-11", minNights=61), 400),
                       (dict(start="2027-02-10", end="2027-02-11", minNights=2.5), 400),
                       (dict(start="2027-02-10", end="2027-02-11", minNights=True), 400),
                       (dict(start="2027-02-10", end="2027-02-11", minNights="п'ять"), 400),
                       (dict(start="2027-02-10", end="2027-02-11", minNights=3, objectId=999), 400),
                       (dict(id=9999, start="2027-02-10", end="2027-02-11", minNights=3), 404)]:
        assert s.admin("min-stay", **body).status_code == code, body
    assert 'id="minStayBox"' in s.client.get("/admin/").get_data(as_text=True)


def test_admin_api_needs_login(ny_site):
    s = ny_site
    r = s.client.post("/admin/api/min-stay", json={"start": "2027-02-10", "end": "2027-02-11", "minNights": 3},
                      headers={"X-CSRF-Token": s.csrf})
    assert r.status_code == 401
    assert len(rules_in(s.db_path)) == 1


def test_existing_short_bookings_keep_working(ny_site):
    """Заявка на 1 ніч, зроблена до правила: лишається, займає календар, її можна підтвердити, скасувати
    й відновити (мінімум перевіряється лише для нових заявок з сайту)."""
    s = ny_site
    conn = db_.connect(s.db_path)
    conn.execute("INSERT INTO bookings (code, object_id, check_in, check_out, nights, guests, guest_name, guest_phone, "
                 "total_price, prepayment) VALUES ('RH-OLDONE01', ?, '2026-11-24', '2026-11-25', 1, 2, 'Стара', "
                 "'+380500000000', 3500, 1050)", (s.ids["big"],))
    conn.close()
    occupancy = s.client.get("/admin/api/data", headers=s.login()).get_json()["occupancy"]
    assert occupancy[str(s.ids["big"])]["2026-11-24"] == 1                 # займає одиницю, як і раніше
    for status in ("confirmed", "cancelled", "new"):
        r = s.admin("status", id="RH-OLDONE01", status=status)
        assert r.status_code == 200, (status, r.get_json())
    old = next(b for b in s.client.get("/admin/api/data").get_json()["bookings"] if b["id"] == "RH-OLDONE01")
    assert (old["nights"], old["total"]) == (1, 3500)


# ---------- браузер рахує так само ----------

@pytest.mark.skipif(not shutil.which("node"), reason="немає node — перевірка браузерного розрахунку пропущена")
def test_browser_matches_server():
    objs = {"1": {"id": 1, "price": 3000, "tiers": [], "minNights": 2, "weekendMinNights": 3},
            "2": {"id": 2, "price": 3000, "tiers": [], "minNights": 1}}
    rules = [NY, {"id": 2, "objectId": 2, "name": "", "start": "2027-02-14", "end": "2027-02-15", "minNights": 3},
             {"id": 3, "objectId": None, "name": "травневі", "start": "2027-05-01", "end": "2027-05-04", "minNights": 4}]
    rnd = random.Random(7)
    cases = []
    for _ in range(400):
        start = date(2026, 12, 15) + timedelta(days=rnd.randint(0, 150))
        cases.append([rnd.choice([1, 2]), start.isoformat(), (start + timedelta(days=rnd.randint(1, 8))).isoformat()])
    expected = []
    for o, a, b in cases:
        s = P.min_stay(objs[str(o)], rules, a, b)
        n = len(P.nights_between(a, b))
        expected.append([s["required"], s["kind"], n >= s["required"], P.min_stay_message(s, n) if n < s["required"] else ""])
    notes = [P.min_stay_note(objs[k], rules, "2026-11-03") for k in ("1", "2")]
    script = """
      global.window = {}; require(process.argv[1]);
      const d = JSON.parse(require('fs').readFileSync(0, 'utf8')), W = window.FHPricing;
      const P = W.make({prepaymentPercent: 30}, d.objs, [], [], d.rules);
      console.log(JSON.stringify({
        cases: d.cases.map(([o, a, b]) => { const s = P.minStay(o, a, b), n = W.nightsBetween(a, b).length;
          return [s.required, s.kind, P.stayOk(o, a, b), n < s.required ? P.minStayMessage(s, n) : '']; }),
        notes: [1, 2].map(o => P.minStayNote(o, '2026-11-03')),
        earliest: [P.earliestCheckout(1, '2026-12-29', null), P.earliestCheckout(1, '2026-12-30', null),
                   P.earliestCheckout(1, '2026-12-30', '2027-01-02'), P.minNightsFrom(1, '2026-12-30')]}));
    """
    res = subprocess.run(["node", "-e", script, os.path.join(ROOT, "static", "js", "pricing.js")],
                         input=json.dumps({"objs": objs, "rules": rules, "cases": cases}),
                         capture_output=True, text=True, check=True)
    js = json.loads(res.stdout)
    assert [c for c, p, j in zip(cases, expected, js["cases"]) if p != j] == []
    assert js["notes"] == notes
    # 29.12 (вт): виїзд 31.12 — 2 ночі; 30.12: найраніше 04.01 (5 ночей), а до 02.01 — жодного
    assert js["earliest"] == ["2026-12-31", "2027-01-04", None, 5]
    assert any(not e[2] for e in expected) and any(e[2] for e in expected)
