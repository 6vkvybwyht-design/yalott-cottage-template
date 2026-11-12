"""Конфіг клієнта: приклади правильні, а помилки пояснюються зрозуміло й українською."""

import copy

import pytest

import site_config
from conftest import CONFIGS, ROOT


def raw(name="ramshill"):
    return copy.deepcopy(site_config.read_yaml(CONFIGS[name]))


def errors_of(data):
    return "\n".join(site_config.validate(data, check_photos=False)[0])


@pytest.mark.parametrize("name", ["site", "ramshill", "blackhouse"])
def test_shipped_configs_are_valid(name):
    errors, _ = site_config.validate(raw(name), check_photos=False)
    assert errors == []
    assert site_config.load(CONFIGS[name]).objects


def test_ramshill_values():
    cfg = site_config.load(CONFIGS["ramshill"])
    big, small = cfg.objects
    assert cfg.brand["theme"] == "wood" and "Славське" in cfg.contacts["address"]
    assert (big["units"], big["price"], big["base_guests"], big["max_guests"], big["extra_guest_price"]) == (2, 8500, 4, 6, 500)
    assert (big["bedrooms"], big["bathrooms"]) == (2, 2)
    assert "Камін" in big["amenities"] and "Тераса з чаном" in big["amenities"]
    assert (small["units"], small["price"], small["base_guests"], small["max_guests"], small["extra_guest_price"]) == (4, 6000, 2, 3, 500)
    chan = cfg.extra_by_key["chan"]
    assert (chan["price"], chan["unit"], chan["unit_label"]) == (2500, "evening", "за вечір")


def test_blackhouse_values():
    cfg = site_config.load(CONFIGS["blackhouse"])
    one, two = cfg.objects
    assert cfg.brand["theme"] == "dark"
    assert (one["key"], one["price"], one["base_guests"], one["max_guests"], one["extra_guest_price"]) == ("001", 4500, 2, 4, 500)
    assert (one["check_in"], one["check_out"]) == ("15:00", "12:00")
    assert (two["key"], two["price"], two["base_guests"], two["max_guests"], two["extra_guest_price"]) == ("002", 4000, 2, 4, 500)
    assert (two["check_in"], two["check_out"]) == ("14:00", "11:00")
    assert cfg.extra_by_key["jacuzzi"]["guest_prices"] == [{"upTo": 2, "price": 2500}, {"upTo": 4, "price": 3000}]
    assert cfg.rules["prepayment_percent"] == 50 and cfg.rules["cancellation_days"] == 10


def test_yaml_keeps_times_ids_and_dates_as_written(tmp_path):
    """У звичайному YAML 15:00 стає числом 900, а 001 — одиницею. Тут — ні."""
    path = tmp_path / "x.yaml"
    path.write_text("time: 15:00\nid: 001\nday: 2026-12-30\nbad_day: 2026-13-45\nprice: 20000\nphone: +380671234567\nflag: true\n",
                    encoding="utf-8")
    assert site_config.read_yaml(str(path)) == {
        "time": "15:00", "id": "001", "day": "2026-12-30", "bad_day": "2026-13-45", "price": 20000,
        "phone": "+380671234567", "flag": True}


def test_missing_fields_are_named():
    data = raw()
    del data["brand"]["name"]
    del data["objects"][1]["price"]
    del data["contacts"]["phone"]
    del data["rules"]["prepayment_percent"]
    text = errors_of(data)
    assert "brand → name: обов'язкове поле" in text
    assert "objects №2 «Маленький котедж» → price: обов'язкове поле, а його немає" in text
    assert "contacts → phone" in text and "rules → prepayment_percent" in text


def test_missing_section():
    data = raw()
    del data["objects"]
    assert "objects: немає цього розділу — він обов'язковий" in errors_of(data)


def test_wrong_date():
    data = raw()
    data["seasons"][0]["start"] = "2026-13-45"
    data["seasons"].append({"name": "Літо", "start": "01.07.2027", "end": "2027-08-31", "price": 9000})
    text = errors_of(data)
    assert "seasons №1 «Новорічні свята» → start: неправильна дата «2026-13-45». Формат: РРРР-ММ-ДД" in text
    assert "seasons №2 «Літо» → start: неправильна дата «01.07.2027»" in text


def test_season_end_before_start():
    data = raw()
    data["seasons"] = [{"name": "Свята", "start": "2027-01-08", "end": "2026-12-28", "price": 9000}]
    assert "кінець сезону (2027-01-08" not in errors_of(data)
    assert "кінець сезону (2026-12-28) раніше за початок (2027-01-08)" in errors_of(data)


def test_overlapping_seasons():
    data = raw()
    data["seasons"] = [
        {"name": "Новий рік", "start": "2026-12-28", "end": "2027-01-08", "prices": {"big": 12000, "small": 8000}},
        {"name": "Різдво", "start": "2027-01-06", "end": "2027-01-10", "prices": {"big": 11000}},
    ]
    text = errors_of(data)
    assert "сезони перетинаються для об'єкта «big»" in text and "«Новий рік»" in text
    assert "«small»" not in text                       # у маленького котеджу перетину немає
    # сезони, що йдуть один за одним, — не помилка
    data["seasons"][1]["start"] = "2027-01-09"
    assert errors_of(data) == ""
    # спільний сезон і сезон об'єкта можуть накладатись: діє сезон об'єкта
    data["seasons"] = [{"name": "Усім", "start": "2026-12-28", "end": "2027-01-08", "price": 9000},
                       {"name": "Великому", "start": "2026-12-30", "end": "2027-01-02", "prices": {"big": 15000}}]
    assert errors_of(data) == ""
    data["seasons"].append({"name": "Ще всім", "start": "2027-01-08", "end": "2027-01-12", "on_request": True})
    assert "сезони перетинаються для всіх об'єктів" in errors_of(data)


