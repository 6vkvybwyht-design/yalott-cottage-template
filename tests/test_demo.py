"""Демо-режим для продажу: посилання з терміном дії, пароль, водяний знак у фото, noindex, свій домен,
прихована позначка авторства, захист від запуску копії на чужому домені."""

import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
from unittest import mock

import pytest
from PIL import Image, ImageChops, ImageStat

import demo
import manage
import notifications
import site_config
from conftest import CONFIGS, ROOT
from test_security import _assert_no_inline

DOMAIN = "forest.1-2-3-4.sslip.io"
PHOTO = "media/objects/a-frame/01.webp"


def strong(diff, threshold=25):
    """Скільки пікселів помітно змінилося (різниця яскравості понад threshold)."""
    return sum(diff.histogram()[threshold + 1:])


def clock(seconds_from_now):
    """Годинник лише для модуля demo (cookie сесії Flask живе своїм часом)."""
    return mock.patch.object(demo, "time", mock.Mock(time=mock.Mock(return_value=time.time() + seconds_from_now)))


def demo_config(tmp_path, **changes):
    """Демо-сайт Forest House (з фото) з увімкненим демо-режимом."""
    raw = open(CONFIGS["site"], encoding="utf-8").read()
    block = {"enabled": "true", "domain": f'"{DOMAIN}"', "days": "14", "link_version": "1"}
    block.update({k: str(v) for k, v in changes.items()})
    raw = re.sub(r"(?ms)^demo:\n(?:  .*\n)+", "demo:\n" + "".join(f"  {k}: {v}\n" for k, v in block.items()), raw)
    path = tmp_path / "site.yaml"          # «site» → фото з static/media, як у справжнього сайту
    path.write_text(raw, encoding="utf-8")
    return str(path)


@pytest.fixture
def demo_site(make_site, tmp_path):
    return make_site(demo_config(tmp_path))


def link(s, days=None, now=None):
    token, _ = demo.make_link_token(s.cfg, s.app.secret_key, days=days, now=now)
    return f"/demo/{token}"


def enter(s, **kw):
    r = s.client.get(link(s, **kw))
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    return r


# ---------- без посилання сайт закритий ----------

def test_without_link_everything_is_closed(demo_site):
    s = demo_site
    for url in ("/", "/a-frame", "/admin/login", "/admin/"):
        r = s.client.get(url)
        html = r.get_data(as_text=True)
        assert r.status_code == 403 and "персональним посиланням" in html, url
        assert "Forest House" not in html and "+380" not in html, url            # даних клієнта немає
        assert r.headers["X-Robots-Tag"].startswith("noindex"), url
    assert s.client.get("/api/availability").status_code == 403
    assert s.client.post("/api/bookings", json={}, headers={"X-CSRF-Token": s.csrf}).status_code == 403
    assert s.client.get(f"/static/{PHOTO}").status_code == 404                     # оригінали фото — ніколи
    assert s.client.get(f"/demo-img/{PHOTO}").status_code == 403                    # фото зі знаком — лише з посиланням
    assert s.client.get("/static/css/style.css").status_code == 200                 # стилі сторінки «закрито»
    assert s.client.get("/robots.txt").get_data(as_text=True) == "User-agent: *\nDisallow: /\n"


