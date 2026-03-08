#!/usr/bin/env python3
"""
Populate the CMS database with demo data.

Creates:
  - 5 light themes + 5 dark themes (CmsStyle)
  - Navigation widgets: header-nav (menu), footer-nav (menu)
  - Content widgets: hero-home1, hero-home2, cta-primary, features-3col (html)
  - 4 layouts: home-v1, home-v2, landing, content-page
  - 5 demo pages: home1, home2, landing2, landing3, about (standard content)

All inserts are idempotent — existing slugs are skipped.

Usage:
    python /app/plugins/cms/src/bin/populate_cms.py
"""
import sys
import re
import base64
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.extensions import db  # noqa: E402
from plugins.cms.src.models.cms_style import CmsStyle  # noqa: E402
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: E402
from plugins.cms.src.models.cms_menu_item import CmsMenuItem  # noqa: E402
from plugins.cms.src.models.cms_layout import CmsLayout  # noqa: E402
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget  # noqa: E402
from plugins.cms.src.models.cms_page import CmsPage  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _split_widget_content(html: str) -> tuple:
    """Extract <style> blocks → CSS; base64-encode the remaining HTML.

    Returns (content_json_dict, source_css_str).
    content_json = {"content": "<base64 of html without inline styles>"}
    """
    css_parts: list = []

    def _grab(m):
        css_parts.append(m.group(1).strip())
        return ""

    html_clean = re.sub(r"<style[^>]*>(.*?)</style>", _grab, html, flags=re.DOTALL).strip()
    b64 = base64.b64encode(html_clean.encode("utf-8")).decode("ascii")
    return {"content": b64}, "\n\n".join(css_parts)


# ─── Styles ───────────────────────────────────────────────────────────────────

LIGHT_BASE = """
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; font-family: var(--font-sans, 'Inter', system-ui, sans-serif); font-size: 16px; line-height: 1.6; }
h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 0 0 0.75em; font-weight: 700; }
p { margin: 0 0 1em; }
a { color: var(--color-link); text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; height: auto; display: block; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 1.5rem; }
.btn { display: inline-flex; align-items: center; padding: 0.65rem 1.5rem; border-radius: 6px; font-weight: 600; cursor: pointer; border: 2px solid transparent; transition: all 0.15s; }
.btn-primary { background: var(--color-primary); color: #fff; }
.btn-primary:hover { filter: brightness(1.1); }
.btn-outline { background: transparent; border-color: var(--color-primary); color: var(--color-primary); }
section { padding: 4rem 0; }
"""

DARK_BASE = LIGHT_BASE

