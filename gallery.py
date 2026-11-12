"""Фото об'єктів — автоматично з папок static/img/obj1, obj2, obj3.

Достатньо покласти файли в папку: сайт сам покаже їх у галереї (в алфавітному порядку імен),
а перше фото зробить обкладинкою об'єкта. Щоб змінити порядок — назвіть файли 01.webp, 02.webp …
Мініатюри (600 px) для галерей — у підпапці thumb/ з тими самими іменами; якщо мініатюри немає,
показується повне фото. Готує їх tools/process_photos.py.
Поки папка порожня, замість фото показуються заглушки в кольорах сайту.

Необов'язково: файл captions.txt у тій самій папці з підписами, рядок «імʼя_файлу = Підпис».
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "img")
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")
PLACEHOLDERS = 6  # скільки блоків-заглушок показувати, поки немає фото


def _captions(folder):
    path = os.path.join(IMG_DIR, folder, "captions.txt")
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                if "=" in line:
                    name, text = line.split("=", 1)
                    out[name.strip()] = text.strip()
    return out


def photos(obj):
    """[{"src": "img/obj1/01.webp", "thumb": "img/obj1/thumb/01.webp", "caption": "..."}] — шляхи відносно static/.
    Порожньо, якщо фото немає."""
    folder = obj["folder"]
    path = os.path.join(IMG_DIR, folder)
    try:
        names = sorted(n for n in os.listdir(path)
                       if n.lower().endswith(EXTENSIONS) and not n.startswith(".")
                       and os.path.isfile(os.path.join(path, n)))
    except FileNotFoundError:
        return []
    captions = _captions(folder)
    return [{"src": f"img/{folder}/{n}", "thumb": thumb_for(f"img/{folder}/{n}"),
             "caption": captions.get(n, f"{obj['name']} — фото {i}")}
            for i, n in enumerate(names, 1)]


def thumb_for(src):
    """img/obj1/01.webp → img/obj1/thumb/01.webp, якщо така мініатюра є; інакше None."""
    if not src:
        return None
    folder, name = os.path.split(src)
    thumb = f"{folder}/thumb/{name}"
    return thumb if os.path.exists(os.path.join(BASE_DIR, "static", thumb)) else None


def cover(obj):
    """Обкладинка об'єкта: файл із obj["cover"] (якщо є в папці), інакше перше фото; None — заглушка."""
    items = photos(obj)
    wanted = f"img/{obj['folder']}/{obj['cover']}" if obj.get("cover") else None
    for p in items:
        if p["src"] == wanted:
            return p["src"]
    return items[0]["src"] if items else None
