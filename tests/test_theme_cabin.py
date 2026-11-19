"""Тема cabin і необов'язкова точка фокусу банера brand.hero_focus: вмикаються лише конфігом."""

import os

import yaml

import site_config
from conftest import CONFIGS


def cabin_config(folder, **brand):
    with open(CONFIGS["ramshill"], encoding="utf-8") as f:
        raw = yaml.load(f, Loader=site_config._Loader)
    raw["brand"].update({"theme": "cabin", "slogan": "Чан під зорями"}, **brand)
    path = os.path.join(folder, "cabin.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True)
    return path


def test_cabin_theme_loads_its_fonts(make_site, tmp_path, ramshill):
    html = make_site(cabin_config(str(tmp_path))).html("/")
    assert 'data-theme="cabin"' in html
    assert "fonts.googleapis.com/css2?family=Lora" in html and "Caveat" in html
    assert '<p class="hero-slogan">Чан під зорями</p>' in html
    plain = ramshill.html("/")                       # інші теми — без нових шрифтів
    assert "Lora" not in plain and "Caveat" not in plain


def test_hero_focus_goes_to_theme_css(make_site, tmp_path, ramshill):
    site = make_site(cabin_config(str(tmp_path), hero_focus="28% 50%"))
    assert "/theme.css" in site.html("/")            # окремий файл, не вбудований <style> (CSP)
    css = site.client.get("/theme.css").get_data(as_text=True)
    assert "@media (max-width:760px){html[data-theme] .hero-bg{object-position:28% 50% !important}}" in css
    assert "/theme.css" not in ramshill.html("/")    # без поля — як раніше


def test_hero_focus_validation():
    for bad in ("left", "30%", "30% 50", "130% 50%", 30):
        raw = yaml.safe_load(open(cabin_config_tmp(hero_focus=bad), encoding="utf-8"))
        errors, _ = site_config.validate(raw, check_photos=False)
        assert any("brand → hero_focus" in e for e in errors), bad
    raw = yaml.safe_load(open(cabin_config_tmp(hero_focus="0% 100%"), encoding="utf-8"))
    errors, _ = site_config.validate(raw, check_photos=False)
    assert not errors


def cabin_config_tmp(**brand):
    import tempfile
    return cabin_config(tempfile.mkdtemp(), **brand)


def test_hero_style_framed(make_site, tmp_path, ramshill, monkeypatch):
    import gallery
    monkeypatch.setattr(gallery, "first", lambda folder: "media/hero/hero.webp")   # банер з фото
    assert '<section class="hero hero--framed">' in make_site(cabin_config(str(tmp_path), hero_style="framed")).html("/")
    assert '<section class="hero">' in ramshill.html("/")      # без поля — звичайний банер
    raw = yaml.safe_load(open(cabin_config_tmp(hero_style="arch"), encoding="utf-8"))
    errors, _ = site_config.validate(raw, check_photos=False)
    assert any("brand → hero_style" in e for e in errors)
