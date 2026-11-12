"""Обробка фото: оригінали з media/… → готові для сайту в static/media/…

    media/objects/<id об'єкта>/   фото об'єкта (порядок — за іменами файлів: 01.jpg, 02.jpg…)
    media/hero/                   банер головної (береться перше фото)
    media/gallery/                галерея території
    media/extras/                 фото послуг: <id послуги>.jpg  (напр. chan.jpg)
    media/brand/                  логотип, favicon — копіюються без змін

Що робиться з кожним фото:
  • повертається за EXIF-орієнтацією (фото з телефона не лежать на боці);
  • прибираються метадані (EXIF, GPS-координати, модель телефона);
  • стискається у WebP: повне — до 1600 px по ширині й ~300 КБ (для десктопа),
    мініатюра — 600 px у підпапці thumb/ (для мобільного й галерей);
  • з --enhance — трохи піднімаються яскравість, контраст і насиченість.
Оригінали не змінюються. Повторний запуск обробляє лише нові й змінені файли (--force — усі).

Запуск:  python manage.py photos
"""

import os
import re
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp")
MAX_WIDTH = 1600
THUMB_WIDTH = 600
QUALITY = 78
MIN_QUALITY = 60
TARGET_BYTES = 300 * 1024


def _slug(stem, index):
    """Безпечне імʼя файлу для сайту: лише латиниця, цифри й дефіс; інакше — порядковий номер."""
    name = re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-")
    return name or f"{index:02d}"


def _fit(im, width):
    from PIL import Image
    if im.width <= width:
        return im
    return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)


def _enhance(im):
    from PIL import ImageEnhance
    lut = [round(255 * (i / 255) ** 0.92) for i in range(256)]   # світліші середні тони, білий лишається білим
    im = im.point(lut * 3)
    im = ImageEnhance.Contrast(im).enhance(1.08)
    return ImageEnhance.Color(im).enhance(1.10)


def _save_webp(im, path, limit=None):
    """Зберігає WebP БЕЗ метаданих. Якщо файл більший за limit — знижує якість, далі трохи зменшує розмір."""
    quality = QUALITY
    while True:
        im.save(path, "WEBP", quality=quality, method=6)   # exif/icc не передаються → метаданих немає
        if not limit or os.path.getsize(path) <= limit:
            return
        if quality > MIN_QUALITY:
            quality -= 6
        elif im.width > 900:
            im = _fit(im, im.width - 100)
        else:
            return


def process_file(src, dst, thumb, enhance=False):
    """Одне фото → dst (до 1600 px) і thumb (600 px). Повертає (ширина, висота) повного фото."""
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)          # орієнтація з EXIF застосовується до пікселів
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.split()[-1])
            im = flat
        else:
            im = im.convert("RGB")
        im = _fit(im, MAX_WIDTH)
        if enhance:
            im = _enhance(im)
        os.makedirs(os.path.dirname(thumb), exist_ok=True)
        _save_webp(_fit(im, THUMB_WIDTH), thumb)
        _save_webp(im, dst, TARGET_BYTES)
        return im.size


def _sources(folder):
    try:
        return sorted(n for n in os.listdir(folder)
                      if n.lower().endswith(SOURCE_EXT) and not n.startswith(".")
                      and os.path.isfile(os.path.join(folder, n)))
    except (FileNotFoundError, NotADirectoryError):
        return []


def folders(src_root):
    """Папки з оригіналами відносно кореня: objects/<id>, hero, gallery, extras."""
    out = []
    objects = os.path.join(src_root, "objects")
    if os.path.isdir(objects):
        out += [f"objects/{d}" for d in sorted(os.listdir(objects)) if os.path.isdir(os.path.join(objects, d))]
    return out + [d for d in ("hero", "gallery", "extras") if os.path.isdir(os.path.join(src_root, d))]


def run(media_root="media", force=False, enhance=False, log=print):
    """Обробляє всі фото. media_root — «media» або «media/examples/<назва>» (див. SiteConfig.media_root).

    Повертає {"done": N, "skipped": N, "failed": [(файл, помилка)]}.
    """
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise RuntimeError("Не встановлено Pillow. Виконайте: pip install -r requirements.txt")
    src_root = os.path.join(BASE_DIR, media_root)
    dst_root = os.path.join(BASE_DIR, "static", media_root)
    stats = {"done": 0, "skipped": 0, "failed": []}
    for folder in folders(src_root):
        names, seen = _sources(os.path.join(src_root, folder)), set()
        if not names:
            continue
        done = 0
        for i, name in enumerate(names, 1):
            stem = _slug(os.path.splitext(name)[0], i)
            while stem in seen:
                stem += "-2"
            seen.add(stem)
            src = os.path.join(src_root, folder, name)
            dst = os.path.join(dst_root, folder, stem + ".webp")
            thumb = os.path.join(dst_root, folder, "thumb", stem + ".webp")
            fresh = (os.path.exists(dst) and os.path.exists(thumb)
                     and os.path.getmtime(dst) >= os.path.getmtime(src))
            if fresh and not force:
                stats["skipped"] += 1
                continue
            try:
                process_file(src, dst, thumb, enhance)
                done += 1
            except Exception as exc:  # зіпсований файл не зупиняє решту
                stats["failed"].append((f"{media_root}/{folder}/{name}", str(exc)))
        stats["done"] += done
        log(f"  {folder}: оброблено {done}, усього фото {len(names)}")
    brand = os.path.join(src_root, "brand")
    if os.path.isdir(brand):
        os.makedirs(os.path.join(dst_root, "brand"), exist_ok=True)
        for name in sorted(os.listdir(brand)):
            if os.path.isfile(os.path.join(brand, name)) and not name.startswith("."):
                shutil.copy2(os.path.join(brand, name), os.path.join(dst_root, "brand", name))
        log("  brand: логотип і favicon скопійовано без змін")
    return stats


def pending(media_root="media"):
    """Оригінали, які ще не оброблені (або змінилися після обробки) — для manage.py check."""
    src_root = os.path.join(BASE_DIR, media_root)
    dst_root = os.path.join(BASE_DIR, "static", media_root)
    out = []
    for folder in folders(src_root):
        for i, name in enumerate(_sources(os.path.join(src_root, folder)), 1):
            dst = os.path.join(dst_root, folder, _slug(os.path.splitext(name)[0], i) + ".webp")
            src = os.path.join(src_root, folder, name)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                out.append(f"{media_root}/{folder}/{name}")
    return out