STYLES = [
    # ── Light themes ──────────────────────────────────────────────────────────
    {
        "slug": "light-clean",
        "name": "Light — Clean",
        "sort_order": 10,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #2563eb;
  --color-link: #2563eb;
  --color-bg: #ffffff;
  --color-surface: #f8fafc;
  --color-border: #e2e8f0;
  --color-text: #1e293b;
  --color-muted: #64748b;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #fff; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-warm",
        "name": "Light — Warm",
        "sort_order": 11,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #d97706;
  --color-link: #b45309;
  --color-bg: #fffbf5;
  --color-surface: #fef3c7;
  --color-border: #fde68a;
  --color-text: #292524;
  --color-muted: #78716c;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #fff8ed; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
h1, h2 { color: #92400e; }
footer { background: #fef3c7; border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-cool",
        "name": "Light — Cool",
        "sort_order": 12,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #0284c7;
  --color-link: #0369a1;
  --color-bg: #f0f9ff;
  --color-surface: #e0f2fe;
  --color-border: #bae6fd;
  --color-text: #0c4a6e;
  --color-muted: #0369a1;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #ffffff; border-bottom: 2px solid var(--color-primary); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-soft",
        "name": "Light — Soft Pastel",
        "sort_order": 13,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #8b5cf6;
  --color-link: #7c3aed;
  --color-bg: #fdfcff;
  --color-surface: #f5f3ff;
  --color-border: #ddd6fe;
  --color-text: #2e1065;
  --color-muted: #7c3aed;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #fff; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
h1, h2 { background: linear-gradient(135deg, #7c3aed, #2563eb); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-paper",
        "name": "Light — Paper",
        "sort_order": 14,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #1a1a1a;
  --color-link: #374151;
  --color-bg: #faf7f2;
  --color-surface: #f0ebe0;
  --color-border: #d6c9b0;
  --color-text: #1c1917;
  --color-muted: #6b7280;
}
body { background: var(--color-bg); color: var(--color-text); font-family: 'Georgia', 'Times New Roman', serif; }
h1, h2, h3 { font-family: 'Georgia', serif; }
header { background: var(--color-surface); border-bottom: 2px solid var(--color-text); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 600; padding: 0 0.875rem; letter-spacing: 0.05em; text-transform: uppercase; font-size: 0.85rem; }
nav a:hover { color: #555; text-decoration: none; border-bottom: 2px solid currentColor; }
.btn-primary { background: var(--color-text); color: #faf7f2; border-radius: 0; }
footer { background: var(--color-surface); border-top: 2px solid var(--color-text); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    # ── Dark themes ───────────────────────────────────────────────────────────
    {
        "slug": "dark-midnight",
        "name": "Dark — Midnight",
        "sort_order": 20,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #60a5fa;
  --color-link: #93c5fd;
  --color-bg: #0f172a;
  --color-surface: #1e293b;
  --color-border: #334155;
  --color-text: #e2e8f0;
  --color-muted: #94a3b8;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #0f172a; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #f1f5f9; }
.btn-primary { background: var(--color-primary); color: #0f172a; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
section { border-bottom: 1px solid var(--color-border); }
""",
    },
    {
        "slug": "dark-charcoal",
        "name": "Dark — Charcoal",
        "sort_order": 21,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #f97316;
  --color-link: #fb923c;
  --color-bg: #18181b;
  --color-surface: #27272a;
  --color-border: #3f3f46;
  --color-text: #fafafa;
  --color-muted: #a1a1aa;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #111113; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #fafafa; }
.btn-primary { background: var(--color-primary); color: #18181b; font-weight: 700; }
footer { background: #111113; border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "dark-forest",
        "name": "Dark — Forest",
        "sort_order": 22,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #4ade80;
  --color-link: #86efac;
  --color-bg: #0a1a0f;
  --color-surface: #132218;
  --color-border: #1a3a22;
  --color-text: #d1fae5;
  --color-muted: #6ee7b7;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #0a150e; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #f0fdf4; text-shadow: 0 0 20px rgba(74, 222, 128, 0.2); }
.btn-primary { background: var(--color-primary); color: #052e16; font-weight: 700; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "dark-purple",
        "name": "Dark — Purple",
        "sort_order": 23,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #a78bfa;
  --color-link: #c4b5fd;
  --color-bg: #0d0a1e;
  --color-surface: #1a1433;
  --color-border: #2d2358;
  --color-text: #e9d5ff;
  --color-muted: #a78bfa;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #0d0a1e; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: #fff; text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #f5f3ff; }
.btn-primary { background: linear-gradient(135deg, #7c3aed, #2563eb); color: #fff; border: none; }
.btn-primary:hover { filter: brightness(1.15); }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "dark-carbon",
        "name": "Dark — Carbon",
        "sort_order": 24,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #e4e4e7;
  --color-link: #a1a1aa;
  --color-bg: #09090b;
  --color-surface: #141416;
  --color-border: #252528;
  --color-text: #fafafa;
  --color-muted: #71717a;
}
body { background: var(--color-bg); color: var(--color-text); font-family: 'JetBrains Mono', 'Fira Code', monospace; }
header { background: #09090b; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; letter-spacing: 0.05em; text-transform: uppercase; font-size: 0.8rem; }
nav a:hover { color: #fff; text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #fff; letter-spacing: -0.02em; }
.btn-primary { background: #fafafa; color: #09090b; border-radius: 0; font-family: inherit; font-size: 0.8rem; letter-spacing: 0.1em; text-transform: uppercase; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.75rem; font-family: inherit; }
""",
    },
]


# ─── Widget content ────────────────────────────────────────────────────────────

HERO_HOME1_HTML = """
<section class="hero">
  <div class="container">
    <h1>Build Something Amazing</h1>
    <p class="hero-sub">The modern platform for teams who ship fast. Scalable, secure, and developer-friendly.</p>
    <div class="hero-cta">
      <a href="/signup" class="btn btn-primary">Get Started Free</a>
      <a href="/demo" class="btn btn-outline" style="margin-left:1rem">Watch Demo</a>
    </div>
  </div>
</section>
<style>
.hero { padding: 6rem 0; text-align: center; }
.hero h1 { font-size: clamp(2rem, 5vw, 3.5rem); margin-bottom: 1rem; }
.hero-sub { font-size: 1.25rem; opacity: 0.75; max-width: 600px; margin: 0 auto 2.5rem; }
.hero-cta { display: flex; justify-content: center; flex-wrap: wrap; gap: 0.75rem; }
</style>
"""

HERO_HOME2_HTML = """
<section class="hero-split">
  <div class="container">
    <div class="hero-split__text">
      <span class="badge">New in 2026</span>
      <h1>Smarter Workflows, Faster Results</h1>
      <p>From idea to production in minutes. Automate your processes and focus on what matters most — your product.</p>
      <a href="/start" class="btn btn-primary">Start Building</a>
    </div>
    <div class="hero-split__image">
      <div class="hero-placeholder">🚀</div>
    </div>
  </div>
</section>
<style>
.hero-split { padding: 5rem 0; }
.hero-split .container { display: grid; grid-template-columns: 1fr 1fr; gap: 3rem; align-items: center; }
@media (max-width: 768px) { .hero-split .container { grid-template-columns: 1fr; } }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; background: var(--color-primary); color: #fff; font-size: 0.8rem; font-weight: 600; margin-bottom: 1rem; }
.hero-split h1 { font-size: clamp(1.75rem, 3.5vw, 3rem); margin-bottom: 1rem; }
.hero-split p { font-size: 1.1rem; opacity: 0.8; margin-bottom: 2rem; }
.hero-placeholder { font-size: 8rem; text-align: center; line-height: 1; background: var(--color-surface, #f8fafc); border-radius: 16px; padding: 3rem; }
</style>
"""

CTA_PRIMARY_HTML = """
<section class="cta-section">
  <div class="container">
    <h2>Ready to get started?</h2>
    <p>Join thousands of teams already using our platform. No credit card required.</p>
    <a href="/signup" class="btn btn-primary">Start Free Trial</a>
  </div>
</section>
<style>
.cta-section { text-align: center; padding: 5rem 0; background: var(--color-surface, #f8fafc); }
.cta-section h2 { font-size: 2rem; margin-bottom: 0.75rem; }
.cta-section p { opacity: 0.75; margin-bottom: 2rem; font-size: 1.1rem; }
</style>
"""

FEATURES_3COL_HTML: str = """
<section class="features">
  <div class="container">
    <h2 class="features__title">Why teams choose us</h2>
    <div class="features__grid">
      <div class="feature-card">
        <div class="feature-icon">⚡</div>
        <h3>Lightning Fast</h3>
        <p>Sub-second response times with global CDN and edge caching built in from day one.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🔒</div>
        <h3>Enterprise Security</h3>
        <p>SOC 2 Type II certified. End-to-end encryption, audit logs, and fine-grained permissions.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🔌</div>
        <h3>API-First</h3>
        <p>REST and GraphQL APIs, webhooks, and 200+ native integrations. Works with your stack.</p>
      </div>
    </div>
  </div>
</section>
<style>
.features { padding: 5rem 0; }
.features__title { text-align: center; font-size: 2rem; margin-bottom: 3rem; }
.features__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 2rem; }
.feature-card { padding: 2rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); }
.feature-icon { font-size: 2.5rem; margin-bottom: 1rem; }
.feature-card h3 { font-size: 1.2rem; margin-bottom: 0.5rem; }
.feature-card p { opacity: 0.75; font-size: 0.95rem; }
</style>
"""

PRICING_2COL_HTML = """
<section class="pricing">
  <div class="container">
    <h2 class="pricing__title">Simple, Transparent Pricing</h2>
    <div class="pricing__grid">
      <div class="pricing-card">
        <div class="pricing-card__tier">Starter</div>
        <div class="pricing-card__price">$0<span>/mo</span></div>
        <ul class="pricing-card__features">
          <li>✓ 3 projects</li><li>✓ 5 GB storage</li>
          <li>✓ Community support</li><li>✓ Basic analytics</li>
        </ul>
        <a href="/signup" class="btn btn-outline" style="width:100%;justify-content:center">Get Started</a>
      </div>
      <div class="pricing-card pricing-card--featured">
        <div class="pricing-card__tier">Pro</div>
        <div class="pricing-card__price">$49<span>/mo</span></div>
        <ul class="pricing-card__features">
          <li>✓ Unlimited projects</li><li>✓ 100 GB storage</li>
          <li>✓ Priority support</li><li>✓ Advanced analytics</li>
          <li>✓ Custom domains</li><li>✓ Team collaboration</li>
        </ul>
        <a href="/signup?plan=pro" class="btn btn-primary" style="width:100%;justify-content:center">Start Free Trial</a>
      </div>
    </div>
  </div>
</section>
<style>
.pricing { padding: 5rem 0; }
.pricing__title { text-align: center; font-size: 2rem; margin-bottom: 3rem; }
.pricing__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 2rem; max-width: 720px; margin: 0 auto; }
.pricing-card { padding: 2.5rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); }
.pricing-card--featured { border-color: var(--color-primary, #2563eb); box-shadow: 0 0 0 2px var(--color-primary, #2563eb); }
.pricing-card__tier { font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.7; margin-bottom: 0.5rem; }
.pricing-card__price { font-size: 2.5rem; font-weight: 800; margin-bottom: 1.5rem; }
.pricing-card__price span { font-size: 1rem; font-weight: 400; opacity: 0.6; }
.pricing-card__features { list-style: none; padding: 0; margin: 0 0 2rem; }
.pricing-card__features li { padding: 0.35rem 0; font-size: 0.95rem; }
</style>
"""

TESTIMONIALS_HTML = """
<section class="testimonials">
  <div class="container">
    <h2 class="testimonials__title">Loved by developers</h2>
    <div class="testimonials__grid">
      <blockquote class="testimonial">
        <p>"Switched from our old stack in a weekend. The DX is unmatched and our deploy time dropped by 80%."</p>
        <cite>— Sarah K., Lead Engineer at Acme</cite>
      </blockquote>
      <blockquote class="testimonial">
        <p>"Best decision we made this year. The team was shipping features in hours instead of days."</p>
        <cite>— Marco P., CTO at Buildfast</cite>
      </blockquote>
      <blockquote class="testimonial">
        <p>"Security audit passed first try. The built-in compliance tools saved us weeks of work."</p>
        <cite>— Jennifer L., VP Engineering at DataCo</cite>
      </blockquote>
    </div>
  </div>
</section>
<style>
.testimonials { padding: 5rem 0; }
.testimonials__title { text-align: center; font-size: 2rem; margin-bottom: 3rem; }
.testimonials__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
.testimonial { margin: 0; padding: 2rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border-left: 4px solid var(--color-primary, #2563eb); }
.testimonial p { font-size: 1rem; font-style: italic; margin-bottom: 1rem; opacity: 0.9; }
.testimonial cite { font-size: 0.875rem; opacity: 0.65; font-style: normal; font-weight: 600; }
</style>
"""

STANDARD_CONTENT_HTML = """
<h1>About Us</h1>
<p>We are a passionate team building the next generation of developer tools. Our mission is to make great software accessible to everyone.</p>
<h2>Our Story</h2>
<p>Founded in 2022, we started with a simple idea: development should be joyful. We built the tools we always wished existed, and now we share them with the world.</p>
<h2>Our Values</h2>
<ul>
  <li>Simplicity — less is more</li>
  <li>Transparency — no hidden fees, no dark patterns</li>
  <li>Community — we build with our users, not just for them</li>
</ul>
"""

STANDARD_CONTENT_JSON = {
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 1},
         "content": [{"type": "text", "text": "About Us"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "We are a passionate team building the next generation of developer tools. Our mission is to make great software accessible to everyone."}]},
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "Our Story"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "Founded in 2022, we started with a simple idea: development should be joyful. We built the tools we always wished existed, and now we share them with the world."}]},
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "Our Values"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Simplicity — less is more"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Transparency — no hidden fees, no dark patterns"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Community — we build with our users, not just for them"}]}]},
        ]},
    ],
}

