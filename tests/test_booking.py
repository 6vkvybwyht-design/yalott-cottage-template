"""Бронювання на живому сайті: ціни прикладів, одиниці, подвійне бронювання, мінімум ночей, адмінка, seed."""

import re
import threading
from datetime import date
from unittest import mock

import database as db_
import notifications
from conftest import CONFIGS, ROOT


# ---------- приклади працюють без правок коду ----------

def test_all_configs_render_every_page(make_site):
    for name, theme in (("site", "forest"), ("ramshill", "wood"), ("blackhouse", "dark")):
        s = make_site(name)
        home = s.html("/")
        assert f'data-theme="{theme}"' in home
        assert s.cfg.brand["name"] in home
        for o in s.cfg.objects:
            page = s.html(f"/{o['slug']}")
            assert o["name"] in page and 'id="booking-form"' in page
        assert s.client.get("/admin/login").status_code == 200
        assert s.client.get("/favicon.svg").status_code == 200
        assert s.client.get("/немає-такої").status_code == 404


def test_examples_have_nothing_from_demo_site(ramshill, blackhouse):
    """У прикладах немає слідів демо-сайту: усе береться з конфігу."""
    for s in (ramshill, blackhouse):
        html = s.html("/") + s.html(f"/{s.cfg.objects[0]['slug']}")
        for leftover in ("Forest House", "А-фрейм", "forest_house", "media/objects/a-frame", "Баня"):
            assert leftover not in html, leftover


def test_sections_can_be_switched_off(ramshill, make_site):
    html = ramshill.html("/")
    assert 'id="faq"' in html and 'id="extras"' in html and 'id="nearby"' in html
    assert 'id="reviews"' not in html                       # sections.reviews: false
    assert 'id="reviews"' in make_site("site").html("/")    # у демо-сайті відгуки увімкнено


def test_placeholder_instead_of_broken_photo(ramshill):
    """Фото немає — показується заглушка, а не зламаний <img>."""
    html = ramshill.html("/") + ramshill.html("/big")
    assert 'class="ph ph--t1' in html and "фото незабаром" in html
    assert 'src=""' not in html and "None" not in html
    assert 'class="hero hero--plain"' in html               # банер без фото — фон теми


def test_theme_colors_from_config(make_site, tmp_path):
    text = open(CONFIGS["ramshill"], encoding="utf-8").read()
    text = text.replace('primary_color: ""', 'primary_color: "#123456"').replace('accent_color: ""', 'accent_color: "#abcdef"')
    path = tmp_path / "ramshill.yaml"
    path.write_text(text, encoding="utf-8")
    html = make_site(str(path)).html("/")
    assert "--primary:#123456" in html and "--accent:#abcdef" in html and "--on-primary:#ffffff" in html


# ---------- Ramshill: ціни й кількість одиниць ----------

def test_ramshill_prices(ramshill):
    s = ramshill
    assert s.total("big", guests=4) == 2 * 8500                       # 4 гості входять у ціну
    assert s.total("big", "2026-11-16", "2026-11-17", guests=6) == 8500 + 2 * 500
    assert s.total("small", guests=2) == 2 * 6000
    assert s.total("small", "2026-11-16", "2026-11-18", guests=3) == 2 * 6000 + 2 * 500
    assert s.total("small", "2026-11-20", "2026-11-21", guests=2, extras=["chan"]) == 6000 + 2500


def test_max_guests(ramshill):
    assert ramshill.book("big", guests=6).status_code == 201
    assert ramshill.book("big", guests=7).status_code == 400
    assert ramshill.book("small", guests=4).status_code == 400
    assert ramshill.book("small", guests=0).status_code == 400