def test_link_opens_demo_with_all_marks(demo_site):
    s = demo_site
    assert enter(s).headers["Location"].endswith("/")
    r = s.client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Forest House" in html
    fid = s.app.extensions["demo_id"]
    assert f'data-yd="{fid}"' in html and "data-demo" in html
    assert '<meta name="robots" content="noindex, nofollow, noarchive, nosnippet, noimageindex">' in html
    assert r.headers["X-Robots-Tag"] == demo.NOINDEX and "no-store" in r.headers["Cache-Control"]
    assert re.search(r'class="demo-bar"><b>Демо</b> · Yalott Studio · до \d\d\.\d\d\.\d{4}', html)
    assert 'class="demo-mark"' in html
    assert f"/demo-img/{PHOTO}" in html and f"/static/{PHOTO}" not in html            # усі фото — зі знаком
    assert demo.find_marks(html) == [fid]
    # невидима позначка в тексті переживає копіювання тексту без HTML
    visible_text = re.sub(r"<[^>]+>", " ", html)
    assert fid in demo.find_marks(re.sub(r"yalott-demo:\w+", "", visible_text))
    hashes = re.search(r'data-dh="([^"]+)"', html).group(1).split(",")
    assert demo.host_hash(DOMAIN) in hashes and demo.host_hash("evil.example") not in hashes
    _assert_no_inline(html, "demo /")                                               # CSP без вбудованого коду


def test_demo_marks_absent_when_demo_is_off(make_site):
    s = make_site("site")
    html = s.html("/")
    assert "data-demo" not in html and "yalott-demo" not in html and "demo-bar" not in html
    assert f"/static/{PHOTO}" in html and s.client.get(f"/static/{PHOTO}").status_code == 200
    assert s.client.get(link(s)).status_code == 404                                 # маршрутів демо немає


# ---------- фото з вшитим водяним знаком ----------

