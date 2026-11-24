"""Дизайн-система (design.py, static/css/design.css, static/js/motion.js) — правило 60/30/10.

Перевіряє: кожна тема — рівно три кольори; контраст усіх пар тексту й кнопок (WCAG AA); шрифти локальні,
з кирилицею (ґ є і ї); palettes.css актуальний; акцент лише на тому, що веде до бронювання; розміри — зі шкали;
«зменшити рух» вимикає анімації; старі теми не отримують нічого нового.
"""

import os
import re

import pytest

import design
import site_config
from conftest import CONFIGS, ROOT

CSS = open(os.path.join(ROOT, "static", "css", "design.css"), encoding="utf-8").read()
MOTION = open(os.path.join(ROOT, "static", "js", "motion.js"), encoding="utf-8").read()
HEX = re.compile(r"^#[0-9a-f]{6}$")


# ---------- палітри ----------

def test_six_to_eight_palettes_of_exactly_three_colors():
    assert 6 <= len(design.PALETTES) <= 8
    for name, p in design.PALETTES.items():
        colors = {k for k in p if re.fullmatch(r"c\d+", k)}
        assert colors == {"c60", "c30", "c10"}, name
        assert all(HEX.match(p[c]) for c in colors), name
        assert len({p["c60"], p["c30"], p["c10"]}) == 3, name
        assert p["label"] and p["mood"] and p["shape"] in design.SHAPES
    assert set(site_config.DS_THEMES) == set(design.PALETTES)
    assert not set(design.PALETTES) & set(site_config.LEGACY_THEMES)


@pytest.mark.parametrize("name", list(design.PALETTES))
def test_palette_contrast_wcag_aa(name):
    failures = [f"{label}: {design.contrast(fg, bg):.2f} < {need}" for label, fg, bg, need in design.checks(name)
                if design.contrast(fg, bg) < need]
    assert not failures, f"{name}: " + "; ".join(failures)


def test_contrast_math():
    assert design.contrast("#000000", "#ffffff") == pytest.approx(21, rel=1e-3)
    assert design.contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)
    # білий текст на банері: затемнення підібране під найгірший випадок — біле небо
    for p in design.PALETTES.values():
        d = design.derive(p)
        bg = design.blend(d["deep"], "#ffffff", float(d["scrim"]))
        assert design.contrast("#ffffff", bg) >= 4.5


def test_derived_colors_come_only_from_the_three():
    """Похідні кольори — суміші трьох кольорів теми з чорним/білим чорнилом, а не нові відтінки «з голови»."""
    for p in design.PALETTES.values():
        d = design.derive(p)
        for key in ("c60", "c30", "c10"):
            assert d[key] == p[key]
        assert d["accent-60"] in (p["c10"],) or design.contrast(d["accent-60"], p["c60"]) >= 4.6


# ---------- шрифти ----------

UKRAINIAN = "ҐґЄєІіЇї"


@pytest.mark.parametrize("folder, weight", design.used_fonts())
def test_fonts_are_local_woff2_with_ukrainian(folder, weight):
    files = design.font_files(folder, weight)
    for subset, rel in files.items():
        path = os.path.join(ROOT, "static", rel)
        assert os.path.exists(path), rel
        with open(path, "rb") as f:
            assert f.read(4) == b"wOF2", rel
    assert os.path.exists(os.path.join(ROOT, "static", "fonts", folder, "OFL.txt")), "ліцензія шрифту"
    fontTools = pytest.importorskip("fontTools.ttLib")
    pytest.importorskip("brotli")
    font = fontTools.TTFont(os.path.join(ROOT, "static", files["cyrillic"]))
    cmap = font.getBestCmap()
    missing = [ch for ch in UKRAINIAN + "АБВабвЩщЮюЯяЬь" if ord(ch) not in cmap]
    assert not missing, f"{folder} {weight}: немає {''.join(missing)}"


def test_each_theme_has_head_and_body_font_pair():
    for name, p in design.PALETTES.items():
        assert p["head"][0] in design.FONTS and p["body"][0] in design.FONTS, name
        assert p["head"][0] != p["body"][0], f"{name}: заголовок і текст — різні шрифти"
        assert len(design.preload(name)) == 2


def test_palettes_css_is_up_to_date():
    current = open(design.CSS_PATH, encoding="utf-8").read()
    assert current == design.css(), "static/css/palettes.css застарів — запустіть: python manage.py design-css"


def test_no_external_fonts_in_design_system():
    assert "googleapis" not in CSS and "gstatic" not in CSS
    assert "googleapis" not in design.css()
    assert "url('../fonts/" in design.css()


# ---------- правило 60/30/10 у стилях ----------

