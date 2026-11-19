"""Демо-режим для продажу: сайт із даними клієнта, але захищений від крадіжки.

Вмикається в config/site.yaml (розділ demo) — для кожного демо окремо, без змін коду:

  • доступ лише за посиланням із терміном дії (за замовчуванням 14 днів) — python manage.py demo-link;
    без посилання, після терміну чи з чужого домену — сторінка «Демо Yalott Studio» замість сайту;
  • необов'язковий пароль — DEMO_PASSWORD у .env (секрет, тому не в конфігу);
  • водяний знак вшитий у самі фото (оригінали в демо недоступні): типово — маленький підпис
    «Yalott Studio · демо» в куті (demo.watermark: subtle), або сітка на все фото (grid), або без нього (off);
  • noindex усюди: заголовок X-Robots-Tag, meta robots, robots.txt «Disallow: /»;
  • код не працює на чужому домені: сервер перевіряє домен, а скрипт сторінки вимикає сайт,
    якщо його скопіювали й відкрили деінде;
  • прихована позначка авторства: ідентифікатор демо (fingerprint) у коді сторінки, у невидимих символах
    тексту (переживає копіювання тексту), у метаданих кожного фото. Знайти його в копії:
    python manage.py demo-find ФАЙЛ.

Чесно про межі: публічну сторінку завжди можна сфотографувати чи переписати вручну. Ці заходи роблять
крадіжку помітною й незручною та дають доказ авторства, але не роблять її неможливою.
"""

import functools
import hashlib
import hmac
import io
import json
import os
import re
import time

from itsdangerous import BadSignature, URLSafeSerializer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "assets", "watermark.ttf")
WATERMARK_TEXT = "Демо · Yalott Studio"
SUBTLE_TEXT = "Yalott Studio · демо"
WATERMARK_VERSION = "9"            # змініть, якщо змінився вигляд водяного знака — кеш перегенерується
# Вигляд знака у фото (demo.watermark у конфігу):
#   subtle — один маленький напівпрозорий підпис у правому нижньому куті (типово);
#   grid   — діагональна сітка напису на все фото + плашка внизу й сітка поверх сторінки;
#   off    — без видимого знака (лишаються позначка в метаданих фото й решта захисту).
WATERMARK_STYLES = ("subtle", "grid", "off")            # змініть, якщо змінився вигляд водяного знака — кеш перегенерується
LOCAL_HOSTS = ("localhost", "127.0.0.1")
DEMO_PASSWORD_ATTEMPTS = 5         # невдалих спроб пароля з однієї IP за 15 хв
NOINDEX = "noindex, nofollow, noarchive, nosnippet, noimageindex"

# Без посилання сайт у демо не відкривається. Але ці шляхи потрібні самій сторінці «доступ закрито».
OPEN_PATHS = ("/demo/", "/static/css/", "/static/js/", "/static/media/brand/", "/theme.css", "/favicon.svg",
              "/robots.txt")


# ---------- налаштування ----------

def settings(site):
    """Розділ demo з конфігу (нормалізований у site_config)."""
    return site.demo


def enabled(site):
    return bool(site.demo["enabled"])


def password():
    return os.environ.get("DEMO_PASSWORD", "")


def fingerprint(site, secret):
    """Ідентифікатор цього демо: однаковий між перезапусками, різний для кожного сайту.
    Відтворити його може лише той, хто знає SECRET_KEY, — тож він є доказом авторства."""
    raw = f"yalott-demo|{site.key}|{site.brand['name']}|{site.demo['domain']}"
    return hmac.new(str(secret).encode(), raw.encode(), hashlib.sha256).hexdigest()[:12]


def host_hash(host):
    """FNV-1a (32 біти) — той самий, що рахує static/js/main.js, щоб перевірити домен у браузері."""
    h = 0x811C9DC5
    for byte in (host or "").lower().encode():
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def allowed_hosts(site):
    domain = site.demo["domain"]
    return ([domain] if domain else []) + list(LOCAL_HOSTS)


def host_ok(site, host):
    host = (host or "").split(":")[0].lower().rstrip(".")
    return not site.demo["domain"] or host in allowed_hosts(site)


# ---------- посилання з терміном дії ----------

def _serializer(secret):
    return URLSafeSerializer(secret, salt="yalott-demo-link")


def make_link_token(site, secret, days=None, now=None):
    """Токен посилання: підписаний SECRET_KEY, з датою закінчення й «версією» посилань із конфігу."""
    now = time.time() if now is None else now
    days = site.demo["days"] if days is None else days
    expires = int(now + days * 86400)
    token = _serializer(secret).dumps({"v": site.demo["link_version"], "exp": expires})
    return token, expires