def test_identical_units_are_booked_separately(ramshill):
    """Великий котедж × 2: дві броні на ті самі дати проходять, третя — ні."""
    s, big = ramshill, str(ramshill.ids["big"])
    assert s.book("big").status_code == 201
    assert "2026-11-10" not in s.get("/api/availability")["busy"][big]   # одна одиниця ще вільна
    assert s.book("big").status_code == 201
    assert s.get("/api/availability")["busy"][big] == ["2026-11-10", "2026-11-11"]
    r = s.book("big")
    assert r.status_code == 409 and "вже зайнято" in r.get_json()["error"]
    # сусідні дати й інший об'єкт не зачеплено
    assert s.book("big", "2026-11-12", "2026-11-13").status_code == 201
    assert s.book("small").status_code == 201


def test_four_units(ramshill):
    codes = [ramshill.book("small").status_code for _ in range(5)]
    assert codes == [201, 201, 201, 201, 409]


def test_partial_overlap_counts_per_night(ramshill):
    """Одиниці однакові: має значення лише те, скільки зайнято в КОЖНУ ніч."""
    s = ramshill
    assert s.book("big", "2026-11-10", "2026-11-12").status_code == 201   # ночі 10, 11
    assert s.book("big", "2026-11-11", "2026-11-13").status_code == 201   # ночі 11, 12 → 11-го зайняті обидві
    assert s.book("big", "2026-11-11", "2026-11-12").status_code == 409
    assert s.book("big", "2026-11-10", "2026-11-11").status_code == 201   # 10-го одна ще вільна
    assert s.book("big", "2026-11-12", "2026-11-14").status_code == 201


def test_cancel_frees_unit_and_restore_checks_again(ramshill):
    s = ramshill
    first = s.book("big").get_json()["booking"]["id"]
    s.book("big")
    assert s.admin("status", id=first, status="cancelled").status_code == 200
    assert s.book("big").status_code == 201                       # місце звільнилось і зайняте знову
    r = s.admin("status", id=first, status="new")                 # відновити вже нікуди
    assert r.status_code == 409


def test_no_double_booking_under_concurrency(blackhouse):
    """Вісім одночасних заявок на один котедж і ті самі дати — проходить рівно одна."""
    s, results = blackhouse, []
    data = {"objectId": s.ids["001"], "checkIn": "2026-11-10", "checkOut": "2026-11-12", "guests": 2,
            "extras": [], "name": "Гість", "phone": "+380501112233"}

    def attempt():
        with s.app.app_context():
            try:
                db_.create_booking(db_.get_db(), dict(data))
                results.append("ok")
            except db_.BookingError:
                results.append("busy")

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["busy"] * 7 + ["ok"]


def test_concurrency_respects_units(ramshill):
    s, results = ramshill, []
    data = {"objectId": s.ids["small"], "checkIn": "2026-11-10", "checkOut": "2026-11-12", "guests": 2,
            "extras": [], "name": "Гість", "phone": "+380501112233"}

    def attempt():
        with s.app.app_context():
            try:
                db_.create_booking(db_.get_db(), dict(data))
                results.append("ok")
            except db_.BookingError:
                results.append("busy")

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 4 and results.count("busy") == 6      # маленьких котеджів чотири


# ---------- Black House ----------

def test_blackhouse_prices_and_jacuzzi(blackhouse):
    s = blackhouse
    assert s.total("001", guests=2) == 2 * 4500
    assert s.total("002", guests=2) == 2 * 4000
    assert s.total("001", "2026-11-16", "2026-11-17", guests=4) == 4500 + 2 * 500
    assert s.book("001", "2026-11-18", "2026-11-19", guests=5).status_code == 400          # до 4 гостей
    # чан-джакузі: 2500 для 2 гостей, 3000 для 3–4
    assert s.total("002", "2026-11-16", "2026-11-17", guests=2, extras=["jacuzzi"]) == 4000 + 2500
    assert s.total("002", "2026-11-18", "2026-11-19", guests=3, extras=["jacuzzi"]) == 4000 + 500 + 3000
    assert s.total("002", "2026-11-20", "2026-11-21", guests=4, extras=["jacuzzi"]) == 4000 + 1000 + 3000


