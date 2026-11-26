"""Базове технічне SEO, що вмикається саме на кожному сайті: robots.txt, sitemap.xml, title/description,
один h1, canonical, Schema.org (JSON-LD), Open Graph, alt / lazy / розміри фото."""

import io
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import pytest
import yaml
from PIL import Image

import seo
import site_config
from conftest import CONFIGS
from test_demo import demo_config

BASE = "https://forest-house.com.ua"


class Page(HTMLParser):
    """Те, що бачить пошуковик: title, meta, canonical, заголовки, JSON-LD, фото."""

    def __init__(self, html):
        super().__init__()
        self.title, self.meta, self.links, self.headings, self.images, self.ld = "", {}, {}, [], [], []
        self._in = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in = "title"
        elif tag == "meta" and (a.get("name") or a.get("property")):
            self.meta[a.get("name") or a.get("property")] = a.get("content", "")
        elif tag == "link":
            self.links[a.get("rel")] = a.get("href")
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        elif tag == "img":
            self.images.append(a)
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in = "ld"

    def handle_endtag(self, tag):
        self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "ld":
            self.ld.append(json.loads(data))

    def ld_type(self, kind):
        return next(x for x in self.ld if x["@type"] == kind)


def custom(tmp_path, change):
    """Копія прикладу Ramshill зі зміненими полями (назва файлу та сама — ті самі фото)."""
    raw = site_config.read_yaml(CONFIGS["ramshill"])
    change(raw)
    path = tmp_path / "ramshill.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)


def pages(s):
    return ["/", "/kontakty"] + [f"/{o['slug']}" for o in s.cfg.objects]


@pytest.fixture
def site(make_site, monkeypatch):
    monkeypatch.setenv("SITE_URL", BASE + "/")
    return make_site("site")


# ---------- robots.txt і sitemap.xml ----------

def test_robots_allows_indexing_and_points_to_sitemap(site):
    text = site.client.get("/robots.txt").get_data(as_text=True)
    assert "Allow: /" in text and "Disallow: /admin/" in text and "Disallow: /api/" in text
    assert f"Sitemap: {BASE}/sitemap.xml" in text
    assert "Disallow: /\n" not in text


def test_demo_closes_everything(make_site, tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_URL", BASE)
    s = make_site(demo_config(tmp_path))
    assert s.client.get("/robots.txt").get_data(as_text=True) == "User-agent: *\nDisallow: /\n"
    assert s.client.get("/sitemap.xml").status_code in (403, 404)      # закрито ще воротами демо


def test_sitemap_lists_every_public_page(site):
    r = site.client.get("/sitemap.xml")
    assert r.status_code == 200 and r.mimetype == "application/xml"
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "i": "http://www.google.com/schemas/sitemap-image/1.1"}
    root = ET.fromstring(r.data)
    urls = [u.findtext("s:loc", namespaces=ns) for u in root.findall("s:url", ns)]
    assert sorted(urls) == sorted(BASE + p for p in pages(site)) and urls[0] == BASE + "/"
    for u in root.findall("s:url", ns):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", u.findtext("s:lastmod", namespaces=ns))
    images = [i.text for i in root.iterfind(".//i:loc", ns)]
    assert images and all(i.startswith(BASE + "/static/media/") for i in images)
    # кожна сторінка з sitemap відкривається
    for p in pages(site):
        assert site.client.get(p).status_code == 200, p


def test_site_url_falls_back_to_request_host(make_site, monkeypatch):
    monkeypatch.setenv("SITE_URL", "forest-house.com.ua/page")       # з помилкою — береться адреса запиту
    s = make_site("ramshill")
    assert "Sitemap: http://localhost/sitemap.xml" in s.client.get("/robots.txt").get_data(as_text=True)
    assert Page(s.html("/")).links["canonical"] == "http://localhost/"


# ---------- title, description, h1, canonical ----------

