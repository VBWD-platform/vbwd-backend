#!/usr/bin/env python
"""Populate GHRM demo data: CMS layouts, widgets, pages, and demo software packages.

Usage: python /app/plugins/ghrm/bin/populate_ghrm.py
"""
import sys
sys.path.insert(0, '/app')

from src.extensions import Session
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.models.cms_page import CmsPage
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget

session = Session()

try:
    print("\n=== Creating GHRM CMS Layouts ===")

    # Layout: category list page
    layout_list = session.query(CmsLayout).filter_by(slug="ghrm-category-list").first()
    if not layout_list:
        layout_list = CmsLayout(
            name="GHRM Category List",
            slug="ghrm-category-list",
            description="Layout for software category pages",
            structure={"areas": [{"id": "content", "label": "Content", "width": 12}]},
            is_active=True,
        )
        session.add(layout_list)
        session.flush()
        print("  Created: ghrm-category-list")
    else:
        print("  Exists: ghrm-category-list")

    # Layout: software detail page
    layout_detail = session.query(CmsLayout).filter_by(slug="ghrm-software-detail").first()
    if not layout_detail:
        layout_detail = CmsLayout(
            name="GHRM Software Detail",
            slug="ghrm-software-detail",
            description="Layout for software package detail pages",
            structure={"areas": [{"id": "content", "label": "Content", "width": 12}]},
            is_active=True,
        )
        session.add(layout_detail)
        session.flush()
        print("  Created: ghrm-software-detail")
    else:
        print("  Exists: ghrm-software-detail")

    print("\n=== Creating GHRM CMS Widgets ===")

    SOFTWARE_LIST_HTML = """<div id="ghrm-software-list"></div>
<script src="/embed/ghrm-list.js" data-category="{{ category_slug }}"></script>"""

    SOFTWARE_DETAIL_HTML = """<div id="ghrm-software-detail"></div>
<script src="/embed/ghrm-detail.js" data-slug="{{ package_slug }}"></script>"""

    widgets = [
        {
            "slug": "ghrm-software-list",
            "name": "GHRM Software List",
            "widget_type": "html",
            "description": "Embeds the GHRM package list component",
            "content_json": {"content": SOFTWARE_LIST_HTML},
        },
        {
            "slug": "ghrm-software-detail-content",
            "name": "GHRM Software Detail",
            "widget_type": "html",
            "description": "Embeds the GHRM package detail component",
            "content_json": {"content": SOFTWARE_DETAIL_HTML},
        },
    ]

    widget_map = {}
    for w in widgets:
        widget = session.query(CmsWidget).filter_by(slug=w["slug"]).first()
        if not widget:
            widget = CmsWidget(
                slug=w["slug"],
                name=w["name"],
                widget_type=w["widget_type"],
                description=w.get("description", ""),
                content_json=w["content_json"],
                is_active=True,
            )
            session.add(widget)
            session.flush()
            print(f"  Created: {w['slug']}")
        else:
            print(f"  Exists: {w['slug']}")
        widget_map[w["slug"]] = widget

    print("\n=== Creating GHRM CMS Pages ===")

    category_pages = [
        {"slug": "category/backend",  "name": "Backend Plugins",  "category_slug": "backend"},
        {"slug": "category/fe-user",  "name": "FE User Plugins",  "category_slug": "fe-user"},
        {"slug": "category/fe-admin", "name": "FE Admin Plugins", "category_slug": "fe-admin"},
    ]

    for p in category_pages:
        page = session.query(CmsPage).filter_by(slug=p["slug"]).first()
        if not page:
            page = CmsPage(
                slug=p["slug"],
                name=p["name"],
                language="en",
                content_json={"type": "doc", "content": []},
                is_published=True,
                sort_order=0,
                layout_id=layout_list.id,
                robots="index,follow",
            )
            session.add(page)
            session.flush()
            # Assign ghrm-software-list widget to the content area
            lw = CmsLayoutWidget(
                layout_id=layout_list.id,
                widget_id=widget_map["ghrm-software-list"].id,
                area_id="content",
                sort_order=0,
            )
            session.add(lw)
            session.flush()
            print(f"  Created page: /{p['slug']}")
        else:
            print(f"  Exists page: /{p['slug']}")

    session.commit()
    print("\n=== Done ===")
    print(f"  Layouts: 2 (ghrm-category-list, ghrm-software-detail)")
    print(f"  Widgets: 2 (ghrm-software-list, ghrm-software-detail-content)")
    print(f"  Pages:   {len(category_pages)}")

except Exception:
    session.rollback()
    import traceback; traceback.print_exc()
    sys.exit(1)
finally:
    session.close()