def test_blackhouse_prepayment_and_rules(blackhouse):
    b = blackhouse.book("001", guests=2).get_json()["booking"]
    assert b["total"] == 9000 and b["prepayment"] == 4500 and b["price"]["prepaymentPercent"] == 50
    assert b["id"].startswith("BH-")
    html = blackhouse.html("/")
    assert "Передоплата 50%" in html
    assert "Скасування за 10 і більше днів до заїзду — переносимо дати. За 9 днів і менше передоплата не повертається." in html


def test_checkin_times_differ_per_object(blackhouse):
    objs = {o["key"]: o for o in blackhouse.get("/api/availability")["objects"].values()}
    assert (objs["001"]["checkIn"], objs["001"]["checkOut"]) == ("15:00", "12:00")
    assert (objs["002"]["checkIn"], objs["002"]["checkOut"]) == ("14:00", "11:00")
    assert "заїзд з 15:00, виїзд до 12:00" in blackhouse.html("/001")
    assert "заїзд з 14:00, виїзд до 11:00" in blackhouse.html("/002")
    assert "Котедж 002: заїзд з 14:00, виїзд до 11:00." in blackhouse.html("/")


def test_season_on_request(blackhouse):
    b = blackhouse.book("001", "2026-12-27", "2026-12-30").get_json()["booking"]
    assert b["onRequest"] and b["total"] is None
    assert b["price"]["missingNights"] == ["2026-12-28", "2026-12-29"]
    assert "Ціна за домовленістю" in notifications.booking_message(b, "Black House")


def test_booking_crossing_season_on_site(make_site):
    """Демо-сайт: А-фрейм 26–30.12 — дві звичайні ночі (знижка від 2 ночей) і дві новорічні."""
    s = make_site("site")
    q = s.book("a-frame", "2026-12-26", "2026-12-30").get_json()["booking"]["price"]
    assert [(line["count"], line["price"], line["kind"]) for line in q["lines"]] == [(2, 3500, "tier"), (2, 7000, "period")]
    assert q["total"] == 2 * 3500 + 2 * 7000
    # послуга «за людину за ніч»: сніданок 250 × 3 гостей × 2 ночі + доплата за третього гостя
    assert s.total("a-frame", "2026-11-10", "2026-11-12", guests=3, extras=["breakfast"]) == 7000 + 2 * 300 + 250 * 3 * 2


# ---------- перевірка форми ----------

def test_validation(ramshill):
    s = ramshill
    assert s.book("big", "2026-11-01", "2026-11-03").status_code == 400            # дата вже минула
    assert s.book("big", "2026-11-12", "2026-11-10").status_code == 400            # виїзд раніше за заїзд
    assert s.book("big", "2028-01-10", "2028-01-12").status_code == 400            # далі ніж на рік
    assert s.book("big", "2026-13-45", "2026-11-12").status_code == 400            # не дата
    assert s.book(999).status_code == 400
    assert s.book("big", name="").status_code == 400
    assert s.book("big", phone="123").status_code == 400
    assert s.book("big", rules=False).status_code == 400
    assert s.book("big", website="spam").status_code == 400                        # пастка для ботів
    r = s.client.post("/api/bookings", json={})                                    # без CSRF
    assert r.status_code == 400


def test_min_nights(ramshill):
    s = ramshill
    assert s.book("big", "2026-11-10", "2026-11-11").status_code == 201            # мінімум 1 ніч
    r = s.admin("object-prices", id=s.ids["big"], price=8500, tiers=[], minNights=3)
    assert r.status_code == 200, r.get_json()
    r = s.book("big", "2026-11-16", "2026-11-18")
    assert r.status_code == 400 and "мінімальне бронювання" in r.get_json()["error"]
    assert s.book("big", "2026-11-16", "2026-11-19").status_code == 201
    assert s.book("small", "2026-11-16", "2026-11-17").status_code == 201          # інший об'єкт — свій мінімум