# ─── Layouts ───────────────────────────────────────────────────────────────────

LAYOUTS = [
    {
        "slug": "home-v1",
        "name": "Home v1 (Hero + Features + CTA)",
        "description": "Standard homepage with hero, 3-column features, CTA bar, and footer.",
        "sort_order": 10,
        "areas": [
            {"name": "header", "type": "header", "label": "Header Navigation"},
            {"name": "hero", "type": "hero", "label": "Hero Banner"},
            {"name": "features", "type": "three-column", "label": "Feature Highlights"},
            {"name": "cta", "type": "cta-bar", "label": "Call to Action"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("hero", "hero-home1"),
            ("features", "features-3col"),
            ("cta", "cta-primary"),
            ("footer", "footer-nav"),
        ],
    },
    {
        "slug": "home-v2",
        "name": "Home v2 (Split Hero + Pricing + Testimonials)",
        "description": "Modern homepage with split hero, two-column pricing, and testimonials.",
        "sort_order": 11,
        "areas": [
            {"name": "header", "type": "header", "label": "Header Navigation"},
            {"name": "hero", "type": "hero", "label": "Split Hero"},
            {"name": "pricing", "type": "two-column", "label": "Pricing Plans"},
            {"name": "testimonials", "type": "three-column", "label": "Testimonials"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("hero", "hero-home2"),
            ("pricing", "pricing-2col"),
            ("testimonials", "testimonials"),
            ("footer", "footer-nav"),
        ],
    },
    {
        "slug": "landing",
        "name": "Landing Page (Hero + Features + CTA + Testimonials)",
        "description": "Conversion-focused landing layout without content area.",
        "sort_order": 12,
        "areas": [
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "hero", "type": "hero", "label": "Hero"},
            {"name": "features", "type": "three-column", "label": "Features"},
            {"name": "cta", "type": "cta-bar", "label": "CTA"},
            {"name": "social-proof", "type": "three-column", "label": "Testimonials"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("hero", "hero-home1"),
            ("features", "features-3col"),
            ("cta", "cta-primary"),
            ("social-proof", "testimonials"),
            ("footer", "footer-nav"),
        ],
    },
    {
        "slug": "content-page",
        "name": "Content Page (Header + Content + Footer)",
        "description": "Standard article/blog/about page with a content area in the middle.",
        "sort_order": 13,
        "areas": [
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "main", "type": "content", "label": "Main Content"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("footer", "footer-nav"),
        ],
    },
]


# ─── Main ──────────────────────────────────────────────────────────────────────

def _get_or_create_style(slug: str, data: dict) -> "CmsStyle":
    existing = db.session.query(CmsStyle).filter_by(slug=slug).first()
    if existing:
        existing.name = data["name"]
        existing.source_css = data["source_css"]
        existing.sort_order = data.get("sort_order", 0)
        db.session.flush()
        print(f"  ~ style '{slug}' (updated)")
        return existing
    obj = CmsStyle(
        slug=slug,
        name=data["name"],
        source_css=data["source_css"],
        sort_order=data.get("sort_order", 0),
        is_active=True,
    )
    db.session.add(obj)
    db.session.flush()
    print(f"  + style '{slug}'")
    return obj


def _get_or_create_widget(slug: str, name: str, widget_type: str,
                           content_html: str = None,
                           content_json: dict = None,
                           source_css: str = None) -> "CmsWidget":
    if widget_type == "html" and content_html is not None:
        content_json, extracted_css = _split_widget_content(content_html)
        source_css = source_css or extracted_css
    existing = db.session.query(CmsWidget).filter_by(slug=slug).first()
    if existing:
        existing.name = name
        if widget_type == "html":
            existing.content_json = content_json
            existing.source_css = source_css
        db.session.flush()
        print(f"  ~ widget '{slug}' (updated)")
        return existing
    obj = CmsWidget(
        slug=slug,
        name=name,
        widget_type=widget_type,
        content_json=content_json,
        source_css=source_css,
        sort_order=0,
        is_active=True,
    )
    db.session.add(obj)
    db.session.flush()
    print(f"  + widget '{slug}' ({widget_type})")
    return obj


def _add_menu_items(widget: "CmsWidget", items: list) -> None:
    for i, item in enumerate(items):
        mi = CmsMenuItem(
            widget_id=widget.id,
            parent_id=None,
            label=item["label"],
            url=item.get("url"),
            page_slug=item.get("page_slug"),
            target=item.get("target", "_self"),
            sort_order=i,
        )
        db.session.add(mi)


def _get_or_create_layout(data: dict, widget_map: dict) -> "CmsLayout":
    slug = data["slug"]
    existing = db.session.query(CmsLayout).filter_by(slug=slug).first()
    if existing:
        existing.name = data["name"]
        existing.description = data.get("description")
        existing.areas = data["areas"]
        existing.sort_order = data.get("sort_order", 0)
        db.session.flush()
        print(f"  ~ layout '{slug}' (updated)")
        return existing
    layout = CmsLayout(
        slug=slug,
        name=data["name"],
        description=data.get("description"),
        areas=data["areas"],
        sort_order=data.get("sort_order", 0),
        is_active=True,
    )
    db.session.add(layout)
    db.session.flush()
    # Assign widgets
    for order, (area_name, widget_slug) in enumerate(data.get("widget_assignments", [])):
        widget = widget_map.get(widget_slug)
        if not widget:
            print(f"    ! widget '{widget_slug}' not found, skipping assignment")
            continue
        lw = CmsLayoutWidget(
            layout_id=layout.id,
            widget_id=widget.id,
            area_name=area_name,
            sort_order=order,
        )
        db.session.add(lw)
    print(f"  + layout '{slug}'")
    return layout


def _get_or_create_page(slug: str, name: str, layout: "CmsLayout",
                          style: "CmsStyle", content_json: dict = None,
                          content_html: str = None,
                          meta_description: str = None,
                          sort_order: int = 0) -> None:
    existing = db.session.query(CmsPage).filter_by(slug=slug).first()
    if existing:
        existing.name = name
        existing.layout_id = layout.id if layout else None
        existing.style_id = style.id if style else None
        if content_json is not None:
            existing.content_json = content_json
        if content_html is not None:
            existing.content_html = content_html
        if meta_description:
            existing.meta_description = meta_description
        existing.sort_order = sort_order
        db.session.flush()
        print(f"  ~ page '{slug}' (updated)")
        return
    page = CmsPage(
        slug=slug,
        name=name,
        language="en",
        content_json=content_json or {"type": "doc", "content": []},
        content_html=content_html,
        is_published=True,
        sort_order=sort_order,
        layout_id=layout.id if layout else None,
        style_id=style.id if style else None,
        use_theme_switcher_styles=False,
        meta_title=name,
        meta_description=meta_description or name,
        robots="index,follow",
    )
    db.session.add(page)
    print(f"  + page '{slug}' (layout={layout.slug if layout else None})")


def populate_cms() -> None:
    print("\n── Styles ──────────────────────────────────────────────────────")
    style_map: dict[str, "CmsStyle"] = {}
    for s in STYLES:
        style_map[s["slug"]] = _get_or_create_style(s["slug"], s)
    db.session.commit()
    print(f"  Styles: {len(style_map)} total")

    print("\n── Widgets ─────────────────────────────────────────────────────")
    widget_map: dict[str, "CmsWidget"] = {}

    # Menu widgets
    header_nav = _get_or_create_widget("header-nav", "Header Navigation", "menu")
    widget_map["header-nav"] = header_nav
    if db.session.query(CmsMenuItem).filter_by(widget_id=header_nav.id).count() == 0:
        _add_menu_items(header_nav, [
            {"label": "Home", "page_slug": "home1"},
            {"label": "Features", "url": "/#features"},
            {"label": "Pricing", "url": "/#pricing"},
            {"label": "About", "page_slug": "about"},
        ])

    footer_nav = _get_or_create_widget("footer-nav", "Footer Navigation", "menu")
    widget_map["footer-nav"] = footer_nav
    if db.session.query(CmsMenuItem).filter_by(widget_id=footer_nav.id).count() == 0:
        _add_menu_items(footer_nav, [
            {"label": "Privacy Policy", "url": "/privacy"},
            {"label": "Terms of Service", "url": "/terms"},
            {"label": "Contact", "url": "/contact"},
        ])

    # HTML widgets
    widget_map["hero-home1"] = _get_or_create_widget(
        "hero-home1", "Hero — Home v1", "html", content_html=HERO_HOME1_HTML,
    )
    widget_map["hero-home2"] = _get_or_create_widget(
        "hero-home2", "Hero — Home v2 Split", "html", content_html=HERO_HOME2_HTML,
    )
    widget_map["cta-primary"] = _get_or_create_widget(
        "cta-primary", "CTA — Get Started", "html", content_html=CTA_PRIMARY_HTML,
    )
    widget_map["features-3col"] = _get_or_create_widget(
        "features-3col", "Features — 3 Columns", "html", content_html=FEATURES_3COL_HTML,
    )
    widget_map["pricing-2col"] = _get_or_create_widget(
        "pricing-2col", "Pricing — 2 Plans", "html", content_html=PRICING_2COL_HTML,
    )
    widget_map["testimonials"] = _get_or_create_widget(
        "testimonials", "Testimonials", "html", content_html=TESTIMONIALS_HTML,
    )

    db.session.commit()
    print(f"  Widgets: {len(widget_map)} total")

    print("\n── Layouts ─────────────────────────────────────────────────────")
    layout_map: dict[str, "CmsLayout"] = {}
    for ld in LAYOUTS:
        layout_map[ld["slug"]] = _get_or_create_layout(ld, widget_map)
    db.session.commit()
    print(f"  Layouts: {len(layout_map)} total")

    print("\n── Pages ───────────────────────────────────────────────────────")
    default_light = style_map.get("light-clean")
    default_dark = style_map.get("dark-midnight")
    home_v1 = layout_map.get("home-v1")
    home_v2 = layout_map.get("home-v2")
    landing = layout_map.get("landing")
    content_page = layout_map.get("content-page")

    _get_or_create_page(
        "home1", "Home — Version 1", home_v1, default_light,
        meta_description="Welcome to our platform. Build something amazing today.",
        sort_order=10,
    )
    _get_or_create_page(
        "home2", "Home — Version 2", home_v2, default_dark,
        meta_description="Smarter workflows, faster results. Try it free.",
        sort_order=11,
    )
    _get_or_create_page(
        "landing2", "Landing Page — Version 2", landing, style_map.get("light-cool"),
        meta_description="Discover why 10,000+ teams choose our platform.",
        sort_order=12,
    )
    _get_or_create_page(
        "landing3", "Landing Page — Version 3", landing, style_map.get("dark-purple"),
        meta_description="The developer platform built for speed and scale.",
        sort_order=13,
    )
    _get_or_create_page(
        "about", "About Us", content_page, default_light,
        content_json=STANDARD_CONTENT_JSON,
        content_html=STANDARD_CONTENT_HTML,
        meta_description="Learn about our team, our story, and our values.",
        sort_order=20,
    )

    db.session.commit()

    print("\n" + "=" * 55)
    print("✓ CMS demo data population complete")
    print(f"  Styles  : {len(STYLES)} (5 light + 5 dark)")
    print(f"  Widgets : {len(widget_map)}")
    print(f"  Layouts : {len(LAYOUTS)}")
    print("  Pages   : 5 (home1, home2, landing2, landing3, about)")
    print("=" * 55)


if __name__ == "__main__":
    from src.app import create_app

    app = create_app()
    with app.app_context():
        populate_cms()
