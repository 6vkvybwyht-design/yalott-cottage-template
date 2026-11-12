"""Обробка фото й команди manage.py (validate, seed, check, new-client)."""

import os

import pytest

import gallery
import manage
import photos
import site_config
from conftest import CONFIGS

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


# ---------- фото ----------

def phone_photo(path, size=(3000, 2000), orientation=6):
    """«Фото з телефона»: лежить на боці (EXIF Orientation), з GPS і моделлю камери в метаданих."""
    im = Image.new("RGB", size, (120, 90, 60))
    for x in range(0, size[0], 40):                      # трохи деталей, щоб стиснення було чесним
        im.paste((200, 180, 140), (x, 0, x + 20, size[1]))
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x0110] = "iPhone 15"
    exif[0x8825] = {1: "N", 2: (48.0, 50.0, 13.9), 3: "E", 4: (23.0, 26.0, 44.1)}
    im.save(path, "JPEG", quality=95, exif=exif)


def test_photo_is_rotated_compressed_and_stripped(tmp_path):
    src, dst, thumb = tmp_path / "IMG_0001.jpg", tmp_path / "out" / "01.webp", tmp_path / "out" / "thumb" / "01.webp"
    os.makedirs(dst.parent)
    phone_photo(str(src))
    assert Image.open(src).getexif().get(0x0112) == 6
    photos.process_file(str(src), str(dst), str(thumb))
    with Image.open(dst) as full, Image.open(thumb) as small:
        assert full.format == "WEBP" and small.format == "WEBP"
        assert full.height > full.width                   # EXIF-поворот застосовано: фото стало вертикальним
        assert full.width <= photos.MAX_WIDTH and small.width == photos.THUMB_WIDTH
        assert len(full.getexif()) == 0 and len(small.getexif()) == 0     # метаданих (GPS, модель) немає
        assert "exif" not in full.info and "xmp" not in full.info
    assert os.path.getsize(dst) < os.path.getsize(src)
    assert os.path.getsize(dst) <= photos.TARGET_BYTES


def test_small_photo_is_not_upscaled(tmp_path):
    src = tmp_path / "small.png"
    Image.new("RGBA", (400, 300), (10, 20, 30, 128)).save(src)
    photos.process_file(str(src), str(tmp_path / "s.webp"), str(tmp_path / "thumb" / "s.webp"))
    assert Image.open(tmp_path / "s.webp").size == (400, 300)
    assert Image.open(tmp_path / "thumb" / "s.webp").size == (400, 300)


def test_photos_run_builds_site_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "BASE_DIR", str(tmp_path))
    for folder, names in (("objects/big", ["02 Вітальня.jpg", "01.jpg"]), ("hero", ["hero.jpg"]),
                          ("gallery", ["a.jpg"]), ("extras", ["chan.jpg"])):
        os.makedirs(tmp_path / "media" / folder)
        for n in names:
            phone_photo(str(tmp_path / "media" / folder / n), size=(900, 600), orientation=1)
    (tmp_path / "media" / "objects" / "big" / "notes.txt").write_text("не фото")
    (tmp_path / "media" / "gallery" / "broken.jpg").write_text("це не картинка")
    os.makedirs(tmp_path / "media" / "brand")
    Image.new("RGBA", (64, 64)).save(tmp_path / "media" / "brand" / "logo.png")

    assert len(photos.pending("media")) == 6
    stats = photos.run("media", log=lambda *_: None)
    assert stats["done"] == 5 and len(stats["failed"]) == 1 and "broken.jpg" in stats["failed"][0][0]
    static = tmp_path / "static"
    assert gallery.list_photos("media/objects/big", str(static)) == ["01.webp", "02.webp"]   # порядок за іменами
    assert gallery.list_photos("media/extras", str(static)) == ["chan.webp"]
    assert (static / "media" / "objects" / "big" / "thumb" / "01.webp").exists()
    assert (static / "media" / "brand" / "logo.png").exists()                                 # логотип — без змін
    assert photos.pending("media") == ["media/gallery/broken.jpg"]
    # повторний запуск нічого не переробляє; --force — переробляє все
    assert photos.run("media", log=lambda *_: None)["done"] == 0
    assert photos.run("media", force=True, log=lambda *_: None)["done"] == 5