# ---------- адмінка ----------

def test_admin_requires_login(ramshill):
    assert ramshill.client.get("/admin/api/data").status_code == 401
    assert ramshill.client.get("/admin/").status_code == 302
    ramshill.login()
    assert ramshill.client.get("/admin/").status_code == 200
    data = ramshill.get("/admin/api/data")
    assert [o["units"] for o in data["objects"].values()] == [2, 4]


def test_admin_price_accepts_any_integer(ramshill):
    """Відомий баг старих сайтів: ціна 20000 не зберігалась через крок поля. Тут — будь-яке ціле число."""
    s, big = ramshill, ramshill.ids["big"]
    for price in (20000, 12345, 1, 999999, "20000", "20 000"):
        r = s.admin("object-prices", id=big, price=price, tiers=[])
        assert r.status_code == 200, (price, r.get_json())
    assert s.get("/api/availability")["objects"][str(big)]["price"] == 20000
    assert s.total("big", "2026-11-16", "2026-11-17", guests=4) == 20000
    for bad in (0, -5, "abc", 12.5, None, 1_000_001):
        assert s.admin("object-prices", id=big, price=bad, tiers=[]).status_code == 400, bad
    # сезон і послуга — так само
    assert s.admin("period", objectId=big, name="Свято", start="2027-03-01", end="2027-03-03", price=20000).status_code == 200
    assert s.admin("extra-price", key="chan", price=20000).status_code == 200


def test_price_inputs_have_step_1():
    """Усі числові поля адмінки — з кроком 1, без step="100"/"500", які блокували такі ціни."""
    js = open(f"{ROOT}/static/js/admin.js", encoding="utf-8").read()
    steps = re.findall(r'type="number"[^>]*?step="([^"]+)"', js)
    assert steps and set(steps) == {"1"}
    assert len(re.findall(r'type="number"', js)) == len(steps)      # жодного числового поля без step


def test_admin_edits_object_settings_and_extras(blackhouse):
    s, one = blackhouse, blackhouse.ids["001"]
    r = s.admin("object-prices", id=one, price=5000, extraGuestPrice=700, baseGuests=2, maxGuests=5, minNights=1,
                units=1, tiers=[{"nights": 3, "price": 4600}])
    assert r.status_code == 200, r.get_json()
    assert s.total("001", "2026-11-16", "2026-11-17", guests=5) == 5000 + 3 * 700
    assert s.total("001", "2026-11-20", "2026-11-23", guests=2) == 3 * 4600
    assert s.admin("object-prices", id=one, price=5000, baseGuests=6, maxGuests=5, tiers=[]).status_code == 400
    assert s.admin("object-prices", id=one, price=5000, tiers=[{"nights": 1, "price": 100}]).status_code == 400
    # ціни чану за кількістю гостей
    r = s.admin("extra-price", key="jacuzzi", price=3500, guestPrices=[{"upTo": 2, "price": 2700}, {"upTo": 4, "price": 3300}])
    assert r.status_code == 200, r.get_json()
    assert s.total("002", "2026-11-16", "2026-11-17", guests=2, extras=["jacuzzi"]) == 4000 + 2700
    assert s.admin("extra-price", key="unknown", price=100).status_code == 400


def test_admin_seasons(ramshill):
    s, big = ramshill, ramshill.ids["big"]
    assert s.admin("period", objectId=big, name="Травневі", start="2027-05-01", end="2027-05-03", price=11000).status_code == 200
    assert s.total("big", "2027-04-30", "2027-05-02", guests=4) == 8500 + 11000
    clash = s.admin("period", objectId=big, name="Ще", start="2027-05-03", end="2027-05-05", price=9000)
    assert clash.status_code == 409 and "перетинається" in clash.get_json()["error"]
    assert s.admin("period", objectId=big, name="x", start="2027-05-09", end="2027-05-05", price=9000).status_code == 400
    period = next(p for p in s.get("/api/availability")["periods"] if p["name"] == "Травневі")
    assert s.admin("period-delete", id=period["id"]).status_code == 200
    assert s.total("big", "2027-05-01", "2027-05-02", guests=4) == 8500


