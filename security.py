"""Безпека сайту — вмикається сама для кожного нового сайту, без ручних кроків.

  • справжня IP відвідувача за вебсервером (ProxyFix у app.py) — ліміти не обходяться підробленим
    X-Forwarded-For;
  • ліміти в базі (спільні для всіх воркерів gunicorn): вхід в адмінку й заявки на бронювання;
  • сесія адмінки: 12 год, відбиток пароля (зміна пароля виганяє всі старі входи);
  • заголовки безпеки, зокрема Content-Security-Policy без вбудованих скриптів і стилів;
  • очищення тексту з форм;
  • завантаження зовнішніх адрес (iCal у v2) — лише https і лише адреси в інтернеті (захист від SSRF).

Ліміти — у константах нижче. Таблиця rate_events лише додається (CREATE TABLE IF NOT EXISTS);
старі записи (старші за добу) видаляються самі, дані сайту не зачіпаються.
"""

import hashlib
import ipaddress
import re
import secrets
import socket
import time
import urllib.parse
import urllib.request

# ---------- ліміти ----------

LOGIN_WINDOW = 15 * 60       # секунд: за який час рахуються невдалі спроби входу й скільки триває пауза
LOGIN_MAX_PER_IP = 5         # невдалих спроб з однієї IP → пауза
LOGIN_MAX_PER_USER = 10      # невдалих спроб на один логін (з будь-яких IP) → пауза
BOOKING_WINDOW = 10 * 60     # секунд
BOOKING_MAX_PER_IP = 10      # спроб надіслати заявку з однієї IP за вікно
SESSION_HOURS = 12           # скільки діє вхід в адмінку
MAX_REQUEST_BYTES = 256 * 1024   # більший запит відхиляється одразу (форма бронювання — кілька сотень байтів)

# Значення SECRET_KEY, які трапляються в прикладах і туторіалах: з ними сесію адмінки можна підробити.
PLACEHOLDER_KEYS = {"secret", "secret-key", "secret_key", "change-me", "changeme", "dev", "development",
                    "your-secret-key", "your_secret_key", "test", "password", "flask", "key"}


def now():
    """Поточний час (окремою функцією — щоб тести могли «перемотати» годинник)."""
    return time.time()


class SecurityConfigError(Exception):
    """Сайт не можна запускати з такими налаштуваннями (пояснення — українською)."""


def require_secret_key(value):
    """SECRET_KEY береться ЛИШЕ з .env. Без нього (чи з прикладом на кшталт «change-me») сайт не стартує:
    інакше будь-хто, хто знає ключ, підробить сесію адмінки."""
    key = (value or "").strip()
    hint = ("Згенеруйте ключ:  python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "і впишіть рядок SECRET_KEY=… у файл .env (на сервері yalott new-site робить це сам).")
    if not key:
        raise SecurityConfigError("Не задано SECRET_KEY у файлі .env — сайт не запускається без нього.\n" + hint)
    if key.lower() in PLACEHOLDER_KEYS:
        raise SecurityConfigError(f"SECRET_KEY=«{key}» — це приклад, а не секрет.\n" + hint)
    return key


def weak_secret_key(value):
    """Ключ коротший за 32 символи — сайт працює, але manage.py check попередить."""
    return len((value or "").strip()) < 32


# ---------- ліміти в базі ----------

def _recent(db, kind, key, since, limit):
    return db.execute("SELECT at FROM rate_events WHERE kind = ? AND key = ? AND at > ? ORDER BY at DESC LIMIT ?",
                      (kind, key, since, limit)).fetchall()


def record(db, kind, key, at=None):
    at = now() if at is None else at
    db.execute("INSERT INTO rate_events (kind, key, at) VALUES (?, ?, ?)", (kind, str(key)[:120], at))
    db.execute("DELETE FROM rate_events WHERE at < ?", (at - 86400,))   # технічні записи старші за добу не потрібні


def wait_seconds(db, kind, key, limit, window, at=None):
    """Скільки секунд ще чекати (0 — можна). Пауза закінчується через window після найстарішої з останніх limit подій."""
    at = now() if at is None else at
    rows = _recent(db, kind, str(key)[:120], at - window, limit)
    return int(rows[-1]["at"] + window - at) + 1 if len(rows) >= limit else 0


def login_blocked(db, ip, username, at=None):
    """Пауза для входу: 5 невдалих спроб з IP або 10 на логін за 15 хв."""
    return max(wait_seconds(db, "login-ip", ip, LOGIN_MAX_PER_IP, LOGIN_WINDOW, at),
               wait_seconds(db, "login-user", username.lower(), LOGIN_MAX_PER_USER, LOGIN_WINDOW, at))


def record_login_failure(db, ip, username, at=None):
    record(db, "login-ip", ip, at)
    record(db, "login-user", username.lower(), at)


def clear_login_failures(db, ip, username):
    """Після успішного входу лічильники цієї IP і цього логіна скидаються."""
    db.execute("DELETE FROM rate_events WHERE (kind = 'login-ip' AND key = ?) OR (kind = 'login-user' AND key = ?)",
               (ip, username.lower()[:120]))


def booking_limited(db, ip, at=None):
    """True — забагато заявок з цієї IP. Інакше подію записано й заявку можна обробляти."""
    if wait_seconds(db, "booking-ip", ip, BOOKING_MAX_PER_IP, BOOKING_WINDOW, at):
        return True
    record(db, "booking-ip", ip, at)
    return False


# ---------- сесія адмінки ----------

def password_version(password_hash, secret):
    """Відбиток пароля в сесії: змінився пароль — усі старі входи недійсні."""
    return hashlib.sha256(f"{secret}:admin-session:{password_hash}".encode()).hexdigest()[:32]


def token_ok(sent, expected):
    """CSRF: порожній токен ніколи не проходить (і з порожнім у сесії теж)."""
    if not sent or not expected:
        return False
    # байтами: compare_digest не порівнює рядки з не-латинськими символами (інакше — помилка 500)
    return secrets.compare_digest(str(sent).encode("utf-8"), str(expected).encode("utf-8"))


# ---------- текст із форм ----------

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮  ⁦-⁩]")