@pytest.mark.parametrize("config", sorted(CONFIGS))
def test_every_page_has_unique_title_description_one_h1_and_canonical(make_site, monkeypatch, config):
    monkeypatch.setenv("SITE_URL", BASE)
    s = make_site(config)
    titles, descriptions = set(), set()
    for path in pages(s):
        p = Page(s.html(path))
        title, description = p.title.strip(), p.meta["description"]
        assert 10 <= len(title) <= seo.TITLE_MAX, (path, title)
        assert 50 <= len(description) <= seo.DESCRIPTION_MAX, (path, description)
        assert title not in titles and description not in descriptions, path
        titles.add(title)
        descriptions.add(description)
        assert p.links["canonical"] == BASE + path
        assert p.meta["og:url"] == BASE + path and p.meta["og:title"] == title
        assert p.headings.count(1) == 1 and p.headings[0] == 1, (path, p.headings)
        jumps = [(a, b) for a, b in zip(p.headings, p.headings[1:]) if b > a + 1]
        assert not jumps, (path, p.headings)
        assert "noindex" not in p.meta.get("robots", "")


def test_title_built_from_name_type_and_locality(tmp_path, make_site):
    def change(raw):
        raw["seo"].pop("title")                           # без свого title — збирається з конфігу
        raw["seo"]["landmark"] = "3 км до Буковеля"
    s = make_site(custom(tmp_path, change))
    assert Page(s.html("/")).title == "Котеджі Ramshill — Славське, 3 км до Буковеля"
    assert Page(s.html("/big")).title == "Великий котедж — Ramshill, Славське"
    assert Page(s.html("/kontakty")).title == "Контакти й як доїхати — Ramshill, Славське"


def test_long_texts_are_clipped_on_a_word():
    assert seo.clip("Слово " * 30, 60).endswith("…") and len(seo.clip("Слово " * 30, 60)) <= 60
    assert seo.clip("Коротко", 60) == "Коротко"
    text = seo.join_fit(["Перше речення.", "Друге речення трохи довше.", "Третє " * 40], 60)
    assert text == "Перше речення. Друге речення трохи довше."


@pytest.mark.parametrize("address, expected", [
    ("смт Славське, вул. Миру, 5", "Славське"), ("с. Поляниця, 12", "Поляниця"),
    ("вул. Лісова, 1, с. Яремче", "Яремче"), ("Буковель", "Буковель"),
])
def test_locality_from_address(address, expected):
    cfg = site_config.load(CONFIGS["ramshill"])
    cfg.contacts = dict(cfg.contacts, address=address, locality="")
    assert seo.locality(cfg) == expected


# ---------- Schema.org ----------

def test_lodging_business_json_ld(site):
    p = Page(site.html("/"))
    biz = p.ld_type("LodgingBusiness")
    assert biz["@context"] == "https://schema.org" and biz["@id"] == f"{BASE}/#lodging"
    assert biz["name"] == site.cfg.brand["full_name"] and biz["url"] == BASE + "/"
    assert biz["telephone"] == site.cfg.contacts["phone_href"]
    assert biz["address"]["@type"] == "PostalAddress" and biz["address"]["addressCountry"] == "UA"
    lat, lon = site.cfg.contacts["coordinates"]
    assert biz["geo"] == {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}
    assert re.fullmatch(r"\d+–\d+ грн за ніч|від \d+ грн за ніч", biz["priceRange"])
    assert biz["image"][0].startswith(BASE + "/static/media/")
    # відгуки-заглушки й неіснуючий рейтинг у розмітку не потрапляють
    assert "aggregateRating" not in biz and "review" not in biz


def test_rating_and_reviews_only_from_real_config(tmp_path, make_site):
    def change(raw):
        raw["rating"] = {"value": 4.9, "count": 37, "source": "Google Maps"}
        raw["reviews"] = [{"text": "Дуже тепло й тихо, чан — найкращий.", "author": "Ірина", "rating": 5,
                           "date": "2026-10-14"}]
        raw.setdefault("sections", {})["reviews"] = True
    s = make_site(custom(tmp_path, change))
    html = s.html("/")
    biz = Page(html).ld_type("LodgingBusiness")
    assert biz["aggregateRating"] == {"@type": "AggregateRating", "ratingValue": 4.9, "reviewCount": 37,
                                      "bestRating": 5, "worstRating": 1}
    assert biz["review"][0]["author"]["name"] == "Ірина" and biz["review"][0]["reviewRating"]["ratingValue"] == 5
    assert "Оцінка 4.9 з 5 · 37 відгуків · Google Maps" in html and 'aria-label="Оцінка 5 з 5"' in html


