"""Безпека з коробки (взірець — svi-cottages-demo, PR #8):

  1. підбір пароля адмінки: 5 спроб з IP / 10 на логін → пауза 15 хв, без sleep;
  2. справжня IP за Caddy (ProxyFix) — ліміти не обходяться підробленим X-Forwarded-For;
  3. CSRF на всіх формах, зокрема на вході й виході;
  4. сесія 12 год, зміна пароля виганяє старі сесії; cookie Secure, HttpOnly, SameSite;
  5. жодних вбудованих <script>, обробників і стилів — сайт працює під суворим CSP;
  6. посилання iCal — лише https:// і адреси в інтернеті (SSRF);
  7. SECRET_KEY лише з .env — без нього сайт не стартує;
  8. права на базу 600, тека 700;
  9. ліміт заявок з однієї IP і перевірка всіх полів форми на сервері.
"""

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import threading
import time
from datetime import timedelta
from unittest import mock

import pytest
from werkzeug.security import generate_password_hash

import app as app_module
import database as db_
import security
import site_config
from conftest import CONFIGS, ROOT

ADMIN_IP, OTHER_IP = "203.0.113.5", "198.51.100.9"


def login(s, password="demo2026", ip=ADMIN_IP, username="admin", csrf=None):
    """Вхід через форму, як у браузері за Caddy: Caddy дописує справжню IP у кінець X-Forwarded-For."""
    s.client.get("/admin/login")
    with s.client.session_transaction() as sess:
        token = sess.get("csrf", "")
    return s.client.post("/admin/login", headers={"X-Forwarded-For": ip},
                         data={"username": username, "password": password, "csrf": token if csrf is None else csrf})


def api_ok(s):
    return s.client.get("/admin/api/data").status_code == 200


@pytest.fixture
def site(make_site):
    return make_site("ramshill")


# ---------- 1. підбір пароля ----------

def test_login_works(site):
    r = login(site)
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/")
    assert api_ok(site)


def test_bruteforce_from_one_ip_is_blocked_even_with_right_password(site):
    for _ in range(security.LOGIN_MAX_PER_IP):
        assert login(site, "wrong-password").status_code == 401
    r = login(site)                                          # правильний пароль, але IP на паузі
    assert r.status_code == 429 and "Забагато невдалих спроб" in r.get_data(as_text=True)
    assert not api_ok(site)
    assert login(site, ip=OTHER_IP).status_code == 302       # власник з іншої IP — входить


def test_bruteforce_on_one_login_from_many_ips_is_blocked(site):
    for i in range(security.LOGIN_MAX_PER_USER):
        login(site, "wrong", ip=f"192.0.2.{i + 1}")
    assert login(site, ip="198.51.100.77").status_code == 429
    assert login(site, ip="198.51.100.78", username="ADMIN").status_code == 429   # регістр логіна не допомагає


def test_block_expires_after_15_minutes(site):
    for _ in range(security.LOGIN_MAX_PER_IP):
        login(site, "wrong")
    assert login(site).status_code == 429
    with mock.patch.object(security, "now", return_value=time.time() + security.LOGIN_WINDOW + 5):
        assert login(site).status_code == 302


def test_block_is_shared_between_workers(make_site):
    """Два воркери gunicorn = два застосунки з однією базою: лічильник спільний."""
    a = make_site("ramshill")
    b = app_module.create_app({"SITE_CONFIG": CONFIGS["ramshill"], "DATABASE": a.db_path}).test_client()
    for _ in range(security.LOGIN_MAX_PER_IP):
        login(a, "wrong")
    b.get("/admin/login")
    with b.session_transaction() as sess:
        token = sess["csrf"]
    r = b.post("/admin/login", headers={"X-Forwarded-For": ADMIN_IP},
               data={"username": "admin", "password": "demo2026", "csrf": token})
    assert r.status_code == 429


