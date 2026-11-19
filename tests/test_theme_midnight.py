"""Тема midnight і необов'язковий девіз brand.slogan: вмикаються лише конфігом, інші сайти не змінюються."""

import os

import yaml

import site_config
from conftest import CONFIGS


def midnight_config(folder, **brand):
    with open(CONFIGS["ramshill"], encoding="utf-8") as f:
        raw = yaml.load(f, Loader=site_config._Loader)
    raw["brand"].update({"theme": "midnight", "slogan": "Гори кличуть тих, чия душа їм за зростом"}, **brand)
    path = os.path.join(folder, "midnight.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True)
    return path


def test_midnight_theme_loads_its_fonts_and_slogan(make_site, tmp_path, ramshill):
    html = make_site(midnight_config(str(tmp_path))).html("/")
    assert 'data-theme="midnight"' in html
    assert "fonts.googleapis.com/css2?family=Prata&amp;family=Tenor+Sans" in html
    assert '<p class="hero-slogan">Гори кличуть тих, чия душа їм за зростом</p>' in html
    plain = ramshill.html("/")                       # інші теми — без нових шрифтів і без девізу
    assert "Prata" not in plain and "hero-slogan" not in plain


def test_midnight_favicon_and_validation(make_site, tmp_path):
    raw = yaml.safe_load(open(midnight_config(str(tmp_path), slogan="x" * 121), encoding="utf-8"))
    errors, _ = site_config.validate(raw, check_photos=False)
    assert any("brand → slogan" in e for e in errors)
    s = make_site(midnight_config(str(tmp_path)))
    assert "#0d1a2e" in s.client.get("/favicon.svg").get_data(as_text=True)