def test_admin_closes_units_one_by_one(ramshill):
    s, small = ramshill, ramshill.ids["small"]
    night = ["2026-11-10"]
    assert s.admin("block-nights", dates=night, objects=[small], blocked=True, count=3).status_code == 200
    assert s.book("small", "2026-11-10", "2026-11-11").status_code == 201        # четверта одиниця вільна
    assert s.book("small", "2026-11-10", "2026-11-11").status_code == 409
    assert s.admin("block-nights", dates=night, objects=[small], blocked=True, count=2).status_code == 200
    assert s.book("small", "2026-11-10", "2026-11-11").status_code == 201
    # «закрити» без кількості — усе, що ще вільне; «відкрити» — усе закрите власником
    s.admin("block-nights", dates=["2026-11-20"], objects=[small], blocked=True)
    assert "2026-11-20" in s.get("/api/availability")["busy"][str(small)]
    s.admin("block-nights", dates=["2026-11-20"], objects=[small], blocked=False)
    assert "2026-11-20" not in s.get("/api/availability")["busy"][str(small)]
    assert s.admin("block-nights", dates=night, objects=[999], blocked=True).status_code == 400


# ---------- Telegram ----------

def test_telegram_message(ramshill):
    b = ramshill.book("big", guests=6, extras=["chan"]).get_json()["booking"]
    text = notifications.booking_message(b, ramshill.cfg.brand["name"])
    for part in ("Ramshill", "Великий котедж", "Гостей: 6", "2 × 8 500 грн = 17 000 грн", "Доплата за гостей",
                 "Чан = 2 500 грн", "Разом: 21 500 грн", "Передоплата 30%", b["id"]):
        assert part in text, part
    with ramshill.app.app_context():
        row = db_.get_db().execute("SELECT status, message FROM notifications").fetchone()
    assert row["status"] == "skipped" and "Великий котедж" in row["message"]      # Telegram не налаштовано


def test_telegram_test_button(ramshill):
    r = ramshill.admin("telegram-test")
    assert r.status_code == 502 and "TELEGRAM_BOT_TOKEN" in r.get_json()["error"]
    with mock.patch.object(notifications, "send_message", return_value=(True, "")) as send:
        assert ramshill.admin("telegram-test").status_code == 200
    assert "Ramshill" in send.call_args[0][0] and "тестове сповіщення" in send.call_args[0][0]


# ---------- seed: конфіг — початкові дані, адмінка має пріоритет ----------

def test_seed_is_safe_to_repeat(ramshill):
    s = ramshill
    conn = db_.connect(s.db_path)
    before = [tuple(r) for r in conn.execute("SELECT key, price FROM objects")] + \
        [tuple(r) for r in conn.execute("SELECT name, start_date FROM periods")]
    for _ in range(3):
        report = db_.seed(conn, s.cfg)
        assert report["added"] == [] and report["updated"] == []
    after = [tuple(r) for r in conn.execute("SELECT key, price FROM objects")] + \
        [tuple(r) for r in conn.execute("SELECT name, start_date FROM periods")]
    conn.close()
    assert before == after and len(after) == 3