def test_no_sleep_during_login(site):
    """Пауза — лічильником у базі, а не sleep: sleep тримав би воркер і гальмував увесь сайт."""
    with mock.patch("time.sleep", side_effect=AssertionError("sleep у вході в адмінку")):
        for _ in range(security.LOGIN_MAX_PER_IP + 2):
            login(site, "wrong")


def test_success_resets_counter_and_old_rows_are_pruned(site):
    for _ in range(security.LOGIN_MAX_PER_IP - 1):
        login(site, "wrong")
    assert login(site).status_code == 302
    conn = db_.connect(site.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM rate_events WHERE kind LIKE 'login%'").fetchone()[0] == 0
        conn.execute("INSERT INTO rate_events (kind, key, at) VALUES ('login-ip', 'x', ?)", (time.time() - 2 * 86400,))
        security.record_login_failure(conn, "1.2.3.4", "admin")
        assert conn.execute("SELECT COUNT(*) FROM rate_events WHERE key = 'x'").fetchone()[0] == 0
    finally:
        conn.close()


def test_unknown_user_takes_similar_time(site):
    t0 = time.perf_counter()
    login(site, "wrong", username="admin", ip="192.0.2.200")
    known = time.perf_counter() - t0
    t0 = time.perf_counter()
    login(site, "wrong", username="nobody", ip="192.0.2.201")
    unknown = time.perf_counter() - t0
    assert abs(known - unknown) < max(known, unknown) * 0.8 + 0.05


# ---------- 3. CSRF ----------

def test_login_requires_csrf(site):
    assert login(site, csrf="").headers["Location"].endswith("/admin/login")
    assert login(site, csrf="підроблений").headers["Location"].endswith("/admin/login")
    with site.client.session_transaction() as sess:
        sess.pop("csrf", None)                               # порожній токен і в сесії, і у формі
    r = site.client.post("/admin/login", data={"username": "admin", "password": "demo2026", "csrf": ""})
    assert r.headers["Location"].endswith("/admin/login")
    assert not api_ok(site)


def test_logout_requires_csrf(site):
    login(site)
    site.client.post("/admin/logout", data={})               # чужий сайт не може «викинути» власника
    assert api_ok(site)
    with site.client.session_transaction() as sess:
        token = sess["csrf"]
    site.client.post("/admin/logout", data={"csrf": token})
    assert not api_ok(site)


def test_every_post_form_has_csrf_token(make_site):
    for name in CONFIGS:
        s = make_site(name)
        pages = [s.html("/admin/login")]
        login(s)
        pages += [s.html("/admin/"), s.html("/")] + [s.html(f"/{o['slug']}") for o in s.cfg.objects]
        for html in pages:
            for form in re.findall(r"<form\b[^>]*>.*?</form>", html, flags=re.S | re.I):
                if re.search(r'method="post"', form, re.I):
                    assert 'name="csrf"' in form, form[:200]


def test_non_latin_csrf_token_does_not_crash(site):
    """Знайдено цим тестом: compare_digest падав на кирилиці — сервер віддавав 500 замість відмови."""
    assert login(site, csrf="підроблений").status_code == 302
    r = site.client.post("/api/bookings", json={}, headers={"X-CSRF-Token": "токен".encode().decode("latin-1")})
    assert r.status_code == 400


def test_api_requires_csrf_header(site):
    login(site)
    big = site.ids["big"]
    assert site.client.post("/admin/api/object-prices", json={"id": big, "price": 1, "tiers": []}).status_code == 400
    assert site.client.post("/api/bookings", json={"objectId": big}).status_code == 400


# ---------- 4. сесія ----------

def test_session_cookie_flags_and_12_hours(make_site, monkeypatch):
    monkeypatch.delenv("SESSION_COOKIE_SECURE")              # як на сервері: змінна не задана
    app = app_module.create_app({"SITE_CONFIG": CONFIGS["ramshill"],
                                 "DATABASE": os.path.join(make_site("ramshill").db_path + "-2")})
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True and app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.permanent_session_lifetime == timedelta(hours=12)
    client = app.test_client()
    client.get("/admin/login", base_url="https://localhost")
    with client.session_transaction(base_url="https://localhost") as sess:
        token = sess["csrf"]
    r = client.post("/admin/login", base_url="https://localhost",
                    data={"username": "admin", "password": "demo2026", "csrf": token})
    cookie = r.headers.get("Set-Cookie", "")
    for flag in ("Secure", "HttpOnly", "SameSite=Lax", "Expires="):
        assert flag in cookie, flag


def test_session_expires_after_12_hours(site):
    login(site)
    assert api_ok(site)
    later = time.time() + 12 * 3600 + 60
    with mock.patch("itsdangerous.timed.time.time", return_value=later):
        assert site.client.get("/admin/api/data").status_code == 401


def test_password_change_logs_out_old_sessions(site):
    login(site)
    assert api_ok(site)
    conn = db_.connect(site.db_path)
    conn.execute("UPDATE admin_users SET password_hash = ? WHERE username = 'admin'",
                 (generate_password_hash("new-strong-password"),))
    conn.close()
    assert site.client.get("/admin/api/data").status_code == 401
    assert site.client.get("/admin/").status_code == 302


def test_set_password_command_logs_out_old_sessions(site):
    login(site)
    db_.set_password(site.db_path, "admin", "another-strong-pass")
    assert not api_ok(site)


def test_forged_session_without_password_fingerprint_rejected(site):
    with site.client.session_transaction() as sess:
        sess["admin_id"] = 1                                 # навіть із правильним SECRET_KEY без відбитка не пускає
    assert not api_ok(site)


# ---------- 2, 9. справжня IP і ліміт заявок ----------

def test_client_ip_is_last_forwarded_hop(site):
    app = app_module.create_app({"SITE_CONFIG": CONFIGS["ramshill"], "DATABASE": site.db_path})
    seen = []

    @app.get("/_ip")
    def _ip():
        seen.append(app_module.client_ip())
        return "ok"
    app.test_client().get("/_ip", headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.50"})
    assert seen == ["203.0.113.50"]                          # «адреса» відвідувача ігнорується


def test_booking_rate_limit_cannot_be_bypassed_with_fake_forwarded_for(site):
    codes = []
    for i in range(security.BOOKING_MAX_PER_IP + 2):
        r = site.client.post("/api/bookings", json={"website": ""},
                             headers={"X-CSRF-Token": site.csrf, "X-Forwarded-For": f"10.0.0.{i}, 203.0.113.60"})
        codes.append(r.status_code)
    assert codes[-1] == 429 and codes.count(429) == 2
    r = site.client.post("/api/bookings", json={}, headers={"X-CSRF-Token": site.csrf, "X-Forwarded-For": "203.0.113.61"})
    assert r.status_code == 400                              # інша справжня IP — не заблокована


def test_booking_limit_shared_between_workers(site):
    other = app_module.create_app({"SITE_CONFIG": CONFIGS["ramshill"], "DATABASE": site.db_path}).test_client()
    other.get("/")
    with other.session_transaction() as sess:
        token = sess["csrf"]
    for _ in range(security.BOOKING_MAX_PER_IP):
        site.client.post("/api/bookings", json={}, headers={"X-CSRF-Token": site.csrf, "X-Forwarded-For": "203.0.113.70"})
    r = other.post("/api/bookings", json={}, headers={"X-CSRF-Token": token, "X-Forwarded-For": "203.0.113.70"})
    assert r.status_code == 429


def test_booking_fields_are_cleaned(site):
    objects = {o["id"]: o for o in site.get("/api/availability")["objects"].values()}
    objects = {int(k): v for k, v in objects.items()}
    body = {"name": "  Оле\x00на\n\rІван‮ко ", "phone": "+38 050\t111 22 33", "comment": "рядок 1\r\nрядок 2\x07",
            "objectId": site.ids["big"], "checkIn": "2026-11-10", "checkOut": "2026-11-12", "guests": 2, "rules": True}
    v = app_module.validate_booking(body, objects, ["chan"], "2026-11-03")
    assert v["name"] == "Олена Іванко" and v["phone"] == "+38 050 111 22 33" and v["comment"] == "рядок 1\nрядок 2"


@pytest.mark.parametrize("change", [
    {"guests": True}, {"guests": "2; DROP TABLE"}, {"guests": 2.5}, {"objectId": [1]}, {"objectId": True},
    {"rules": "так"}, {"rules": 1}, {"phone": "+380<script>1112233"}, {"name": {"a": 1}}, {"checkIn": 20261110},
    {"checkOut": "2026-11-12T00:00"}, {"extras": "chan"},
])
def test_booking_rejects_wrong_types(site, change):
    body = {"name": "Олена", "phone": "+380501112233", "objectId": site.ids["big"], "checkIn": "2026-11-10",
            "checkOut": "2026-11-12", "guests": 2, "rules": True, **change}
    r = site.client.post("/api/bookings", json=body, headers={"X-CSRF-Token": site.csrf})
    if change == {"extras": "chan"}:                         # не список — послуги просто ігноруються
        assert r.status_code == 201 and r.get_json()["booking"]["extras"] == []
    else:
        assert r.status_code == 400, (change, r.get_json())


def test_oversized_request_rejected(site):
    r = site.client.post("/api/bookings", data="x" * (security.MAX_REQUEST_BYTES + 1),
                         headers={"X-CSRF-Token": site.csrf, "Content-Type": "application/json"})
    assert r.status_code == 413


# ---------- 7. SECRET_KEY ----------

@pytest.mark.parametrize("value", ["", "   ", "change-me", "secret", "dev"])
def test_no_secret_key_no_start(make_site, monkeypatch, value):
    monkeypatch.setenv("SECRET_KEY", value)
    with pytest.raises(security.SecurityConfigError) as exc:
        app_module.create_app({"SITE_CONFIG": CONFIGS["ramshill"], "DATABASE": make_site().db_path + "-x"})
    assert "SECRET_KEY" in str(exc.value) and "token_hex" in str(exc.value)


def test_no_secret_key_stops_wsgi_with_message(monkeypatch, capsys):
    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(SystemExit) as exc:
        app_module._create_default_app()
    assert "Не задано SECRET_KEY" in str(exc.value.code)


def test_no_secret_key_file_fallback():
    source = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    assert "secret_key\")" not in source and "token_hex(32)" not in source   # немає запасного ключа з файлу


# ---------- 8. права на базу ----------

def test_database_and_folder_private(site):
    assert stat.S_IMODE(os.stat(site.db_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(site.db_path)).st_mode) == 0o700


def test_permissions_fixed_on_restart(site):
    """Старий сайт із ширшими правами — виправляються самі під час запуску."""
    os.chmod(site.db_path, 0o644)
    os.chmod(os.path.dirname(site.db_path), 0o755)
    db_.init_db(site.db_path, site.cfg)
    assert stat.S_IMODE(os.stat(site.db_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(site.db_path)).st_mode) == 0o700


# ---------- демо-доступ ----------

def test_demo_password_shown_only_on_demo_site(make_site):
    assert "demo2026" not in make_site("ramshill").html("/admin/login")
    assert "demo2026" in make_site("ramshill", demo=True).html("/admin/login")


def test_no_known_password_on_production_site(make_site, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    s_path = make_site().db_path + "-prod"
    app = app_module.create_app({"SITE_CONFIG": CONFIGS["ramshill"], "DATABASE": s_path})
    client = app.test_client()
    client.get("/admin/login")
    with client.session_transaction() as sess:
        token = sess["csrf"]
    r = client.post("/admin/login", data={"username": "admin", "password": "demo2026", "csrf": token})
    assert r.status_code == 401                              # demo2026 на робочому сайті не працює
    assert "demo2026" not in client.get("/admin/login").get_data(as_text=True)


def test_demo_site_shows_demo_password(make_site, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    app = app_module.create_app({"SITE_CONFIG": CONFIGS["ramshill"], "DATABASE": make_site().db_path + "-demo",
                                 "DEMO_DATA": True})
    assert "demo2026" in app.test_client().get("/admin/login").get_data(as_text=True)


# ---------- 5. заголовки й CSP ----------

def test_security_headers_everywhere(site):
    login(site)
    for url in ("/", "/big", "/admin/login", "/admin/", "/немає", "/api/availability", "/theme.css"):
        h = site.client.get(url).headers
        csp = h.get("Content-Security-Policy", "")
        assert "script-src 'self'" in csp and "frame-ancestors 'self'" in csp and "object-src 'none'" in csp, url
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp, url
        assert h.get("X-Content-Type-Options") == "nosniff" and h.get("X-Frame-Options") == "SAMEORIGIN", url
        assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin", url
    assert site.client.get("/admin/").headers.get("X-Robots-Tag") == "noindex, nofollow"
    assert "upgrade-insecure-requests" not in site.client.get("/").headers["Content-Security-Policy"]
    https = site.client.get("/", headers={"X-Forwarded-Proto": "https"}).headers["Content-Security-Policy"]
    assert "upgrade-insecure-requests" in https


def _assert_no_inline(html, where):
    for m in re.finditer(r"<script\b([^>]*)>", html, flags=re.I):
        attrs = m.group(1)
        assert re.search(r"\bsrc=", attrs) or 'type="application/ld+json"' in attrs, f"{where}: <script{attrs}>"
    assert not re.search(r"<[a-z][^>]*\son[a-z]+\s*=", html, flags=re.I), f"{where}: вбудований обробник подій"
    assert "javascript:" not in html.lower(), where
    assert not re.search(r"<style\b", html, flags=re.I), f"{where}: вбудований <style>"
    assert not re.search(r"<[a-z][^>]*\sstyle\s*=", html, flags=re.I), f"{where}: атрибут style="


def test_pages_have_no_inline_scripts_handlers_or_styles(make_site, tmp_path):
    text = open(CONFIGS["ramshill"], encoding="utf-8").read().replace('primary_color: ""', 'primary_color: "#123456"')
    custom = tmp_path / "ramshill.yaml"
    custom.write_text(text, encoding="utf-8")
    for name in list(CONFIGS) + [str(custom)]:
        s = make_site(name)
        pages = ["/", "/admin/login", "/немає"] + [f"/{o['slug']}" for o in s.cfg.objects]
        for url in pages:
            _assert_no_inline(s.client.get(url).get_data(as_text=True), f"{name}{url}")
        login(s)
        _assert_no_inline(s.html("/admin/"), f"{name}/admin/")


def test_scripts_do_not_build_inline_handlers():
    """admin.js і main.js будують HTML рядками — у них теж не має бути onclick= чи style=."""
    for name in ("main.js", "admin.js", "api.js", "pricing.js"):
        js = open(os.path.join(ROOT, "static", "js", name), encoding="utf-8").read()
        assert not re.search(r"""['"<][^'"]*\son[a-z]+\s*=""", js), name
        assert not re.search(r"""<[a-z][^'"]*\sstyle\s*=""", js), name
        assert "eval(" not in js and "new Function" not in js and "javascript:" not in js, name


# ---------- 6. iCal: лише https і інтернет ----------

@pytest.mark.parametrize("url", ["http://admin.booking.com/ical.ics", "ftp://x.com/a", "https://localhost/a.ics",
                                 "https://127.0.0.1/a.ics", "https://10.0.0.5/x", "https://192.168.1.1/x",
                                 "https://169.254.169.254/latest/meta-data", "https://[::1]/x", "https://router.local/x",
                                 "https://user:pass@example.com/x", "https://intranet/x", "javascript:alert(1)", ""])
def test_ical_url_format_refused(url):
    with pytest.raises(security.UnsafeUrlError):
        security.check_url_format(url)


def test_ical_url_ok():
    assert security.check_url_format(" https://admin.booking.com/hotel/ical/abc.ics?t=1 ").startswith("https://")


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "100.64.0.1"])
def test_domain_pointing_inside_refused(addr):
    family = socket.AF_INET6 if ":" in addr else socket.AF_INET
    with mock.patch.object(socket, "getaddrinfo", return_value=[(family, 1, 6, "", (addr, 443))]):
        with pytest.raises(security.UnsafeUrlError):
            security.fetch_public("https://calendar.example/feed.ics")


def test_redirect_to_inside_refused():
    handler = security._SafeRedirect()
    with mock.patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, 1, 6, "", ("127.0.0.1", 443))]):
        with pytest.raises(security.UnsafeUrlError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x")
    with pytest.raises(security.UnsafeUrlError):
        handler.redirect_request(None, None, 302, "Found", {}, "http://admin.booking.com/x")


def test_config_rejects_unsafe_ical_links():
    raw = site_config.read_yaml(CONFIGS["ramshill"])
    raw["integrations"] = {"ical": {"big": "http://admin.booking.com/a.ics", "small": "https://10.0.0.1/x"},
                           "airbnb_url": "https://www.airbnb.com/calendar/ical/1.ics"}
    errors = "\n".join(site_config.validate(raw, check_photos=False)[0])
    assert "integrations → ical → big: Посилання має починатися з https://" in errors
    assert "integrations → ical → small: Посилання веде на внутрішню адресу" in errors
    assert "airbnb" not in errors


# ---------- 10. налаштування для сервера ----------

def test_env_example_secure_defaults():
    env = open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
    assert re.search(r"(?m)^SECRET_KEY=$", env)               # yalott new-site генерує ключ лише в порожній рядок
    assert re.search(r"(?m)^SESSION_COOKIE_SECURE=$", env)    # порожньо → Secure увімкнено
    assert re.search(r"(?m)^BEHIND_PROXY=1$", env)


def test_deploy_doc_has_security_steps():
    doc = open(os.path.join(ROOT, "DEPLOY.md"), encoding="utf-8").read()
    for step in ("sudo secure-site", "--no-cloudflare", "sudo security-check", "chmod 700", "chmod 600"):
        assert step in doc, step


# ---------- CSP у справжньому браузері ----------

BROWSER_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[2], pages = JSON.parse(process.argv[3]);
  const b = await chromium.launch(); const p = await b.newPage();
  const violations = [];
  p.on('console', m => { if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(p.url() + ': ' + m.text()); });
  p.on('pageerror', e => violations.push(p.url() + ': JS ' + e.message));
  for (const url of pages) { await p.goto(base + url, { waitUntil: 'load' }); await p.waitForTimeout(400); }
  await p.goto(base + '/admin/login');
  await p.fill('input[name=username]', 'admin'); await p.fill('input[name=password]', 'demo2026');
  await p.click('button.btn'); await p.waitForSelector('#stats .stat');
  for (const tab of ['calendar', 'prices']) { await p.click('[data-tab-btn=' + tab + ']'); await p.waitForTimeout(300); }
  console.log(JSON.stringify({ violations, adminOk: (await p.$$('#priceObjs form')).length > 0 }));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_strict_csp_breaks_nothing_in_browser(make_site, tmp_path):
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('playwright')"], capture_output=True, cwd=ROOT).returncode:
        pytest.skip("немає node + playwright — перевірку в браузері пропущено")
    from werkzeug.serving import make_server

    s = make_site("site")                                    # демо з фото, картою й усіма блоками
    server = make_server("127.0.0.1", 0, s.app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    script = tmp_path / "csp.js"
    script.write_text(BROWSER_SCRIPT, encoding="utf-8")
    pages = ["/"] + [f"/{o['slug']}" for o in s.cfg.objects]
    try:
        run = subprocess.run([node, str(script), f"http://127.0.0.1:{server.server_port}", json.dumps(pages)],
                             capture_output=True, text=True, timeout=120, cwd=ROOT)
    finally:
        server.shutdown()
    assert run.returncode == 0, run.stderr[-2000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["adminOk"]
    assert result["violations"] == [], "\n".join(result["violations"])