def test_gallery_cover_and_captions(tmp_path, monkeypatch):
    folder = tmp_path / "media" / "objects" / "x"
    os.makedirs(folder / "thumb")
    for n in ("02.webp", "01.webp", "03.jpg", "thumb/01.webp"):
        (folder / n).write_bytes(b"x")
    (folder / "captions.txt").write_text("# підписи\n01.webp = Фасад\n", encoding="utf-8")
    monkeypatch.setattr(gallery, "STATIC_DIR", str(tmp_path))
    items = gallery.photos("media/objects/x", "Котедж")
    assert [p["src"] for p in items] == [f"media/objects/x/{n}" for n in ("01.webp", "02.webp", "03.jpg")]
    assert items[0]["caption"] == "Фасад" and items[1]["caption"] == "Котедж — фото 2"
    assert items[0]["thumb"] == "media/objects/x/thumb/01.webp" and items[1]["thumb"] is None
    obj = {"folder": "media/objects/x", "name": "Котедж"}
    assert gallery.cover(obj) == "media/objects/x/01.webp"
    assert gallery.cover(dict(obj, cover="03")) == "media/objects/x/03.jpg"
    assert gallery.cover(dict(obj, cover="02.webp")) == "media/objects/x/02.webp"
    assert gallery.cover({"folder": "media/objects/none", "name": "Немає"}) is None
    assert gallery.find("media/objects/x", "02") == "media/objects/x/02.webp"
    assert gallery.first("media/hero") is None


def test_demo_photos_are_optimized():
    """Демо-фото шаблону: WebP, до 1600 px і ~270 КБ, у кожного є мініатюра."""
    cfg = site_config.load(CONFIGS["site"])
    folders = [o["folder"] for o in cfg.objects] + [cfg.media("gallery"), cfg.media("hero")]
    for folder in folders:
        items = gallery.photos(folder)
        assert items, folder
        for p in items:
            full = os.path.join(gallery.STATIC_DIR, p["src"])
            assert p["src"].endswith(".webp") and p["thumb"], p["src"]
            assert os.path.getsize(full) <= 270 * 1024, p["src"]
            with Image.open(full) as im:
                assert im.width <= 1600
            with Image.open(os.path.join(gallery.STATIC_DIR, p["thumb"])) as im:
                assert im.width <= 600


# ---------- manage.py ----------

def run(*argv):
    return manage.main(list(argv))


def test_validate_command(capsys, tmp_path):
    assert run("validate", "--config", CONFIGS["blackhouse"]) == 0
    out = capsys.readouterr().out
    assert "Конфіг правильний: «Black House», тема dark, об'єктів — 2, послуг — 1, сезонів — 1" in out
    assert "немає фото. Покладіть їх у media/examples/blackhouse/objects/001/" in out

    bad = tmp_path / "bad.yaml"
    text = open(CONFIGS["blackhouse"], encoding="utf-8").read()
    bad.write_text(text.replace("start: 2026-12-28", "start: 2026-02-30").replace("theme: dark", "theme: night"),
                   encoding="utf-8")
    assert run("validate", "--config", str(bad)) == 1
    out = capsys.readouterr().out
    assert "✗ brand → theme: немає теми «night»" in out
    assert "✗ seasons №1 «Новорічні свята» → start: неправильна дата «2026-02-30»" in out
    assert "Помилок: 2" in out


def test_seed_command_is_idempotent(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "seed.db"))
    assert run("seed", "--config", CONFIGS["ramshill"]) == 0
    first = capsys.readouterr().out
    assert "+ об'єкт «Великий котедж» — 8 500 грн / ніч" in first and "+ послуга «Чан» — 2 500 грн" in first
    assert run("seed", "--config", CONFIGS["ramshill"]) == 0
    second = capsys.readouterr().out
    assert "Додано з конфігу" not in second and "Повторний запуск безпечний" in second
    assert run("seed", "--config", CONFIGS["ramshill"], "--reset", "--yes") == 0
    assert "~ об'єкт «Великий котедж» — ціни й параметри з конфігу" in capsys.readouterr().out
    assert run("seed", "--config", CONFIGS["ramshill"], "--demo") == 0
    assert "Демо-зайнятість і демо-заявки додано" in capsys.readouterr().out
    assert run("seed", "--config", CONFIGS["ramshill"], "--clear-demo") == 0
    assert "демо-заявок — 2" in capsys.readouterr().out


