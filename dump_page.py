import sys, json
sys.path.insert(0, '/app')
from vbwd.app import create_app
from vbwd.extensions import db
app = create_app()
with app.app_context():
    from plugins.cms.src.models.cms_post import CmsPost
    p = db.session.query(CmsPost).filter(CmsPost.slug == 'checkout-confirmation', CmsPost.type == 'page').first()
    if not p: print("NO PAGE"); raise SystemExit
    out = {
        "slug": p.slug, "type": p.type, "title": getattr(p, 'title', None), "name": getattr(p, 'name', None),
        "language": p.language, "content_json": p.content_json, "content_html": p.content_html or "",
        "source_css": getattr(p, 'source_css', None), "is_published": getattr(p, 'is_published', True),
        "meta_title": p.meta_title, "meta_description": p.meta_description, "robots": getattr(p, 'robots', None),
    }
    open('/tmp/cc_page.json', 'w').write(json.dumps(out))
    print("DUMPED slug=%s title=%r content_json_keys=%s" % (p.slug, out['title'], list((p.content_json or {}).keys())[:8] if isinstance(p.content_json, dict) else type(p.content_json).__name__))