def _rules(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    depth, buf, out = 0, "", []
    for ch in css:
        if ch == "{":
            depth += 1
            buf += ch
        elif ch == "}":
            depth -= 1
            buf += ch
            if depth == 0:
                out.append(buf)
                buf = ""
        else:
            buf += ch
    rules = []
    for block in out:
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
            rules.append((m.group(1).strip(), m.group(2)))
    return rules


def _selectors(selector):
    """Селектори через кому верхнього рівня (коми всередині :is(...) не ділять)."""
    out, depth, cur = [], 0, ""
    for ch in selector:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return out + [cur.strip()]


ACCENT_VARS = re.compile(r"var\(--(c10|c10-hover|on-10|price|accent-(?:60|30|deep|soft-30)|primary|cta-on-dark)\)")
# Акцент (10 %) — лише те, що веде до бронювання: кнопки, ціни, вибір у формі бронювання, підсумок
ACCENT_ALLOWED = re.compile(r"btn|price|summary|cal-day|step-n|obj-opt|extra-opt|extra-tiers|mobile-cta|::selection|"
                            r":focus|check input|obj-hero|^html\[data-ds\]$")


def test_accent_only_on_booking_elements():
    bad = []
    for selector, body in _rules(CSS):
        for decl in body.split(";"):
            if ACCENT_VARS.search(decl):
                prop = decl.split(":")[0].strip()
                if prop.startswith("--") and not ACCENT_VARS.search(decl.split(":", 1)[1].split("var(")[0] or ""):
                    # перепризначення змінних (--price: var(--accent-30)) у блоках — дозволено
                    if re.match(r"--(price|primary|on-primary|primary-hover|cta-on-dark|cta-on-dark-ink|free-hover)$", prop):
                        continue
                if not all(ACCENT_ALLOWED.search(s) for s in _selectors(selector)):
                    bad.append(f"{selector} {{ {decl.strip()} }}")
    assert not bad, "Акцент поза бронюванням:\n" + "\n".join(bad)


def test_old_accent_variables_are_neutral_in_design_system():
    """--accent / --warm старого style.css (іконки, підзаголовки, зірки) у дизайн-системі — нейтральні."""
    root = next(body for sel, body in _rules(CSS) if sel == "html[data-ds]" and "--accent:" in body)
    assert "--accent: var(--muted-60)" in root and "--warm: var(--muted-60)" in root
    assert "--primary: var(--c10)" in root and "--price: var(--accent-60)" in root


SIZE_PROPS = re.compile(r"^(padding|margin|gap|row-gap|column-gap|font-size)(-[a-z]+)?$")


def test_sizes_come_from_the_scale():
    """Відступи й розміри тексту — лише зі шкали (--space-*, --fs-*), щоб нічого не «плавало»."""
    bad = []
    for selector, body in _rules(CSS):
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, value = (x.strip() for x in decl.split(":", 1))
            if not SIZE_PROPS.match(prop):
                continue
            stripped = re.sub(r"var\([^)]*\)|calc\([^;]*\)", "", value)
            if re.search(r"\d*\.?\d+(px|rem|em|vw)", stripped):
                bad.append(f"{selector} {{ {prop}: {value} }}")
    assert not bad, "Розміри поза шкалою:\n" + "\n".join(bad)


def test_scale_tokens_defined():
    for i in range(1, 11):
        assert f"--space-{i}:" in CSS
    for t in ("xs", "sm", "base", "md", "lg", "xl", "2xl", "3xl", "4xl", "hero"):
        assert f"--fs-{t}:" in CSS


# ---------- рух ----------

def test_reduced_motion_disables_everything():
    block = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "animation: none !important" in block and "transition-duration: .01ms !important" in block
    assert "[data-reveal] { opacity: 1 !important" in block and "translate: none !important" in block
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in MOTION and "if (reduce.matches) return;" in MOTION


def test_mobile_gets_lighter_motion():
    assert "@media (max-width: 760px), (hover: none)" in CSS
    mobile = CSS[CSS.index("/* телефон і планшет: легша версія"):]
    assert "animation: none; translate: none" in mobile
    assert '(min-width: 761px) and (hover: hover) and (pointer: fine)' in MOTION       # паралакс — лише миша


def test_motion_is_csp_safe():
    """Без eval, вбудованих стилів через атрибут і зовнішніх бібліотек; лише CSSOM (style.setProperty)."""
    for bad in ("eval(", "new Function", "setAttribute(\"style\"", "innerHTML", "http://", "https://", "import("):
        assert bad not in MOTION, bad
    assert "passive: true" in MOTION
    assert "transition: all" not in CSS
    for prop in re.findall(r"transition:\s*([^;]+)", CSS):
        assert not re.search(r"\b(width|height|top|left|margin|padding)\b", prop), prop    # без анімації розкладки


# ---------- сторінки ----------

def test_design_theme_page(make_site, tmp_path):
    raw = open(CONFIGS["site"], encoding="utf-8").read().replace("  theme: forest", "  theme: lake")
    cfg = tmp_path / "site.yaml"
    cfg.write_text(raw, encoding="utf-8")
    s = make_site(str(cfg))
    page = s.html("/")
    assert 'data-theme="lake" data-ds data-tone="light"' in page
    assert "css/palettes.css" in page and "css/design.css" in page and "js/motion.js" in page
    assert "fonts.googleapis" not in page and "fonts.gstatic" not in page
    assert page.count('rel="preload"') == 2 and "fonts/literata/literata-cyrillic-600-normal.woff2" in page
    hero = page[page.index('class="hero hero--ds'):page.index("</section>", page.index('class="hero hero--ds'))]
    assert hero.count('class="btn') == 1 and "Забронювати" in hero                 # одна головна кнопка
    assert "від</span> <strong>" in hero and "/ ніч" in hero                              # ціна «від …»
    assert "<h1>Forest House</h1>" in hero
    assert "brand-logo--on-page" in page                                            # темний логотип для світлої шапки
    obj = s.html("/a-frame")
    assert "data-ds" in obj and "js/motion.js" in obj


@pytest.mark.parametrize("config", ["ramshill", "blackhouse", "site"])
def test_legacy_themes_unchanged(make_site, config):
    page = make_site(config).html("/")
    assert "data-ds" not in page and "design.css" not in page and "motion.js" not in page and "palettes.css" not in page
    assert "fonts.googleapis.com" in page                                          # як і раніше
    assert "hero--ds" not in page and 'class="hero-objects"' in page or "hero--ds" not in page


def test_config_refuses_custom_colors_over_palette(tmp_path):
    raw = open(CONFIGS["site"], encoding="utf-8").read().replace("  theme: forest", "  theme: pine")
    raw = raw.replace('  accent_color: ""', '  accent_color: "#ff0000"')
    errors, _ = site_config.validate(__import__("yaml").safe_load(raw), check_photos=False)
    assert any("brand → accent_color" in e and "60/30/10" in e for e in errors)


def test_mobile_hero_photo_and_real_srcset_widths(make_site, tmp_path, monkeypatch):
    """media/hero/mobile/ — окреме вертикальне фото банера для телефона; ширини в srcset — справжні."""
    import gallery
    from PIL import Image
    static = tmp_path / "static"
    for rel, size in (("media/hero/01.webp", (1600, 1200)), ("media/hero/thumb/01.webp", (600, 450)),
                      ("media/hero/mobile/01.webp", (1000, 1333)), ("media/hero/mobile/thumb/01.webp", (600, 800))):
        (static / rel).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (90, 60, 40)).save(static / rel, "WEBP")
    monkeypatch.setattr(gallery, "STATIC_DIR", str(static))
    assert gallery.width("media/hero/mobile/01.webp") == 1000 and gallery.width("media/nope.webp") == 0
    raw = open(CONFIGS["site"], encoding="utf-8").read().replace("  theme: forest", "  theme: birch")
    cfg = tmp_path / "site.yaml"
    cfg.write_text(raw, encoding="utf-8")
    page = make_site(str(cfg)).html("/")
    assert '<source media="(max-width: 760px)" srcset="/static/media/hero/mobile/thumb/01.webp 600w, ' \
           '/static/media/hero/mobile/01.webp 1000w" sizes="100vw">' in page
    assert 'srcset="/static/media/hero/thumb/01.webp 600w, /static/media/hero/01.webp 1600w"' in page


def test_photos_pipeline_makes_mobile_hero_1000px(tmp_path, monkeypatch):
    import photos
    from PIL import Image
    monkeypatch.setattr(photos, "BASE_DIR", str(tmp_path))
    (tmp_path / "media" / "hero" / "mobile").mkdir(parents=True)
    Image.new("RGB", (3000, 4000), (120, 90, 60)).save(tmp_path / "media" / "hero" / "mobile" / "vertical.jpg")
    Image.new("RGB", (4000, 3000), (120, 90, 60)).save(tmp_path / "media" / "hero" / "wide.jpg")
    photos.run("media", log=lambda *_: None)
    with Image.open(tmp_path / "static" / "media" / "hero" / "mobile" / "vertical.webp") as im:
        assert im.width == photos.MOBILE_HERO_WIDTH
    assert (tmp_path / "static" / "media" / "hero" / "mobile" / "vertical.webp").stat().st_size <= photos.MOBILE_HERO_BYTES
    with Image.open(tmp_path / "static" / "media" / "hero" / "wide.webp") as im:
        assert im.width == photos.MAX_WIDTH