def test_season_price_rules():
    data = raw()
    data["seasons"] = [{"name": "A", "start": "2027-01-01", "end": "2027-01-02", "prices": {"villa": 9000}},
                       {"name": "B", "start": "2027-02-01", "end": "2027-02-02"},
                       {"name": "C", "start": "2027-03-01", "end": "2027-03-02", "price": 9000, "on_request": True}]
    text = errors_of(data)
    assert "немає об'єкта з id «villa». Є: big, small" in text
    assert text.count("вкажіть рівно одне з трьох") == 2


def test_object_rules():
    data = raw()
    data["objects"][0].update(base_guests=8, price="8 500", units=0, check_in="15.00", icon="spaceship")
    data["objects"][1]["id"] = "big"
    text = errors_of(data)
    assert "гостей у базовій ціні (base_guests = 8) більше, ніж максимум (max_guests = 6)" in text
    assert "price: має бути ціле число без лапок і пробілів, а вказано «8 500»" in text
    assert "units: не може бути менше 1" in text
    assert 'check_in: час має бути у форматі ГГ:ХХ, напр. "15:00"' in text
    assert "немає іконки «spaceship»" in text
    assert "id «big» уже використано в іншого об'єкта" in text


def test_object_id_rules():
    data = raw()
    for bad, message in ((1, "візьміть його в лапки"), ("Великий котедж", "лише малі латинські літери"),
                         ("admin", "зайнято самим сайтом")):
        data["objects"][0]["id"] = bad
        assert message in errors_of(data), bad


def test_theme_colors_contacts():
    data = raw()
    data["brand"].update(theme="blue", primary_color="коричневий")
    data["contacts"].update(phone="12345", instagram="https://instagram.com/ramshill", coordinates=[48.8], email="пошта")
    text = errors_of(data)
    assert "немає теми «blue». Доступні: dark, wood, forest" in text
    assert 'brand → primary_color: колір має бути у форматі "#a06a3c"' in text
    assert "не схоже на номер телефону" in text and "лише нік без @" in text
    assert "потрібні два числа [широта, довгота]" in text and "не схоже на електронну адресу" in text


def test_extras_rules():
    data = raw("blackhouse")
    data["extras"][0].update(unit="hour", guest_prices=[{"up_to": 4, "price": 3000}, {"up_to": 2, "price": 2500}])
    text = errors_of(data)
    assert "невідома одиниця «hour»" in text and "evening (за вечір)" in text
    assert "пороги up_to мають зростати" in text


def test_secrets_are_rejected():
    """Паролі й токени — тільки в .env."""
    data = raw()
    data["telegram_bot_token"] = "123:ABC"
    data["contacts"]["admin_password"] = "qwerty"
    text = errors_of(data)
    assert text.count("Секрети зберігаються ТІЛЬКИ у файлі .env") == 2


def test_no_secrets_in_shipped_files():
    for path in list(CONFIGS.values()) + [f"{ROOT}/.env.example"]:
        text = open(path, encoding="utf-8").read()
        for line in text.splitlines():
            if line.startswith(("SECRET_KEY=", "ADMIN_PASSWORD=", "TELEGRAM_BOT_TOKEN=", "TELEGRAM_CHAT_ID=")):
                assert line.endswith("="), line


def test_missing_photos_is_a_warning(tmp_path):
    data = raw()
    errors, warnings = site_config.validate(data, static_dir=str(tmp_path), media="media/examples/ramshill")
    assert errors == []
    assert sum("немає фото. Покладіть їх у media/examples/ramshill/objects/" in w for w in warnings) == 2
    folder = tmp_path / "media" / "examples" / "ramshill" / "objects" / "big"
    folder.mkdir(parents=True)
    (folder / "01.webp").write_bytes(b"x")
    _, warnings = site_config.validate(data, static_dir=str(tmp_path), media="media/examples/ramshill")
    assert sum("немає фото" in w for w in warnings) == 1


def test_broken_yaml_and_missing_file(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("brand:\n  name: Тест\n   theme: wood\n", encoding="utf-8")
    with pytest.raises(site_config.ConfigError) as exc:
        site_config.load(str(path))
    assert "Синтаксис YAML — рядок 3" in exc.value.errors[0]
    with pytest.raises(site_config.ConfigError) as exc:
        site_config.load(str(tmp_path / "none.yaml"))
    assert "python manage.py new-client" in exc.value.errors[0]


def test_load_raises_with_all_errors(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text("brand: {name: Тест}\n", encoding="utf-8")
    with pytest.raises(site_config.ConfigError) as exc:
        site_config.load(str(path))
    assert len(exc.value.errors) >= 4 and "brand → theme" in str(exc.value)


def test_media_root_per_config():
    assert site_config.load(CONFIGS["site"]).media_root == "media"
    assert site_config.load(CONFIGS["ramshill"]).objects[0]["folder"] == "media/examples/ramshill/objects/big"


def test_booking_prefix_from_name():
    assert [site_config._prefix(n) for n in ("Ramshill", "Black House", "Садиба")] == ["RA", "BH", "BK"]
