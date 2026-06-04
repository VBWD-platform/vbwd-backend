"""S47.1 core seam — ``/sitemap.xml`` + ``/robots.txt`` (agnostic).

The routes aggregate registered providers (none in core ⇒ valid-empty) and
emit a sitemap-index past the 50k URL cap. ``/robots.txt`` blocks the app
surfaces and names the sitemap; ``seo.mode=off`` disallows everything.
"""
import pytest

from vbwd.services import seo_registry
from vbwd.routes.seo import SITEMAP_URL_CAP


@pytest.fixture(autouse=True)
def _clean_registry():
    seo_registry.clear_sitemap_providers()
    yield
    seo_registry.clear_sitemap_providers()


def _register(entries):
    class Provider:
        def sitemap_entries(self):
            return entries

    seo_registry.register_sitemap_provider(Provider())


def test_sitemap_empty_but_valid_with_no_providers(client):
    """Liskov: zero providers ⇒ a valid, empty urlset (not a 500)."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.content_type
    body = response.get_data(as_text=True)
    assert "<urlset" in body
    assert "<url>" not in body


def test_sitemap_lists_provider_entries(client):
    _register(
        [
            seo_registry.SitemapEntry(
                loc="https://x/de/pricing",
                lastmod="2026-01-02T00:00:00+00:00",
                changefreq="weekly",
                priority="0.8",
            )
        ]
    )
    response = client.get("/sitemap.xml")
    body = response.get_data(as_text=True)
    assert "<loc>https://x/de/pricing</loc>" in body
    assert "<lastmod>2026-01-02T00:00:00+00:00</lastmod>" in body
    assert "<changefreq>weekly</changefreq>" in body


def test_sitemap_includes_hreflang_alternates(client):
    _register(
        [
            seo_registry.SitemapEntry(
                loc="https://x/en/pricing",
                alternates=[
                    {"hreflang": "de", "href": "https://x/de/pricing"},
                    {"hreflang": "x-default", "href": "https://x/en/pricing"},
                ],
            )
        ]
    )
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert 'hreflang="de"' in body
    assert 'href="https://x/de/pricing"' in body
    assert 'hreflang="x-default"' in body


def test_sitemap_escapes_loc(client):
    _register([seo_registry.SitemapEntry(loc="https://x/a?b=1&c=2")])
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert "&amp;" in body
    assert "b=1&c=2" not in body


def test_sitemap_index_past_cap(client):
    entries = [
        seo_registry.SitemapEntry(loc=f"https://x/p{i}")
        for i in range(SITEMAP_URL_CAP + 1)
    ]
    _register(entries)
    response = client.get("/sitemap.xml")
    body = response.get_data(as_text=True)
    assert "<sitemapindex" in body
    assert "/sitemap-1.xml" in body


def test_sitemap_page_serves_a_chunk(client):
    entries = [
        seo_registry.SitemapEntry(loc=f"https://x/p{i}")
        for i in range(SITEMAP_URL_CAP + 1)
    ]
    _register(entries)
    response = client.get("/sitemap-1.xml")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<urlset" in body


def test_robots_blocks_app_surfaces(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /dashboard" in body
    assert "Disallow: /api" in body
    assert "Disallow: /admin" in body
    assert "Sitemap:" in body
    assert "/sitemap.xml" in body


def test_robots_mode_off_disallows_all(client, app):
    app.config["SEO_MODE"] = "off"
    try:
        body = client.get("/robots.txt").get_data(as_text=True)
        assert "Disallow: /" in body
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        assert "Disallow: /dashboard" not in lines
    finally:
        app.config.pop("SEO_MODE", None)


def test_robots_content_type(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "text/plain" in response.content_type
