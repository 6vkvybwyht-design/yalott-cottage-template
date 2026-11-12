"""Фото сайту — автоматично з папок static/media/…

    static/media/objects/<id>/   фото об'єкта (перше за назвою — обкладинка, або поле cover у конфігу)
    static/media/hero/           банер головної (береться перше фото)
    static/media/gallery/        галерея території на головній
    static/media/extras/         фото послуг: <id послуги>.webp
    static/media/brand/          логотип, favicon, og-зображення

Сюди фото потрапляють командою  python manage.py photos  з оригіналів у media/… (WebP 1600 px
+ мініатюра 600 px у підпапці thumb/). Можна класти й готові файли напряму.
Якщо фото немає — сайт показує заглушку в кольорах теми, а не зламаний блок.

Усі функції приймають папку ВІДНОСНО static/: «media/objects/big». Для config/site.yaml корінь —
static/media/; для будь-якого іншого конфігу (приклади) — static/media/examples/<назва конфігу>/,
щоб фото різних сайтів не змішувались (див. SiteConfig.media).

Необов'язково: файл captions.txt у папці з підписами, рядок «імʼя_файлу = Підпис».
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")


def _captions(path):
    out = {}
    file = os.path.join(path, "captions.txt")
    if os.path.exists(file):
        with open(file, encoding="utf-8-sig") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    name, text = line.split("=", 1)
                    out[name.strip()] = text.strip()
    return out


def list_photos(folder, static_dir=None):
    """Імена файлів фото в static/<folder>, за алфавітом. Порожньо, якщо папки чи фото немає."""
    path = os.path.join(static_dir or STATIC_DIR, folder)
    try:
        return sorted(n for n in os.listdir(path)
                      if n.lower().endswith(EXTENSIONS) and not n.startswith(".")
                      and os.path.isfile(os.path.join(path, n)))
    except (FileNotFoundError, NotADirectoryError):
        return []


def photos(folder, name=""):
    """[{"src": "media/objects/big/01.webp", "thumb": "media/objects/big/thumb/01.webp", "caption": "..."}]
    — шляхи відносно static/."""
    captions = _captions(os.path.join(STATIC_DIR, folder))
    return [{"src": f"{folder}/{n}", "thumb": thumb_for(f"{folder}/{n}"),
             "caption": captions.get(n) or (f"{name} — фото {i}" if name else f"Фото {i}")}
            for i, n in enumerate(list_photos(folder), 1)]


def thumb_for(src):
    """media/objects/big/01.webp → media/objects/big/thumb/01.webp, якщо така мініатюра є; інакше None."""
    if not src:
        return None
    folder, name = os.path.split(src)
    thumb = f"{folder}/thumb/{name}"
    return thumb if os.path.exists(os.path.join(STATIC_DIR, thumb)) else None


def cover(obj):
    """Обкладинка об'єкта: файл із поля cover (з розширенням чи без), інакше перше фото; None — заглушка."""
    items = photos(obj["folder"], obj["name"])
    wanted = str(obj.get("cover") or "")
    for p in items:
        name = os.path.basename(p["src"])
        if wanted and wanted in (name, os.path.splitext(name)[0]):
            return p["src"]
    return items[0]["src"] if items else None


def find(folder, stem):
    """Файл <stem>.* у папці (напр. фото послуги за її id) або None."""
    stem = os.path.splitext(str(stem))[0]
    for n in list_photos(folder):
        if os.path.splitext(n)[0] == stem:
            return f"{folder}/{n}"
    return None


def first(folder):
    names = list_photos(folder)
    return f"{folder}/{names[0]}" if names else None


def exists(src):
    """Чи є файл static/<src> (для логотипа й favicon із конфігу)."""
    return bool(src) and os.path.isfile(os.path.join(STATIC_DIR, src))