def test_admin_edits_survive_seed_and_restart(ramshill, make_site):
    s, big = ramshill, ramshill.ids["big"]
    s.admin("object-prices", id=big, price=9900, extraGuestPrice=600, tiers=[], units=3)
    s.admin("extra-price", key="chan", price=2800)
    season = s.get("/api/availability")["periods"][0]
    s.admin("period-delete", id=season["id"])                     # власник видалив сезон із конфігу
    s.book("big")

    conn = db_.connect(s.db_path)
    report = db_.seed(conn, s.cfg)                                # python manage.py seed
    conn.close()
    assert report["added"] == []
    assert any("у базі 9 900 грн, у конфігу 8 500 грн" in line for line in report["kept"])
    db_.init_db(s.db_path, s.cfg)                                 # перезапуск сайту

    data = s.get("/api/availability")
    obj = data["objects"][str(big)]
    assert (obj["price"], obj["extraGuestPrice"], obj["units"]) == (9900, 600, 3)
    assert data["extras"][0]["price"] == 2800
    assert data["periods"] == []                                  # видалений сезон не повернувся


def test_seed_reset_restores_config(ramshill):
    s, big = ramshill, ramshill.ids["big"]
    s.admin("object-prices", id=big, price=9900, tiers=[])
    s.admin("period-delete", id=s.get("/api/availability")["periods"][0]["id"])
    code = s.book("big").get_json()["booking"]["id"]
    conn = db_.connect(s.db_path)
    report = db_.seed(conn, s.cfg, reset=True)
    conn.close()
    assert len(report["updated"]) == 3
    data = s.get("/api/availability")
    assert data["objects"][str(big)]["price"] == 8500 and len(data["periods"]) == 1
    with s.app.app_context():
        assert db_.get_booking(db_.get_db(), code)["total"] == 2 * 9900       # бронювання не чіпаються


def test_seed_adds_new_objects_from_config(make_site, tmp_path):
    """У конфіг додали об'єкт і сезон — seed доливає їх, не чіпаючи наявне."""
    text = open(CONFIGS["blackhouse"], encoding="utf-8").read()
    path = tmp_path / "blackhouse.yaml"
    path.write_text(text, encoding="utf-8")
    s = make_site(str(path))
    s.admin("object-prices", id=s.ids["001"], price=5100, tiers=[])
    extra = text.replace("extras:\n", '''  - id: "003"
    name: Котедж 003
    price: 5500
    base_guests: 2
    max_guests: 2
    description: Новий котедж.

extras:
''', 1).replace("rules:\n", '''  - name: Травневі
    start: 2027-05-01
    end: 2027-05-03
    prices: {"003": 7000}

rules:
''', 1)
    path.write_text(extra, encoding="utf-8")
    import site_config
    cfg = site_config.load(str(path))
    conn = db_.connect(s.db_path)
    report = db_.seed(conn, cfg)
    rows = {r["key"]: r["price"] for r in conn.execute("SELECT key, price FROM objects")}
    conn.close()
    assert rows == {"001": 5100, "002": 4000, "003": 5500}
    assert len(report["added"]) == 2 and "Котедж 003" in report["added"][0] and "Травневі" in report["added"][1]


# ---------- DEMO_DATA ----------

def test_demo_data(make_site):
    s = make_site("ramshill", demo=True)
    data = s.get("/api/availability")
    assert any(data["busy"].values())                             # є зайняті вихідні
    assert all(date.fromisoformat(n).weekday() in (4, 5) for nights in data["busy"].values() for n in nights)
    s.login()
    admin = s.get("/admin/api/data")
    assert sorted(b["status"] for b in admin["bookings"]) == ["confirmed", "new"]
    assert all(b["source"] == "demo" for b in admin["bookings"])
    # повторний запуск демо-дані не дублює
    conn = db_.connect(s.db_path)
    assert db_.seed_demo(conn, s.cfg, date(2026, 11, 3)) is False
    blocked, bookings = db_.clear_demo(conn)
    assert blocked > 0 and bookings == 2
    assert conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    assert db_.seed_demo(conn, s.cfg, date(2026, 11, 3)) is False       # після очищення не повертаються
    conn.close()


def test_no_demo_data_by_default(ramshill):
    assert not any(ramshill.get("/api/availability")["busy"].values())
