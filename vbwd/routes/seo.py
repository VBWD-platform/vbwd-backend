"""Core SEO seam — ``/sitemap.xml`` + ``/robots.txt`` (agnostic).

These two routes are the ONLY SEO endpoints core ships. They aggregate
whatever sitemap providers plugins have registered (core declares none) and
serve the conventional ``robots.txt``. No plugin name appears here: the route
talks to the duck-typed ``seo_registry`` aggregator and to Flask config only.

Past ``SITEMAP_URL_CAP`` URLs the sitemap becomes an index pointing at numbered
chunk files (``/sitemap-<n>.xml``), as the sitemaps.org protocol requires.
"""
from xml.sax.saxutils import escape, quoteattr

from flask import Blueprint, Response, current_app, request

from vbwd.services.seo_registry import aggregate_sitemap_entries

seo_bp = Blueprint("seo", __name__)

# sitemaps.org caps a single sitemap at 50,000 URLs; past that we emit an index.
SITEMAP_URL_CAP = 50000

_DISALLOWED_SURFACES = ("/dashboard", "/api", "/admin")


def _seo_mode() -> str:
    """Resolve the SEO mode (``on``/``off``) from Flask config, default ``on``."""
    return str(current_app.config.get("SEO_MODE", "on")).lower()


def _xml_response(body: str) -> Response:
    return Response(body, status=200, mimetype="application/xml")


def _render_url_element(entry) -> str:
    parts = [f"  <url>\n    <loc>{escape(entry.loc)}</loc>"]
    if entry.lastmod:
        parts.append(f"    <lastmod>{escape(entry.lastmod)}</lastmod>")
    if entry.changefreq:
        parts.append(f"    <changefreq>{escape(entry.changefreq)}</changefreq>")
    if entry.priority:
        parts.append(f"    <priority>{escape(entry.priority)}</priority>")
    for alternate in entry.alternates:
        hreflang = quoteattr(alternate.get("hreflang", ""))
        href = quoteattr(alternate.get("href", ""))
        parts.append(
            '    <xhtml:link rel="alternate" ' f"hreflang={hreflang} href={href} />"
        )
    parts.append("  </url>")
    return "\n".join(parts)


def _render_urlset(entries) -> str:
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
    )
    rows = "\n".join(_render_url_element(entry) for entry in entries)
    if rows:
        rows += "\n"
    return header + rows + "</urlset>\n"


def _render_sitemap_index(chunk_count: int) -> str:
    base = request.host_url.rstrip("/")
    rows = []
    for index in range(1, chunk_count + 1):
        loc = escape(f"{base}/sitemap-{index}.xml")
        rows.append(f"  <sitemap>\n    <loc>{loc}</loc>\n  </sitemap>")
    body = "\n".join(rows)
    if body:
        body += "\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</sitemapindex>\n"
    )


def _chunk(entries, size):
    for start in range(0, len(entries), size):
        yield entries[start : start + size]


@seo_bp.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """Aggregate all providers; emit an index past the URL cap."""
    entries = aggregate_sitemap_entries()
    if len(entries) > SITEMAP_URL_CAP:
        chunk_count = (len(entries) + SITEMAP_URL_CAP - 1) // SITEMAP_URL_CAP
        return _xml_response(_render_sitemap_index(chunk_count))
    return _xml_response(_render_urlset(entries))


@seo_bp.route("/sitemap-<int:chunk>.xml", methods=["GET"])
def sitemap_chunk(chunk: int):
    """Serve the ``chunk``-th 50k-URL slice (1-based)."""
    entries = aggregate_sitemap_entries()
    chunks = list(_chunk(entries, SITEMAP_URL_CAP))
    if chunk < 1 or chunk > len(chunks):
        return _xml_response(_render_urlset([]))
    return _xml_response(_render_urlset(chunks[chunk - 1]))


@seo_bp.route("/robots.txt", methods=["GET"])
def robots():
    """Block app surfaces + name the sitemap; ``seo.mode=off`` blocks all."""
    base = request.host_url.rstrip("/")
    sitemap_line = f"Sitemap: {base}/sitemap.xml"
    if _seo_mode() == "off":
        body = "User-agent: *\nDisallow: /\n\n" + sitemap_line + "\n"
        return Response(body, status=200, mimetype="text/plain")

    lines = ["User-agent: *"]
    lines.extend(f"Disallow: {surface}" for surface in _DISALLOWED_SURFACES)
    lines.append("")
    lines.append(sitemap_line)
    return Response("\n".join(lines) + "\n", status=200, mimetype="text/plain")
