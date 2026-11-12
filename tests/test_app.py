"""Перевірка цін (знижки за тривалість, свята, чан і баня), бронювань трьох будинків,
міграції старої бази, галереї, адмінки й Telegram.

Запуск (з папки проєкту, з увімкненим віртуальним середовищем):
    python -m unittest discover -s tests -v
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "import.db")
for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ADMIN_PASSWORD", "ADMIN_USERNAME"):
    os.environ[k] = ""
os.environ["NOTIFY_SYNC"] = "1"

import app as app_module  # noqa: E402
import database as db_  # noqa: E402
import gallery  # noqa: E402
import notifications  # noqa: E402
import pricing as P  # noqa: E402
import site_content  # noqa: E402

FIXED_NOW = datetime(2026, 11, 3, 10, 0)
EXTRAS = {"chan": 3000, "banya": 2000}
AFRAME = {"id": 3, "price": 4000, "tiers": [{"nights": 2, "price": 3500}, {"nights": 5, "price": 3000}]}
NEW_YEAR = [{"objectId": None, "name": "Новорічні свята", "start": "2026-12-30", "end": "2027-01-07", "price": None}]


class PricingTest(unittest.TestCase):
    def total(self, nights, extras=(), obj=AFRAME, periods=()):
        return P.quote(obj, list(periods), EXTRAS, "2026-11-10", f"2026-11-{10 + nights}", 2, extras)["total"]

    def test_length_discounts(self):
        self.assertEqual(self.total(1), 4000)
        self.assertEqual(self.total(2), 7000)        # 2 × 3500
        self.assertEqual(self.total(4), 14000)       # 4 × 3500
        self.assertEqual(self.total(5), 15000)       # 5 × 3000
        self.assertEqual(self.total(7), 21000)
        green = {"id": 1, "price": 2500, "tiers": [{"nights": 2, "price": 2200}]}
        self.assertEqual(self.total(1, obj=green), 2500)
        self.assertEqual(self.total(3, obj=green), 6600)
        self.assertEqual(P.min_price(AFRAME), 3000)

    def test_extras(self):
        self.assertEqual(self.total(2, ["chan"]), 10000)
        self.assertEqual(self.total(2, ["chan", "banya"]), 12000)
        q = P.quote(AFRAME, [], EXTRAS, "2026-11-10", "2026-11-12", 2, ["banya"])
        self.assertEqual(q["prepayment"], round(9000 * P.CONFIG["prepaymentPercent"] / 100))

    def test_price_on_request(self):
        q = P.quote(AFRAME, NEW_YEAR, EXTRAS, "2026-12-28", "2027-01-02", 2, ["chan"])
        self.assertTrue(q["onRequest"])
        self.assertIsNone(q["total"])
        self.assertEqual(q["missingNights"], ["2026-12-30", "2026-12-31", "2027-01-01"])
        # період з ціною замінює звичайну
        fixed = [{"objectId": 3, "name": "Свято", "start": "2026-11-10", "end": "2026-11-10", "price": 5000}]
        self.assertEqual(self.total(2, periods=fixed), 5000 + 3500)

    def test_start_prices(self):
        prices = {o["id"]: (o["price"], o["tiers"]) for o in site_content.OBJECTS}
        self.assertEqual(prices, {1: (2500, [(2, 2200)]), 2: (4000, [(2, 3500)]),
                                  3: (4000, [(2, 3500), (5, 3000)])})
        self.assertEqual({e["key"]: e["price"] for e in site_content.EXTRAS}, EXTRAS)


class AppTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patch = mock.patch.object(app_module, "now_local", return_value=FIXED_NOW)
        self.patch.start()
        app_module._hits.clear()  # скидаємо захист від спаму між тестами
        self.app = app_module.create_app({"DATABASE": os.path.join(self.dir, "t.db")})
        self.client = self.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as s:
            self.csrf = s["csrf"]

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def book(self, **kw):
        body = {"objectId": 3, "checkIn": "2026-11-10", "checkOut": "2026-11-12", "guests": 2,
                "name": "Олена", "phone": "+380501112233", "rules": True}
        body.update(kw)
        return self.client.post("/api/bookings", json=body, headers={"X-CSRF-Token": self.csrf})

    def login(self):
        self.client.post("/admin/login", data={"username": "admin", "password": "forsethouse2026", "csrf": self.csrf})
        with self.client.session_transaction() as s:
            self.csrf = s["csrf"] = s.get("csrf") or "x"
        return {"X-CSRF-Token": self.csrf}

    def test_pages(self):
        for url in ("/", "/green", "/cottage", "/a-frame", "/admin/login"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/nothing").status_code, 404)
        html = self.client.get("/").get_data(as_text=True)
        for text in ("Приватна садиба Forest House", "від <strong>2 200 грн</strong> / доба", "img/logo.png",
                     "instagram.com/forest_house2026", "tiktok.com/@foresthouse2023", "img/territory/thumb/01.webp",
                     "img/food/thumb/01.webp", "Домашнє харчування за домовленістю", "Відгуки гостей"):
            self.assertIn(text, html)
        html = self.client.get("/a-frame").get_data(as_text=True)
        self.assertIn("img/obj3/01.webp", html)
        self.assertIn("img/obj3/thumb/01.webp 600w", html)
        # банер — А-фрейм узимку з вогниками; обкладинка котеджу — вітальня з каміном і ялинкою
        self.assertIn("img/obj3/22.webp", self.client.get("/").get_data(as_text=True))
        cottage = self.client.get("/cottage").get_data(as_text=True)
        self.assertIn('<div class="obj-hero-media"><img class="photo " src="/static/img/obj2/03.webp"', cottage)
        self.assertIn("img/obj2/01.webp", cottage)  # фасад лишився в галереї
        for url in ("/green", "/cottage", "/a-frame"):
            self.assertIn('class="page-object dark-top"', self.client.get(url).get_data(as_text=True))

    def test_each_object_with_and_without_chan(self):
        # 10.11 → 12.11 (2 доби) для кожного будинку, без чану й з чаном (різні дати — той самий будинок)
        expected = {1: 4400, 2: 7000, 3: 7000}
        for oid, base in expected.items():
            r = self.book(objectId=oid)
            self.assertEqual(r.status_code, 201, r.get_json())
            self.assertEqual(r.get_json()["booking"]["total"], base)
            r = self.book(objectId=oid, checkIn="2026-11-16", checkOut="2026-11-18", extras=["chan"])
            b = r.get_json()["booking"]
            self.assertEqual((b["total"], b["extras"]), (base + 3000, ["Чан"]))
        # А-фрейм на 5 діб з чаном і банею
        b = self.book(checkIn="2026-11-23", checkOut="2026-11-28", extras=["chan", "banya", "bogus"]).get_json()["booking"]
        self.assertEqual((b["total"], b["extras"]), (5 * 3000 + 5000, ["Чан", "Баня"]))

    def test_booking_conflicts_and_validation(self):
        self.assertEqual(self.book().status_code, 201)
        self.assertEqual(self.book(checkIn="2026-11-11", checkOut="2026-11-13").status_code, 409)
        self.assertEqual(self.book(objectId=1).status_code, 201)
        self.assertEqual(self.book(objectId=9, checkIn="2026-11-24").status_code, 400)
        self.assertEqual(self.book(guests=5, checkIn="2026-11-24", checkOut="2026-11-26").status_code, 400)
        self.assertEqual(self.book(objectId=2, guests=6, checkIn="2026-11-24", checkOut="2026-11-25").status_code, 201)

    def test_new_year_on_request(self):
        r = self.book(checkIn="2026-12-29", checkOut="2027-01-02", extras=["banya"])
        b = r.get_json()["booking"]
        self.assertEqual(r.status_code, 201)
        self.assertTrue(b["onRequest"])
        self.assertIsNone(b["total"])
        self.assertIn("Ціна за домовленістю", notifications.booking_message(b))

    def test_telegram_message(self):
        b = self.book(objectId=2, guests=5, extras=["chan"]).get_json()["booking"]
        text = notifications.booking_message(b)
        for part in ("Двоповерховий котедж", "Чан", "від 2 діб", "10 000 грн"):
            self.assertIn(part, text)

    def test_admin(self):
        self.assertEqual(self.client.get("/admin/api/data").status_code, 401)
        h = self.login()
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        r = self.client.post("/admin/api/object-prices", headers=h, json={
            "id": 1, "price": 2600, "tiers": [{"nights": 3, "price": 2100}, {"nights": 7, "price": 1900}]})
        self.assertEqual(r.status_code, 200, r.get_json())
        o = self.client.get("/api/availability").get_json()["objects"]
        self.assertEqual((o["1"]["price"], [t["nights"] for t in o["1"]["tiers"]]), (2600, [3, 7]))
        self.assertEqual(o["3"]["price"], 4000)  # інші не змінились
        self.assertEqual(self.book(objectId=1).get_json()["booking"]["total"], 5200)       # 2 доби — без знижки
        self.assertEqual(self.book(objectId=1, checkIn="2026-11-16", checkOut="2026-11-19").get_json()["booking"]["total"], 6300)
        bad = self.client.post("/admin/api/object-prices", headers=h,
                               json={"id": 1, "price": 2600, "tiers": [{"nights": 1, "price": 2000}]})
        self.assertEqual(bad.status_code, 400)
        # ціна чану
        self.client.post("/admin/api/extra-price", headers=h, json={"key": "chan", "price": 3500})
        self.assertEqual(self.book(objectId=2, extras=["chan"]).get_json()["booking"]["total"], 7000 + 3500)
        # період «за домовленістю» для одного будинку
        r = self.client.post("/admin/api/period", headers=h, json={
            "objectId": 2, "name": "Травневі", "start": "2027-05-01", "end": "2027-05-03", "onRequest": True})
        self.assertEqual(r.status_code, 200, r.get_json())
        periods = self.client.get("/api/availability").get_json()["periods"]
        self.assertIn({"objectId": 2, "name": "Травневі", "price": None}, [
            {k: p[k] for k in ("objectId", "name", "price")} for p in periods])
        # закриття доби лише для одного будинку
        self.client.post("/admin/api/block-nights", headers=h,
                         json={"dates": ["2026-11-24"], "objects": [1], "blocked": True})
        busy = self.client.get("/api/availability").get_json()["busy"]
        self.assertIn("2026-11-24", busy["1"])
        self.assertNotIn("2026-11-24", busy["2"])
        code = self.book(objectId=3, checkIn="2026-11-25", checkOut="2026-11-27").get_json()["booking"]["id"]
        r = self.client.post("/admin/api/status", headers=h, json={"id": code, "status": "confirmed"})
        self.assertEqual(r.get_json()["booking"]["status"], "confirmed")


class MigrationTest(unittest.TestCase):
    def test_v1_database_is_upgraded(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE objects (id INTEGER PRIMARY KEY, weekday_price INTEGER NOT NULL, weekend_price INTEGER,
                                  weekend_nights TEXT NOT NULL DEFAULT '[4, 5]');
            CREATE TABLE seasons (id INTEGER PRIMARY KEY, object_id INTEGER, name TEXT, start_date TEXT, end_date TEXT,
                                  weekday_price INTEGER, weekend_price INTEGER);
            CREATE TABLE bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
                object_id INTEGER NOT NULL REFERENCES objects(id), check_in TEXT NOT NULL, check_out TEXT NOT NULL,
                nights INTEGER NOT NULL, guests INTEGER NOT NULL, guest_name TEXT NOT NULL, guest_phone TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '', total_price INTEGER NOT NULL, prepayment INTEGER NOT NULL,
                quote_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL DEFAULT 'x', updated_at TEXT NOT NULL DEFAULT 'x');
            INSERT INTO objects VALUES (1, 2500, NULL, '[4, 5]'), (2, 3500, NULL, '[4, 5]'), (3, 3000, NULL, '[4, 5]');
            INSERT INTO bookings (code, object_id, check_in, check_out, nights, guests, guest_name, guest_phone,
                                  total_price, prepayment)
                VALUES ('FH-OLD', 3, '2026-11-10', '2026-11-12', 2, 2, 'Гість', '+380', 6000, 1800);
        """)
        conn.commit()
        conn.close()
        db_.init_db(path, with_demo=False)
        conn = db_.connect(path)
        self.assertEqual(conn.execute("SELECT price FROM objects WHERE id = 3").fetchone()[0], 4000)
        row = conn.execute("SELECT code, total_price, extras FROM bookings").fetchone()
        self.assertEqual(tuple(row), ("FH-OLD", 6000, "[]"))
        self.assertEqual(json.loads(conn.execute("SELECT tiers FROM objects WHERE id = 1").fetchone()[0]),
                         [{"nights": 2, "price": 2200}])
        conn.close()
        shutil.rmtree(d)


