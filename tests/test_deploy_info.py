"""manage.py deploy-info — опис сайту для серверного скрипта launch-site (yalott-server).

launch-site читає цей JSON на сервері, щоб не питати власника: точку входу gunicorn, куди покласти базу,
чи сайт у демо-режимі й на якому домені, і чи підходить файл бази, який переносять.
"""

import json
import os
import re
import sqlite3

import pytest

import database as db_
import manage
from conftest import CONFIGS


def info(capsys, *argv):
    assert manage.main(["deploy-info", *argv]) == 0
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "instance"))
    for key in ("DATABASE_PATH", "DEMO_PASSWORD"):
        monkeypatch.setenv(key, "")
    return monkeypatch


def demo_config(tmp_path, domain="demo-site.203-0-113-5.sslip.io"):
    raw = open(CONFIGS["site"], encoding="utf-8").read()
    raw = re.sub(r"(?ms)^demo:\n(?:  .*\n)+", f'demo:\n  enabled: true\n  domain: "{domain}"\n', raw)
    path = tmp_path / "site.yaml"
    path.write_text(raw, encoding="utf-8")
    return str(path)


def test_describes_site_without_side_effects(capsys, env, tmp_path):
    data = info(capsys, "--config", CONFIGS["ramshill"])
    assert data["format"] == 1 and data["kind"] == "yalott-cottage-template"
    assert data["wsgi"] == "wsgi:app"                      # саме це gunicorn має імпортувати
    assert data["config"] == os.path.join("config", "examples", "ramshill.yaml")
    assert data["config_errors"] == [] and data["site_name"]
    assert data["database"] == str(tmp_path / "instance" / "ramshill.db")     # окрема база на конфіг
    assert data["demo"] == {"enabled": False, "domain": "", "password": False}
    assert not (tmp_path / "instance").exists()            # базу не створено — лише опис
    assert "db_file" not in data


def test_database_path_from_env(capsys, env, tmp_path):
    env.setenv("DATABASE_PATH", str(tmp_path / "data" / "cottage.db"))
    assert info(capsys, "--config", CONFIGS["blackhouse"])["database"] == str(tmp_path / "data" / "cottage.db")


def test_demo_mode_and_password_flag_without_secret(capsys, env, tmp_path):
    env.setenv("DEMO_PASSWORD", "дуже-секретний-пароль")
    out = manage.main(["deploy-info", "--config", demo_config(tmp_path)])
    text = capsys.readouterr().out
    assert out == 0
    data = json.loads(text)
    assert data["demo"] == {"enabled": True, "domain": "demo-site.203-0-113-5.sslip.io", "password": True}
    assert "дуже-секретний-пароль" not in text             # секрети не друкуються
    assert "test" * 16 not in text                          # SECRET_KEY теж


def test_placeholders_in_template_config(capsys, env):
    data = info(capsys, "--config", CONFIGS["site"])
    assert data["placeholders"] is True                    # шаблонний конфіг із «ЗАМІНИТИ» — не для робочого сайту


def test_config_errors_go_to_json(capsys, env, tmp_path):
    bad = tmp_path / "site.yaml"
    bad.write_text("brand:\n  name: 5\n", encoding="utf-8")
    data = info(capsys, "--config", str(bad))
    assert data["config_errors"]
    assert data["demo"]["enabled"] is False


def make_db(path, cfg="ramshill"):
    from conftest import app_module
    app = app_module.create_app({"SITE_CONFIG": CONFIGS[cfg], "DATABASE": str(path)})
    with app.app_context():
        pass
    return path


def test_db_file_ok(capsys, env, tmp_path):
    db = make_db(tmp_path / "pa" / "site.db")
    data = info(capsys, "--config", CONFIGS["ramshill"], "--db", str(db))
    f = data["db_file"]
    assert f["ok"] is True and f["problem"] == "" and f["integrity"] == "ok"
    assert {"objects", "bookings", "admin_users"} <= set(f["tables"])
    assert f["bookings"] == 0 and f["admins"] == 1
    assert oct(os.stat(db).st_mode & 0o777) == oct(0o600)   # перевірка нічого не змінила


@pytest.mark.parametrize("case", ["missing", "not_sqlite", "foreign", "old", "corrupt"])
def test_db_file_problems(capsys, env, tmp_path, case):
    path = tmp_path / "x.db"
    if case == "not_sqlite":
        path.write_text("SECRET_KEY=abc\n", encoding="utf-8")
    elif case == "foreign":
        sqlite3.connect(path).execute("CREATE TABLE users (id INTEGER)").connection.commit()
    elif case == "old":
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE objects (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE bookings (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
    elif case == "corrupt":
        make_db(path)
        raw = bytearray(path.read_bytes())
        page = 4096
        for i in range(page + 100, min(len(raw), 3 * page)):    # зіпсувати сторінки даних, не заголовок файлу
            raw[i] = 0xAB
        path.write_bytes(bytes(raw))
    f = info(capsys, "--config", CONFIGS["ramshill"], "--db", str(path))["db_file"]
    assert f["ok"] is False and f["problem"], f
    if case == "old":
        assert "старою версією" in f["problem"]
    if case == "foreign":
        assert "не база сайту" in f["problem"]


def test_init_db_still_refuses_old_database(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE objects (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()
    from site_config import load
    with pytest.raises(RuntimeError, match="старою версією"):
        db_.init_db(str(path), load(CONFIGS["ramshill"]))
