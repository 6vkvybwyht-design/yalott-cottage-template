"""Одноразова обробка фото садиби: photos/original/<папка> → static/img/<папка>.

Що робить з кожним фото:
  • повертає за EXIF-орієнтацією й прибирає метадані (зокрема GPS);
  • трохи піднімає яскравість (м'яка крива середніх тонів — світлі ділянки не пересвічуються),
    контраст і насиченість (+10–15 %);
  • зберігає у WebP якість 75 (фото з дрібною деталлю — листя — до 60, щоб вкластися в ~250 КБ): повне фото до 1600 px по ширині — static/img/<папка>/NN.webp,
    мініатюра для галереї 600 px — static/img/<папка>/thumb/NN.webp (менші фото не збільшує).
Оригінали не змінюються й не видаляються. Вони НЕ зберігаються в git (photos/original у .gitignore):
тримайте їх у себе, на сервер ідуть лише оптимізовані фото зі static/img.

Запуск з папки проєкту (потрібен Pillow: pip install pillow):   python tools/process_photos.py
Повторний запуск перезаписує static/img/<папка>/NN.webp і thumb/.

Нові фото пізніше можна просто класти в static/img/<папка> — сайт підхопить їх і без цього скрипта.
"""

import glob
import os
import re
import sys

from PIL import Image, ImageEnhance, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "photos", "original")
DST = os.path.join(ROOT, "static", "img")

MAX_WIDTH = 1600
THUMB_WIDTH = 600
QUALITY = 75
BRIGHTNESS_GAMMA = 0.90   # <1 — світліші середні тони; білий лишається білим
CONTRAST = 1.10
SATURATION = 1.13

# Порядок фото (номер у назві оригіналу) і підписи. Перше фото об'єкта — обкладинка.
# Фото, яких тут немає, додаються в кінець за номером.
ORDER = {
    "obj1": [(1, "Апартаменти Green увечері"), (3, "Спальня"), (4, "Кухня-вітальня"), (10, "Вітальня"),
             (9, "Спальня"), (2, "Тераса"), (7, "Тераса"), (8, "Затишні деталі"), (5, "Вхід"), (6, "Санвузол")],
    "obj2": [(19, "Двоповерховий котедж"), (17, "Вітальня з каміном"), (26, "Камін"), (23, "Їдальня"),
             (24, "Кухня й сходи"), (16, "Кухня"), (13, "Спальня"), (25, "Спальня"), (20, "Спальня"),
             (29, "Санвузол"), (14, "Вхід"), (11, "Літня кухня"), (22, "Літня кухня"), (12, "Альтанка"),
             (15, "Двір"), (18, "Ставок"), (21, "Тераса"), (28, "Альтанка біля ставка")],
    "obj3": [(30, "Будинок А-фрейм"), (33, "Вітальня з панорамним вікном"), (53, "Вид на гори"),
             (36, "Панорамне вікно"), (31, "Камін і сходи на антресоль"), (46, "Вітальня"), (45, "Вид з антресолі"),
             (35, "Антресоль"), (43, "Спальня під дахом"), (41, "Обідня зона"), (42, "Кухня"), (27, "Кухня"),
             (50, "Кухня"), (37, "Кавова зона"), (32, "Мийка з видом"), (34, "Санвузол"), (48, "Санвузол"),
             (44, "Душ"), (39, "Вхід"), (47, "Тераса"), (40, "Альтанка"), (52, "А-фрейм узимку"),
             (51, "Зимовий вечір"), (49, "Святковий настрій"), (38, "Усе необхідне на кухні")],
    "territory": [(54, "Чан"), (59, "Чан з цитрусами"), (64, "Чан з квітами"), (56, "Баня"), (57, "Баня"),
                  (60, "Басейн"), (58, "Басейн і баня"), (63, "Альтанка ввечері"), (66, "Альтанка"),
                  (62, "Зона відпочинку"), (55, "Територія"), (61, "Стежка")],
    "food": [(70, "Сніданок"), (71, "Сніданок"), (69, "Шакшука"), (68, "Каша з ягодами"),
             (72, "Запечене м'ясо"), (73, "Десерт"), (65, "Меню сніданків"), (67, "Меню сніданків і десертів")],
}
NO_ENHANCE = {("food", 65), ("food", 67)}  # афіші з текстом — лише зменшуємо


def num(path):
    m = re.search(r"photo_(\d+)", os.path.basename(path))
    return int(m.group(1)) if m else 10 ** 6


def enhance(im):
    lut = [round(255 * (i / 255) ** BRIGHTNESS_GAMMA) for i in range(256)]
    im = im.point(lut * 3)
    im = ImageEnhance.Contrast(im).enhance(CONTRAST)
    return ImageEnhance.Color(im).enhance(SATURATION)