def test_photos_are_watermarked(demo_site):
    s = demo_site
    enter(s)
    r = s.client.get(f"/demo-img/{PHOTO}")
    assert r.status_code == 200 and r.mimetype == "image/webp"
    assert r.headers["Cache-Control"] == "private, max-age=3600"
    marked = Image.open(io.BytesIO(r.data)).convert("RGB")
    original = Image.open(os.path.join(ROOT, "static", PHOTO)).convert("RGB")
    assert marked.size == original.size
    diff = ImageChops.difference(marked, original).convert("L")
    changed = strong(diff) / (marked.width * marked.height)
    assert changed > 0.025, changed                                                 # літери знака по всьому фото
    for quarter in ((0, 0), (1, 0), (0, 1), (1, 1)):                                # і в кожній чверті
        x, y = quarter[0] * marked.width // 2, quarter[1] * marked.height // 2
        part = diff.crop((x, y, x + marked.width // 2, y + marked.height // 2))
        assert strong(part) > part.width * part.height * 0.01, quarter
    plate = diff.crop((marked.width * 2 // 5, marked.height * 85 // 100, marked.width * 3 // 5, marked.height * 93 // 100))
    assert ImageStat.Stat(plate).mean[0] > 20                                        # плашка внизу по центру
    exif = Image.open(io.BytesIO(r.data)).getexif()
    assert exif[0x013B] == "Yalott Studio" and f"yalott-demo:{s.app.extensions['demo_id']}" in exif[0x010E]
    thumb = s.client.get("/demo-img/media/objects/a-frame/thumb/01.webp")
    assert thumb.status_code == 200 and Image.open(io.BytesIO(thumb.data)).width <= 600


def test_watermark_cache_and_paths(demo_site):
    s = demo_site
    enter(s)
    cache = os.path.join(s.app.instance_path, "demo-cache")
    shutil.rmtree(cache, ignore_errors=True)                                        # кеш спільний для тестів
    first = s.client.get(f"/demo-img/{PHOTO}").data
    files = os.listdir(cache)
    assert len(files) == 1 and oct(os.stat(os.path.join(cache, files[0])).st_mode & 0o777) == "0o600"
    assert s.client.get(f"/demo-img/{PHOTO}").data == first                          # з кешу, не перемальовує
    for bad in ("../app.py", "media/../../app.py", "css/style.css", "media/objects/none.webp", "media/../.env"):
        assert s.client.get(f"/demo-img/{bad}").status_code == 404, bad


def test_watermark_function_without_font(tmp_path, monkeypatch):
    """Шрифт загубився — водяний знак однаково ставиться (латиницею), сайт не падає."""
    monkeypatch.setattr(demo, "FONT_PATH", str(tmp_path / "none.ttf"))
    data = demo.watermark(os.path.join(ROOT, "static", PHOTO), "abc123abc123")
    assert Image.open(io.BytesIO(data)).format == "WEBP"


# ---------- термін, скасування, підробка ----------

def test_link_expires(demo_site):
    s = demo_site
    r = s.client.get(link(s, now=time.time() - 15 * 86400))                        # видано 15 днів тому на 14
    assert r.status_code == 403 and "Термін демо минув" in r.get_data(as_text=True)
    enter(s)
    assert s.client.get("/").status_code == 200
    with clock(14 * 86400 + 60):
        r = s.client.get("/")
    assert r.status_code == 403 and "Термін демо минув" in r.get_data(as_text=True)


def test_custom_days(demo_site):
    s = demo_site
    enter(s, days=3)
    with clock(2 * 86400):
        assert s.client.get("/").status_code == 200
    with clock(4 * 86400):
        assert s.client.get("/").status_code == 403


def test_tampered_link_refused(demo_site):
    s = demo_site
    token = link(s).rsplit("/", 1)[1]
    for bad in (token[:-2] + "xx", "abc", token + "a"):
        assert s.client.get(f"/demo/{bad}").status_code == 403
    assert s.client.get("/").status_code == 403


def test_link_from_other_secret_key_refused(demo_site):
    token, _ = demo.make_link_token(demo_site.cfg, "інший-ключ" * 4)
    assert demo_site.client.get(f"/demo/{token}").status_code == 403


def test_link_version_revokes_old_links_and_sessions(make_site, tmp_path):
    s = make_site(demo_config(tmp_path))
    old = link(s)
    enter(s)
    s2_path = demo_config(tmp_path, link_version=2)
    import app as app_module
    newer = app_module.create_app({"SITE_CONFIG": s2_path, "DATABASE": s.db_path})
    client = newer.test_client()
    with s.client.session_transaction() as old_session:
        grant = dict(old_session["demo"])
    with client.session_transaction() as sess:
        sess["demo"] = grant                                                          # та сама cookie, що була
    r = client.get("/")
    assert r.status_code == 403 and "Посилання вимкнено" in r.get_data(as_text=True)
    assert client.get(old).status_code == 403


# ---------- свій домен ----------

def test_foreign_domain_refused(demo_site):
    s = demo_site
    assert s.client.get(link(s), base_url=f"https://{DOMAIN}").status_code == 302
    assert s.client.get("/", base_url=f"https://{DOMAIN}").status_code == 200
    for host in ("evil.example", "forest.1-2-3-4.sslip.io.evil.example", "copy-of-forest.com"):
        r = s.client.get("/", base_url=f"https://{host}")
        assert r.status_code == 403 and "працює лише за нашою адресою" in r.get_data(as_text=True), host
        assert "Forest House" not in r.get_data(as_text=True)
    assert s.client.get(link(s), base_url="https://evil.example").status_code == 403


# ---------- пароль ----------

def test_password(make_site, tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "ліс-2026")
    s = make_site(demo_config(tmp_path))
    assert enter(s).headers["Location"].endswith("/demo/password")
    assert s.client.get("/").headers["Location"].endswith("/demo/password")
    form = s.client.get("/demo/password").get_data(as_text=True)
    assert 'name="csrf"' in form and "Введіть пароль" in form and "Forest House" not in form
    with s.client.session_transaction() as sess:
        csrf = sess["csrf"]
    assert s.client.post("/demo/password", data={"password": "ліс-2026"}).status_code == 400   # без CSRF
    assert s.client.post("/demo/password", data={"password": "ні", "csrf": csrf}).status_code == 401
    r = s.client.post("/demo/password", data={"password": "ліс-2026", "csrf": csrf})
    assert r.status_code == 302 and s.client.get("/").status_code == 200
    monkeypatch.setenv("DEMO_PASSWORD", "новий-пароль")                               # змінили пароль
    assert s.client.get("/").headers["Location"].endswith("/demo/password")


def test_password_attempts_limited(make_site, tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "секрет-демо")
    s = make_site(demo_config(tmp_path))
    enter(s)
    with s.client.session_transaction() as sess:
        csrf = sess["csrf"]
    codes = [s.client.post("/demo/password", data={"password": f"x{i}", "csrf": csrf},
                           headers={"X-Forwarded-For": "203.0.113.9"}).status_code for i in range(6)]
    assert codes == [401] * 5 + [429]
    r = s.client.post("/demo/password", data={"password": "секрет-демо", "csrf": csrf},
                      headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 429                                                       # навіть правильний — пауза


# ---------- демо працює як сайт ----------

def test_booking_in_demo_marked_for_telegram(demo_site):
    s = demo_site
    enter(s)
    with s.client.session_transaction() as sess:
        s.csrf = sess["csrf"]
    with mock.patch.object(notifications, "booking_message", wraps=notifications.booking_message) as msg:
        assert s.book("a-frame").status_code == 201
    assert msg.call_args[0][1] == "🧪 ДЕМО · Forest House"


def test_admin_in_demo_needs_link_first(demo_site):
    s = demo_site
    assert s.client.get("/admin/login").status_code == 403
    enter(s)
    assert s.client.get("/admin/login").status_code == 200
    s.login()
    assert s.client.get("/admin/api/data").status_code == 200


# ---------- конфіг ----------

@pytest.mark.parametrize("demo_block, message", [
    ({"enabled": True}, "у демо-режимі потрібен домен"),
    ({"enabled": True, "domain": "https://x.sslip.io"}, "лише ім'я сайту без https://"),
    ({"enabled": True, "domain": "x.sslip.io/demo"}, "лише ім'я сайту"),
    ({"enabled": "так", "domain": "x.sslip.io"}, "має бути true або false"),
    ({"enabled": True, "domain": "x.sslip.io", "days": 0}, "days: не може бути менше 1"),
    ({"enabled": True, "domain": "x.sslip.io", "days": 365}, "days: не може бути більше 90"),
    ({"enabled": True, "domain": "x.sslip.io", "password": "123"}, "Секрети зберігаються ТІЛЬКИ"),
])
def test_demo_config_errors(demo_block, message):
    raw = site_config.read_yaml(CONFIGS["ramshill"])
    raw["demo"] = demo_block
    assert message in "\n".join(site_config.validate(raw, check_photos=False)[0])


def test_shipped_configs_have_demo_off():
    for path in CONFIGS.values():
        assert site_config.load(path).demo["enabled"] is False


def test_fingerprint_stable_and_unique():
    a, b = site_config.load(CONFIGS["ramshill"]), site_config.load(CONFIGS["blackhouse"])
    assert demo.fingerprint(a, "k" * 40) == demo.fingerprint(a, "k" * 40)
    assert len({demo.fingerprint(a, "k" * 40), demo.fingerprint(b, "k" * 40), demo.fingerprint(a, "z" * 40)}) == 3
    assert demo.find_marks("текст" + demo.invisible_mark("0123456789ab") + "далі") == ["0123456789ab"]


# ---------- команди ----------

def test_demo_link_command(tmp_path, capsys, make_site):
    path = demo_config(tmp_path)
    assert manage.main(["demo-link", "--config", path, "--days", "3"]) == 0
    out = capsys.readouterr().out
    url = re.search(rf"https://{re.escape(DOMAIN)}/demo/(\S+)", out)
    assert url and "діє 3 дн." in out and "yalott-demo:" in out and "link_version" in out
    count = int(re.search(r"підготовлено заздалегідь: (\d+)", out).group(1))
    assert count >= 100                                                              # усі фото Forest House
    s = make_site(path)
    assert s.client.get(f"/demo/{url.group(1)}").status_code == 302                  # посилання з команди працює
    assert manage.main(["demo-link", "--config", CONFIGS["ramshill"]]) == 1           # демо вимкнено
    assert "Демо-режим вимкнено" in capsys.readouterr().out


def test_demo_find_command(demo_site, tmp_path, capsys):
    s = demo_site
    enter(s)
    page = tmp_path / "stolen.html"
    page.write_text(s.html("/"), encoding="utf-8")
    assert manage.main(["demo-find", str(page)]) == 0
    assert f"yalott-demo:{s.app.extensions['demo_id']}" in capsys.readouterr().out
    photo = tmp_path / "stolen.webp"
    photo.write_bytes(s.client.get(f"/demo-img/{PHOTO}").data)
    assert manage.main(["demo-find", str(photo)]) == 0
    clean = tmp_path / "clean.html"
    clean.write_text("<html>звичайний сайт</html>", encoding="utf-8")
    assert manage.main(["demo-find", str(clean)]) == 1


def test_check_warns_about_demo_mode(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "c.db"))
    manage.main(["check", "--config", demo_config(tmp_path)])
    assert "сайт у ДЕМО-режимі" in capsys.readouterr().out


# ---------- копія на чужому домені в справжньому браузері ----------

BROWSER_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const [base, entry] = process.argv.slice(2);
  const b = await chromium.launch(); const ctx = await b.newContext(); const p = await ctx.newPage();
  const errors = []; p.on('pageerror', e => errors.push(e.message));
  // 1) справжнє демо (дозволений хост 127.0.0.1): сайт працює
  await p.goto(base + entry); await p.waitForSelector('.cal-day', { timeout: 15000 });
  const ownOk = await p.$$eval('.cal-day', d => d.length) > 0;
  const html = await p.content();
  // 2) «вкрадена» копія: той самий HTML, стилі й скрипти, але на чужому домені
  await ctx.route(/^https:\/\/copy-of-site\.example\//, async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/') return route.fulfill({ body: html, contentType: 'text/html' });
    const res = await route.fetch({ url: base + url.pathname + url.search });
    return route.fulfill({ response: res });
  });
  const copy = await ctx.newPage();
  await copy.goto('https://copy-of-site.example/'); await copy.waitForTimeout(800);
  const text = await copy.evaluate(() => document.body.innerText);
  const calendar = await copy.$$eval('.cal-day', d => d.length);
  console.log(JSON.stringify({ ownOk, text, calendar, errors }));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_copied_page_disables_itself_on_foreign_domain(make_site, tmp_path):
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('playwright')"], capture_output=True, cwd=ROOT).returncode:
        pytest.skip("немає node + playwright — перевірку в браузері пропущено")
    from werkzeug.serving import make_server

    s = make_site(demo_config(tmp_path))
    server = make_server("127.0.0.1", 0, s.app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    script = tmp_path / "copy.js"
    script.write_text(BROWSER_SCRIPT, encoding="utf-8")
    try:
        run = subprocess.run([node, str(script), f"http://127.0.0.1:{server.server_port}", link(s)],
                             capture_output=True, text=True, timeout=120, cwd=ROOT)
    finally:
        server.shutdown()
    assert run.returncode == 0, run.stderr[-2000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["ownOk"] and result["errors"] == []
    assert "Демо-версія Yalott Studio" in result["text"] and "Forest House" not in result["text"]
    assert result["calendar"] == 0


def test_templates_load_photos_only_through_media_url():
    """Фото в шаблонах — лише через media_url(): інакше в демо воно піде без водяного знака (і з 404)."""
    import glob
    for path in glob.glob(os.path.join(ROOT, "templates", "**", "*.html"), recursive=True):
        text = open(path, encoding="utf-8").read()
        for arg in re.findall(r"url_for\(\s*'static'\s*,\s*filename\s*=\s*([^)]+)\)", text):
            assert arg.strip() in ("''", '""'), f"{os.path.relpath(path, ROOT)}: url_for('static', filename={arg}) — " \
                                                "для фото використовуйте media_url()"
