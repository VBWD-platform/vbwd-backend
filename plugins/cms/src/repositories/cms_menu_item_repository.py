"""CmsMenuItem repository."""
from typing import List, Dict, Any
from uuid import uuid4
from plugins.cms.src.models.cms_menu_item import CmsMenuItem


class CmsMenuItemRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_tree_by_widget(self, widget_id: str) -> List[CmsMenuItem]:
        return (
            self.session.query(CmsMenuItem)
            .filter(CmsMenuItem.widget_id == widget_id)
            .order_by(CmsMenuItem.sort_order.asc())
            .all()
        )

    def replace_tree(self, widget_id: str, items: List[Dict[str, Any]]) -> List[CmsMenuItem]:
        """Delete all existing items for widget and insert new tree atomically."""
        self.session.query(CmsMenuItem).filter(CmsMenuItem.widget_id == widget_id).delete(
            synchronize_session="fetch"
        )
        created = []
        for item_data in items:
            item = CmsMenuItem()
            item.id = uuid4()
            item.widget_id = widget_id
            item.parent_id = item_data.get("parent_id")
            item.label = item_data.get("label", "")
            item.url = item_data.get("url")
            item.page_slug = item_data.get("page_slug")
            item.target = item_data.get("target", "_self")
            item.icon = item_data.get("icon")
            item.sort_order = item_data.get("sort_order", 0)
            self.session.add(item)
            created.append(item)
        self.session.flush()
        self.session.commit()
        return created

    def delete_by_widget(self, widget_id: str) -> None:
        self.session.query(CmsMenuItem).filter(CmsMenuItem.widget_id == widget_id).delete(
            synchronize_session="fetch"
        )
        self.session.flush()
        self.session.commit()
