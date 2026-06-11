import sys, json
sys.path.insert(0,'/app')
from vbwd.app import create_app
from vbwd.extensions import db
app=create_app()
with app.app_context():
    from plugins.cms.src.repositories.post_repository import PostRepository
    from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
    pr=PostRepository(db.session)
    # find the checkout-confirmation page
    from plugins.cms.src.models.cms_post import CmsPost
    p=db.session.query(CmsPost).filter(CmsPost.slug=='checkout-confirmation').first()
    if not p: print("NO PAGE"); raise SystemExit
    lay = CmsLayoutRepository(db.session).find_by_id(str(p.layout_id)) if p.layout_id else None
    print(json.dumps({"slug":p.slug,"type":p.type,"layout_id":str(p.layout_id),"layout_slug":(lay.slug if lay else None),
      "content_html_len":len(p.content_html or ''), "has_content_json":bool(p.content_json)}))
