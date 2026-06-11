import sys, json
sys.path.insert(0, '/app')
from vbwd.app import create_app
from vbwd.extensions import db
FLOW_LAYOUTS = {"booking-catalogue","booking-resource-detail","booking-form","booking-success","booking-cancel","checkout","checkout-confirmation"}
app = create_app()
with app.app_context():
    from plugins.cms.src.models.cms_post import CmsPost
    from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
    lr = CmsLayoutRepository(db.session)
    items = []
    for p in db.session.query(CmsPost).filter(CmsPost.type == 'page').all():
        lay = lr.find_by_id(str(p.layout_id)) if p.layout_id else None
        lslug = lay.slug if lay else None
        if (lslug in FLOW_LAYOUTS) or ('booking' in (p.slug or '')) or ('checkout' in (p.slug or '')):
            items.append({"type":"page","slug":p.slug,"title":getattr(p,'title',None) or getattr(p,'name',None),
              "language":p.language or "en","content_json":p.content_json,"content_html":p.content_html or "",
              "source_css":getattr(p,'source_css',None),"meta_title":p.meta_title,"meta_description":p.meta_description,
              "is_published":True,"layout_slug":lslug})
    open('/tmp/flow_pages.json','w').write(json.dumps({"items":items}))
    print("FLOW PAGES on localhost:")
    for i in items: print("  ", i['slug'], "-> layout", i['layout_slug'])