def clean_text(value, limit, multiline=False):
    """Текст із форми: без керівних і «невидимих» символів (зокрема тих, що перевертають напрямок тексту);
    у короткі поля — без переносів рядків і зайвих пробілів."""
    s = value if isinstance(value, str) else ("" if value is None else str(value))
    s = _CONTROL.sub("", s).replace("\r\n", "\n").replace("\r", "\n")
    if multiline:
        s = "\n".join(" ".join(line.split()) for line in s.split("\n"))
        s = re.sub(r"\n{3,}", "\n\n", s)
    else:
        s = " ".join(s.split())
    return s.strip()[:limit]


# ---------- заголовки безпеки ----------

def content_security_policy(secure):
    """CSP сайту й адмінки. Скрипти й стилі — лише власні файли (без вбудованих), шрифти — Google Fonts,
    рамка — лише карта Google Maps. Новий зовнішній сервіс (аналітика, відео, віджет) треба дописати сюди."""
    rules = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-src https://www.google.com https://maps.google.com",
        "media-src 'self'",
        "manifest-src 'self'",
        "worker-src 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
    if secure:
        rules.append("upgrade-insecure-requests")
    return "; ".join(rules)


def security_headers(secure, admin=False):
    """Заголовки для кожної відповіді. HSTS додає Caddy (sudo secure-site): на http-сайті він шкодить."""
    headers = {
        "Content-Security-Policy": content_security_policy(secure),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if admin:
        headers["X-Robots-Tag"] = "noindex, nofollow"
        headers["Cache-Control"] = "no-store"
    return headers


# ---------- зовнішні адреси (iCal у v2): лише https і лише інтернет ----------

class UnsafeUrlError(ValueError):
    """Адресу не можна завантажувати (пояснення — українською)."""


def check_url_format(url):
    """Перевірка без мережі (для конфігу й форм адмінки): https://, справжнє ім'я сайту, не IP з локальної мережі."""
    url = (url or "").strip()
    if len(url) > 1000:
        raise UnsafeUrlError("Задовге посилання")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise UnsafeUrlError("Посилання має починатися з https://")
    if parts.username or parts.password:
        raise UnsafeUrlError("Посилання не може містити логін і пароль")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        raise UnsafeUrlError("Посилання веде на внутрішню адресу — такі календарі не завантажуються")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise UnsafeUrlError("Вкажіть повне посилання на сайт календаря (з доменом)")
    else:
        if not ip.is_global:
            raise UnsafeUrlError("Посилання веде на внутрішню адресу — такі календарі не завантажуються")
    return url


def check_public(url):
    """Повна перевірка перед завантаженням: формат + усі IP, на які вказує домен, — в інтернеті
    (не 127.0.0.1, не 10.x/192.168.x, не 169.254.169.254 тощо)."""
    url = check_url_format(url)
    parts = urllib.parse.urlsplit(url)
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise UnsafeUrlError("Не вдалося знайти сайт за посиланням — перевірте його")
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise UnsafeUrlError("Посилання веде на внутрішню адресу — такі календарі не завантажуються")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Переадресацію теж перевіряємо: https і адреса в інтернеті."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def fetch_public(url, timeout=15, max_bytes=2 * 1024 * 1024, user_agent="YalottCottage/1.0"):
    """Завантажує текст із зовнішньої https-адреси (для синхронізації iCal у v2). Кидає UnsafeUrlError."""
    check_public(url)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/calendar, */*"})
    with _opener.open(req, timeout=timeout) as resp:
        body = resp.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise UnsafeUrlError("Файл за посиланням завеликий")
    return body.decode("utf-8", errors="replace")