class GalleryTest(unittest.TestCase):
    def test_photos_from_folder(self):
        folder = tempfile.mkdtemp()
        o = dict(site_content.OBJECTS[0], folder="test")
        with mock.patch.object(gallery, "IMG_DIR", folder):
            self.assertEqual(gallery.photos(o), [])
            self.assertIsNone(gallery.cover(o))
            os.makedirs(os.path.join(folder, "test"))
            for n in ("02.jpg", "01.webp", "notes.txt"):
                open(os.path.join(folder, "test", n), "w").close()
            with open(os.path.join(folder, "test", "captions.txt"), "w", encoding="utf-8") as f:
                f.write("01.webp = Фасад\n")
            items = gallery.photos(o)
        self.assertEqual([p["src"] for p in items], ["img/test/01.webp", "img/test/02.jpg"])
        self.assertEqual(items[0]["caption"], "Фасад")
        shutil.rmtree(folder)

    def test_real_photos_optimized(self):
        """Усі фото — WebP до ~250 КБ, до 1600 px; у кожного є мініатюра 600 px."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow не встановлено (потрібен лише для обробки фото)")
        for folder in ("obj1", "obj2", "obj3", "territory", "food"):
            items = gallery.photos({"folder": folder, "name": folder})
            self.assertTrue(items, folder)
            for p in items:
                full = os.path.join(ROOT, "static", p["src"])
                self.assertTrue(p["src"].endswith(".webp"), p["src"])
                self.assertIsNotNone(p["thumb"], p["src"])
                self.assertLessEqual(os.path.getsize(full), 270 * 1024, p["src"])
                with Image.open(full) as im:
                    self.assertLessEqual(im.width, 1600)
                with Image.open(os.path.join(ROOT, "static", p["thumb"])) as im:
                    self.assertLessEqual(im.width, 600)


if __name__ == "__main__":
    unittest.main()