def test_seed_stops_on_broken_config(capsys, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("brand: {name: X, theme: wood}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run("seed", "--config", str(bad))
    assert exc.value.code == 1 and "містить помилки" in capsys.readouterr().out


def test_check_command(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "check.db"))
    assert run("check", "--config", CONFIGS["ramshill"]) == 1          # приклад без фото й без секретів
    out = capsys.readouterr().out
    for part in ("ADMIN_PASSWORD не задано", "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не задано",
                 "«Великий котедж»: немає фото", "лишились заглушки", "НЕ ГОТОВО"):
        assert part in out, part
    assert "SECRET_KEY задано" in out

    # готовий сайт: справжні контакти, секрети, фото
    text = open(CONFIGS["site"], encoding="utf-8").read().replace("+380 67 000 00 00", "+380 67 123 45 67") \
        .replace("+380670000000", "+380671234567")
    config = tmp_path / "site.yaml"
    config.write_text(text, encoding="utf-8")
    for key, value in (("ADMIN_PASSWORD", "strong-pass-2026"), ("TELEGRAM_BOT_TOKEN", "1:abc"),
                       ("TELEGRAM_CHAT_ID", "42"), ("SESSION_COOKIE_SECURE", "1")):
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(manage.os.path, "exists", lambda p, _real=os.path.exists: True if p.endswith(".env") else _real(p))
    assert run("check", "--config", str(config)) == 0
    out = capsys.readouterr().out
    assert "ГОТОВО до деплою" in out and "«Будинок А-фрейм»: фото — 25" in out


def answers(script):
    """Відповіді майстра за шматком питання; усе інше — Enter (значення за замовчуванням)."""
    asked = []

    def fake_input(prompt):
        asked.append(prompt)
        for key, value in script:
            if key in prompt:
                if isinstance(value, list):
                    return value.pop(0) if value else ""
                return value
        return ""
    return fake_input, asked


def test_new_client_wizard(tmp_path, monkeypatch, capsys):
    out = tmp_path / "config" / "newhouse.yaml"
    fake, asked = answers([
        ("Назва (напр. Ramshill)", "Тиха Хата"), ("Тип закладу", "Котеджі"), ("Тема:", "1"),
        ("Телефон (напр.", ["12", "+380 67 123 45 67"]),                    # перша відповідь — з помилкою
        ("Адреса", "смт Славське, вул. Лісова, 5"), ("Координати", "48.8372, 23.4456"),
        ("Передоплата", "50"), ("За скільки днів", "10"),
        ("Назва (напр. Великий котедж)", ["Великий котедж", "Маленький котедж"]),
        ("Скільки ОДНАКОВИХ", ["2", "4"]), ("Базова ціна за ніч", ["8500", "6000"]),
        ("Максимум гостей", ["6", "3"]), ("входить у базову ціну", ["4", "2"]),
        ("Додати ще один об'єкт", ["так", "ні"]),
        ("Додати послугу?", "так"), ("Назва (напр. Чан)", "Чан"), ("Ціна, грн", "2500"),
        ("залежить від кількості гостей", "так"), ("До скількох гостей", ["2", "4"]),
        ("Ціна до 2 гостей", "2500"), ("Ціна до 4 гостей", "3000"), ("Ще один поріг", ["так", "ні"]),
        ("Додати ще одну послугу", "ні"),
        ("Додати сезон", "так"), ("Перша ніч", "2026-12-28"), ("Остання ніч", "2027-01-08"),
        ("«Великий котедж», грн", "12000"), ("«Маленький котедж», грн", "8000"),
    ])
    monkeypatch.setattr("builtins.input", fake)
    monkeypatch.setattr(manage, "BASE_DIR", str(tmp_path))
    assert run("new-client", "--output", str(out)) == 0
    text = capsys.readouterr().out
    assert "Не схоже на номер" in text and "Конфіг збережено" in text and "python manage.py photos" in text

    cfg = site_config.load(str(out))                              # згенерований файл одразу правильний
    assert cfg.brand["full_name"] == "Котеджі Тиха Хата" and cfg.brand["theme"] == "dark"
    assert cfg.contacts["coordinates"] == [48.8372, 23.4456] and cfg.contacts["viber"] == "+380671234567"
    big, small = cfg.objects
    assert (big["key"], big["units"], big["price"], big["base_guests"], big["max_guests"]) == ("velykyi-kotedzh", 2, 8500, 4, 6)
    assert (small["key"], small["units"], small["price"], small["extra_guest_price"]) == ("malenkyi-kotedzh", 4, 6000, 500)
    assert cfg.extras[0]["guest_prices"] == [{"upTo": 2, "price": 2500}, {"upTo": 4, "price": 3000}]
    assert cfg.rules["prepayment_percent"] == 50 and cfg.rules["cancellation_days"] == 10
    assert {(s["object"], s["price"]) for s in cfg.seasons} == {("velykyi-kotedzh", 12000), ("malenkyi-kotedzh", 8000)}
    source = out.read_text(encoding="utf-8")
    assert "# [БАЗА]" in source and "password" not in source.lower() and "token" not in source.lower()
    assert (tmp_path / "media" / "examples" / "newhouse" / "objects" / "velykyi-kotedzh").is_dir()


def test_slugify():
    assert manage.slugify("Великий котедж") == "velykyi-kotedzh"
    assert manage.slugify("Будинок А-фрейм №2") == "budynok-a-freim-2"
    assert manage.slugify("Black House") == "black-house"
