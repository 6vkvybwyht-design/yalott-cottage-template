"""Спільне для тестів. Запуск із папки проєкту:  python -m pytest

Кожен тест отримує власну порожню базу в тимчасовій папці; справжня база й .env не чіпаються.
"""

import os
import shutil
import sys
import tempfile
from datetime import datetime
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="cottage-tests-")
os.environ.update({"YALOTT_NO_APP": "1", "INSTANCE_PATH": _tmp, "NOTIFY_SYNC": "1", "SECRET_KEY": "test" * 16})
for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ADMIN_PASSWORD", "ADMIN_USERNAME", "DATABASE_PATH",
            "DEMO_DATA", "SITE_CONFIG"):
    os.environ[key] = ""

import app as app_module  # noqa: E402

FIXED_NOW = datetime(2026, 11, 3, 10, 0)     # вівторок
CONFIGS = {
    "site": os.path.join(ROOT, "config", "site.yaml"),
    "ramshill": os.path.join(ROOT, "config", "examples", "ramshill.yaml"),
    "blackhouse": os.path.join(ROOT, "config", "examples", "blackhouse.yaml"),
}


class Site:
    """Тестовий клієнт одного сайту: бронювання, вхід в адмінку, доступ до бази."""

    def __init__(self, config, folder, demo=False):
        self.db_path = os.path.join(folder, "test.db")
        self.app = app_module.create_app({"SITE_CONFIG": CONFIGS.get(config, config), "DATABASE": self.db_path,
                                          "DEMO_DATA": demo})
        self.cfg = self.app.extensions["site"]
        self.client = self.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as s:
            self.csrf = s["csrf"]
        self.ids = {o["key"]: o["id"] for o in self.get("/api/availability")["objects"].values()}

    def get(self, url):
        return self.client.get(url).get_json()

    def html(self, url="/"):
        r = self.client.get(url)
        assert r.status_code == 200, url
        return r.get_data(as_text=True)

    def book(self, obj, check_in="2026-11-10", check_out="2026-11-12", guests=2, **kw):
        body = {"objectId": self.ids.get(obj, obj), "checkIn": check_in, "checkOut": check_out, "guests": guests,
                "name": "Олена", "phone": "+380501112233", "rules": True}
        body.update(kw)
        return self.client.post("/api/bookings", json=body, headers={"X-CSRF-Token": self.csrf})

    def total(self, obj, *args, **kw):
        r = self.book(obj, *args, **kw)
        assert r.status_code == 201, r.get_json()
        return r.get_json()["booking"]["total"]

    def login(self):
        with self.client.session_transaction() as s:
            logged = bool(s.get("admin_id"))
        if not logged:
            self.client.post("/admin/login", data={"username": "admin", "password": "demo2026", "csrf": self.csrf})
        with self.client.session_transaction() as s:
            assert s.get("admin_id"), "вхід в адмінку не вдався"
            self.csrf = s["csrf"] = s.get("csrf") or "x"
        return {"X-CSRF-Token": self.csrf}

    def admin(self, url, **body):
        return self.client.post(f"/admin/api/{url}", json=body, headers=self.login())


@pytest.fixture
def make_site():
    folders, patch = [], mock.patch.object(app_module, "now_local", return_value=FIXED_NOW)
    patch.start()
    app_module._hits.clear()   # скидаємо захист від спаму між тестами

    def factory(config="ramshill", demo=False):
        folders.append(tempfile.mkdtemp(prefix="cottage-db-"))
        return Site(config, folders[-1], demo)

    yield factory
    patch.stop()
    for f in folders:
        shutil.rmtree(f, ignore_errors=True)


@pytest.fixture
def ramshill(make_site):
    return make_site("ramshill")


@pytest.fixture
def blackhouse(make_site):
    return make_site("blackhouse")