def read_link_token(site, secret, token, now=None):
    """Дата закінчення, якщо посилання дійсне; інакше (причина, None)."""
    now = time.time() if now is None else now
    try:
        data = _serializer(secret).loads(token)
    except BadSignature:
        return "invalid", None
    if not isinstance(data, dict) or data.get("v") != site.demo["link_version"]:
        return "revoked", None
    if not isinstance(data.get("exp"), int) or data["exp"] <= now:
        return "expired", None
    return None, data["exp"]


def password_mark(secret):
    """Відбиток поточного DEMO_PASSWORD у сесії: змінили пароль — старі входи в демо недійсні."""
    pw = password()
    return hashlib.sha256(f"{secret}|demo-password|{pw}".encode()).hexdigest()[:24] if pw else ""


def access(site, session, secret, now=None):
    """None — доступ є; інакше причина: «no-link», «expired», «revoked», «password»."""
    now = time.time() if now is None else now
    grant = session.get("demo")
    if not isinstance(grant, dict):
        return "no-link"
    if grant.get("v") != site.demo["link_version"]:
        return "revoked"
    if not isinstance(grant.get("exp"), int) or grant["exp"] <= now:
        return "expired"
    if password() and grant.get("pw") != password_mark(secret):
        return "password"
    return None


def is_open_path(path):
    return path.startswith(OPEN_PATHS)


# ---------- невидима позначка в тексті ----------

_ZW0, _ZW1, _ZWSTART, _ZWEND = "​", "‌", "⁠", "⁣"


def invisible_mark(fid):
    """Ідентифікатор невидимими символами: копіюється разом із текстом, але не видно на сторінці."""
    bits = "".join(f"{int(ch, 16):04b}" for ch in fid)
    return _ZWSTART + "".join(_ZW1 if b == "1" else _ZW0 for b in bits) + _ZWEND


def find_marks(text):
    """Усі ідентифікатори демо, знайдені в тексті / HTML копії: явні позначки й невидимі символи."""
    found = set(re.findall(r"yalott-demo[:\s-]+([0-9a-f]{12})", text or ""))
    for chunk in re.findall(f"{_ZWSTART}([{_ZW0}{_ZW1}]+){_ZWEND}", text or ""):
        if len(chunk) % 4 == 0:
            found.add("".join(f"{int(chunk[i:i + 4].replace(_ZW0, '0').replace(_ZW1, '1'), 2):x}"
                              for i in range(0, len(chunk), 4)))
    return sorted(found)


# ---------- водяний знак у фото ----------

def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:          # файл шрифту загубився — латиницею вбудованим шрифтом Pillow
        return ImageFont.load_default(size=size)


def _exif(fid, domain):
    from PIL import Image
    exif = Image.Exif()
    exif[0x013B] = "Yalott Studio"                                                   # Artist
    exif[0x8298] = "© Yalott Studio. Демо-версія, використання заборонено."[:60]     # Copyright
    exif[0x010E] = f"yalott-demo:{fid} {domain}".strip()                             # ImageDescription
    return exif.tobytes()


@functools.lru_cache(maxsize=16)
def _subtle_layer(w, h):
    """Один маленький напівпрозорий підпис у правому нижньому куті (~50 % непрозорості).
    Щоб кадрування на сайті (object-fit: cover) не зрізало куток, у демо з subtle фото кадруються
    від правого нижнього кута (static/css/style.css, html[data-wm="subtle"])."""
    from PIL import Image, ImageDraw

    size = max(11, int(min(w, h) / 38))
    font = _font(size)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    left, top, right, bottom = d.textbbox((0, 0), SUBTLE_TEXT, font=font)
    margin_x, margin_y = max(8, int(w * 0.035)), max(8, int(h * 0.04))
    x, y = w - margin_x - (right - left) - left, h - margin_y - (bottom - top) - top
    d.text((x + 1, y + 1), SUBTLE_TEXT, font=font, fill=(0, 0, 0, 70))            # м'яка тінь — читається на небі
    d.text((x, y), SUBTLE_TEXT, font=font, fill=(255, 255, 255, 128))
    return layer


def _layer(w, h, style="grid"):
    if style == "subtle":
        return _subtle_layer(w, h)
    return _grid_layer(w, h)