def fit(im, width):
    if im.width <= width:
        return im
    return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)


TARGET_BYTES = 250 * 1024   # мета для повного фото
MIN_QUALITY = 60


def save_webp(im, path, limit=None):
    """WebP якість 75; якщо більше за limit — знижуємо якість до 60, далі трохи зменшуємо розмір.
    Повертає (якість, ширина), з якими збережено. Метадані (EXIF/GPS) не записуються."""
    quality = QUALITY
    while True:
        im.save(path, "WEBP", quality=quality, method=6)
        if not limit or os.path.getsize(path) <= limit:
            return quality, im.width
        if quality > MIN_QUALITY:
            quality -= 5
        elif im.width > 800:
            im = fit(im, im.width - 100)
        else:
            return quality, im.width


def process(src, dst, thumb, do_enhance=True):
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im = fit(im, MAX_WIDTH)
        if do_enhance:
            im = enhance(im)
        save_webp(fit(im, THUMB_WIDTH), thumb)
        return save_webp(im, dst, TARGET_BYTES)


def process_folder(folder):
    files = {num(f): f for f in glob.glob(os.path.join(SRC, folder, "*.jp*g"))}
    order = ORDER.get(folder, [])
    known = [n for n, _ in order if n in files]
    rest = sorted(n for n in files if n not in known)
    captions = dict(order)
    out_dir = os.path.join(DST, folder)
    thumb_dir = os.path.join(out_dir, "thumb")
    os.makedirs(thumb_dir, exist_ok=True)
    for pattern in ("[0-9][0-9].jpg", "[0-9][0-9].webp", "thumb/[0-9][0-9].webp"):
        for old in glob.glob(os.path.join(out_dir, pattern)):
            os.remove(old)
    lines = []
    for i, n in enumerate(known + rest, 1):
        name = f"{i:02d}.webp"
        quality, width = process(files[n], os.path.join(out_dir, name), os.path.join(thumb_dir, name),
                                 (folder, n) not in NO_ENHANCE)
        if quality != QUALITY:
            print(f"  {folder}/{name}: якість {quality}, ширина {width}px — щоб вкластися в ~250 КБ")
        if n in captions:
            lines.append(f"{name} = {captions[n]}")
    with open(os.path.join(out_dir, "captions.txt"), "w", encoding="utf-8") as f:
        f.write("# Підписи до фото: імʼя_файлу = Підпис\n" + "\n".join(lines) + "\n")
    print(f"{folder}: {len(known) + len(rest)} фото")


def process_logo():
    """Логотип на білому тлі → прозорий PNG (темний і світлий для темного тла) + favicon."""
    src = os.path.join(SRC, "logo", "logo.jpg")
    if not os.path.exists(src):
        return
    with Image.open(src) as im:
        gray = ImageOps.exif_transpose(im).convert("L")
    alpha = ImageOps.invert(gray).point(lambda v: 0 if v < 18 else min(255, round((v - 18) * 1.25)))
    box = alpha.getbbox()
    alpha = alpha.crop(box)
    pad = 12
    canvas = Image.new("L", (alpha.width + pad * 2, alpha.height + pad * 2), 0)
    canvas.paste(alpha, (pad, pad))
    for name, color in (("logo.png", (28, 31, 28)), ("logo-light.png", (247, 245, 240))):
        out = Image.new("RGBA", canvas.size, color + (0,))
        out.putalpha(canvas)
        w = 600
        out.resize((w, round(out.height * w / out.width)), Image.LANCZOS).save(os.path.join(DST, name), optimize=True)
    # favicon: лише дерево (верхня частина логотипа, без напису)
    rows = [canvas.crop((0, y, canvas.width, y + 1)).getbbox() is not None for y in range(canvas.height)]
    gap = next((y for y in range(int(canvas.height * 0.4), canvas.height) if not rows[y]), canvas.height)
    tree = canvas.crop((0, 0, canvas.width, gap))
    tree = tree.crop(tree.getbbox())
    side = max(tree.size) + 16
    sq = Image.new("L", (side, side), 0)
    sq.paste(tree, ((side - tree.width) // 2, (side - tree.height) // 2))
    fav = Image.new("RGBA", (side, side), (28, 31, 28, 0))
    fav.putalpha(sq)
    bg = Image.new("RGBA", (side, side), (247, 245, 240, 255))
    bg.alpha_composite(fav)
    bg.resize((128, 128), Image.LANCZOS).save(os.path.join(ROOT, "static", "favicon.png"), optimize=True)
    print("logo.png, logo-light.png, favicon.png")


if __name__ == "__main__":
    folders = sys.argv[1:] or sorted(d for d in os.listdir(SRC) if d != "logo" and os.path.isdir(os.path.join(SRC, d)))
    for folder in folders:
        process_folder(folder)
    process_logo()