def test_rating_must_be_real_numbers():
    raw = site_config.read_yaml(CONFIGS["ramshill"])
    raw["rating"] = {"value": 7, "count": 0}
    errors, _ = site_config.validate(raw, check_photos=False)
    assert any("rating → value" in e for e in errors) and any("rating" in e and "count" in e for e in errors)


def test_object_page_json_ld_and_breadcrumbs(site):
    obj = site.cfg.objects[0]
    p = Page(site.html(f"/{obj['slug']}"))
    room = p.ld_type("Accommodation")
    assert room["name"] == obj["name"] and room["url"] == f"{BASE}/{obj['slug']}"
    assert room["occupancy"]["maxValue"] == obj["max_guests"]
    assert room["containedInPlace"]["@id"] == f"{BASE}/#lodging"
    crumbs = p.ld_type("BreadcrumbList")["itemListElement"]
    assert [c["item"] for c in crumbs] == [BASE + "/", f"{BASE}/{obj['slug']}"]


# ---------- Open Graph ----------

def test_open_graph_image_is_jpeg_1200x630(site):
    for path in pages(site):
        p = Page(site.html(path))
        assert p.meta["og:title"] and p.meta["og:description"] == p.meta["description"]
        assert p.meta["og:image"].startswith(BASE + "/og/") and p.meta["og:image:alt"]
        assert p.meta["twitter:card"] == "summary_large_image"
        r = site.client.get(p.meta["og:image"].replace(BASE, ""))
        assert r.status_code == 200 and r.mimetype == "image/jpeg"
        img = Image.open(io.BytesIO(r.data))
        assert img.format == "JPEG" and img.size == seo.OG_SIZE
    assert site.client.get("/og/nothing.jpg").status_code == 404


def test_no_og_image_without_photos(make_site):
    p = Page(make_site("ramshill").html("/"))         # у прикладу немає фото — картинку не вигадуємо
    assert "og:image" not in p.meta and p.meta["twitter:card"] == "summary"


# ---------- фото ----------

def test_photos_have_alt_lazy_and_real_size(site):
    for path in pages(site):
        p = Page(site.html(path))
        photos = [i for i in p.images if "/media/" in i.get("src", "") and "/brand/" not in i["src"]]
        assert photos or path == "/kontakty", path
        for i, img in enumerate(photos):
            assert img.get("alt"), (path, img["src"])
            assert img.get("width") and img.get("height"), (path, img["src"])
            assert img.get("loading") == "lazy" or img.get("fetchpriority") == "high", (path, img["src"])
        assert sum(img.get("fetchpriority") == "high" for img in photos) <= 1, path
        if photos and path != "/kontakty":
            assert photos[0].get("fetchpriority") == "high", path      # перший екран — без lazy
        for img in p.images:
            if "/brand/" in img.get("src", "") and img.get("alt"):
                assert img.get("width"), img["src"]


def test_alt_names_what_is_on_the_photo():
    assert seo.photo_alt("Котедж", "03-spalnya.webp", index=3) == "Котедж — спальня"
    assert seo.photo_alt("Котедж", "01.webp", "Фасад") == "Котедж — фасад"
    assert seo.photo_alt("Котедж", "07.webp", index=7) == "Котедж — фото 7"


# ---------- сторінки ----------

def test_contacts_page(site):
    html = site.html("/kontakty")
    assert site.cfg.contacts["phone"] in html and "Як доїхати" in html
    assert 'href="/#booking"' in html
    assert 'href="/kontakty" aria-current="page"' in html


def test_404_is_not_indexed(site):
    r = site.client.get("/takoi-storinky-nemaye")
    assert r.status_code == 404 and '<meta name="robots" content="noindex">' in r.get_data(as_text=True)