@functools.lru_cache(maxsize=16)
def _grid_layer(w, h):
    """Прозорий шар із водяним знаком для фото розміру w×h. Не залежить від змісту фото, тож для кожного
    розміру (повне фото, мініатюра, у двох орієнтаціях) малюється один раз на процес."""
    from PIL import Image, ImageDraw

    size = max(15, int(max(w, h) / 50))            # на мініатюрах — не дрібніше 15 px, щоб не рябіло
    font = _font(size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), WATERMARK_TEXT, font=font)
    tw, th = right - left, bottom - top

    # діагональна сітка напису на всю фотографію: рівні рядки на великому полотні, повернутому цілком
    side = int((w * w + h * h) ** 0.5) + tw          # полотно, яке після повороту накриє все фото
    stamp = Image.new("RGBA", (tw + 4 + size // 7, th + 4 + size // 7), (0, 0, 0, 0))
    # світлі літери з темним контуром — знак читається і на небі, і на темній стіні; малюємо один раз
    ImageDraw.Draw(stamp).text((2 - left, 2 - top), WATERMARK_TEXT, font=font, fill=(255, 255, 255, 95),
                               stroke_width=max(1, size // 14), stroke_fill=(0, 0, 0, 60))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    gap_x, gap_y = int(tw * 0.5), int(th * 3.2)
    for row, y in enumerate(range(0, side, th + gap_y)):
        shift = (row % 2) * (tw + gap_x) // 2
        for x in range(-shift, side, tw + gap_x):
            canvas.paste(stamp, (x, y))               # копії не перекриваються — paste без маски досить
    canvas = canvas.rotate(28, resample=Image.BILINEAR)
    layer = canvas.crop(((side - w) // 2, (side - h) // 2, (side - w) // 2 + w, (side - h) // 2 + h))

    # чітка плашка внизу по центру — видно навіть на мініатюрі, і кадрування на сайті (object-fit: cover,
    # яке зрізає краї) її не обрізає
    small = _font(max(12, int(min(w, h) / 22)))
    l2, t2, r2, b2 = probe.textbbox((0, 0), WATERMARK_TEXT, font=small)
    pad = max(6, size // 3)
    bw, bh = (r2 - l2) + pad * 2, (b2 - t2) + pad * 2
    x0, y0 = (w - bw) // 2, h - bh - int(h * 0.06)
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=pad, fill=(0, 0, 0, 150))
    d.text((x0 + pad - l2, y0 + pad - t2), WATERMARK_TEXT, font=small, fill=(255, 255, 255, 235))
    return layer


def watermark(src_path, fid, domain="", style="subtle"):
    """Фото з вшитим водяним знаком (WebP-байти) і позначкою в метаданих. style — див. WATERMARK_STYLES."""
    from PIL import Image, ImageOps

    with Image.open(src_path) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
    if style != "off":
        im = Image.alpha_composite(im, _layer(*im.size, style=style))
    out = im.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "WEBP", quality=80, method=2, exif=_exif(fid, domain))
    return buf.getvalue()


def cached_watermark(static_dir, cache_dir, src, fid, domain="", style="subtle"):
    """Шлях до готового фото з водяним знаком (кеш у instance/demo-cache, права 700/600). None — фото немає."""
    path = os.path.realpath(os.path.join(static_dir, src))
    media_root = os.path.realpath(os.path.join(static_dir, "media")) + os.sep
    if not path.startswith(media_root) or not os.path.isfile(path):
        return None                                   # лише фото з static/media, без «../»
    stat = os.stat(path)
    key = hashlib.sha256(json.dumps([src, stat.st_mtime_ns, stat.st_size, fid, domain, style, WATERMARK_VERSION])
                         .encode()).hexdigest()[:32]
    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    target = os.path.join(cache_dir, key + ".webp")
    if not os.path.exists(target):
        data = watermark(path, fid, domain, style)
        tmp = f"{target}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)                       # атомарно: паралельні воркери не побачать півфайлу
    return target


def warm(site, static_dir, cache_dir, fid):
    """Готує фото з водяним знаком заздалегідь (manage.py demo-link): клієнт не чекатиме на перше відкриття."""
    root = os.path.join(static_dir, site.media_root)
    done = 0
    for folder, _dirs, files in os.walk(root):
        if os.sep + "brand" in folder[len(root):] or os.sep + "examples" in folder[len(root):]:
            continue
        for name in files:
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")):
                src = os.path.relpath(os.path.join(folder, name), static_dir).replace(os.sep, "/")
                if cached_watermark(static_dir, cache_dir, src, fid, site.demo["domain"], site.demo["watermark"]):
                    done += 1
    return done
