# CMS Plugin (Backend)

Content Management System — pages, categories, images, widgets, layouts, and styles.

## Purpose

Provides a headless CMS for creating and managing static/dynamic pages, organised into categories, with support for images, reusable widgets, layout templates, and global style configuration.

## Configuration (`plugins/config.json`)

```json
{
  "cms": {
    "upload_dir": "uploads/cms",
    "max_image_size_mb": 5,
    "allowed_extensions": ["jpg", "jpeg", "png", "gif", "webp", "svg"]
  }
}
```

## API Routes

### Public

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cms/categories` | List all categories |
| GET | `/api/v1/cms/pages` | List published pages |
| GET | `/api/v1/cms/pages/<slug>` | Get page by slug |
| GET | `/uploads/<path>` | Serve uploaded files |

### Admin (requires `@require_auth` + `@require_admin`)

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/api/v1/admin/cms/pages` | List / create pages |
| POST | `/api/v1/admin/cms/pages/bulk` | Bulk create pages |
| POST | `/api/v1/admin/cms/pages/export` | Export pages as JSON |
| POST | `/api/v1/admin/cms/pages/import` | Import pages from JSON |
| GET/PUT/DELETE | `/api/v1/admin/cms/pages/<id>` | Page detail / update / delete |
| GET/POST | `/api/v1/admin/cms/categories` | List / create categories |
| GET/PUT/DELETE | `/api/v1/admin/cms/categories/<id>` | Category detail |
| GET/POST | `/api/v1/admin/cms/images` | List / upload images |
| DELETE | `/api/v1/admin/cms/images/<id>` | Delete image |
| GET/POST | `/api/v1/admin/cms/widgets` | List / create widgets |
| GET/PUT/DELETE | `/api/v1/admin/cms/widgets/<id>` | Widget detail |
| GET/POST | `/api/v1/admin/cms/layouts` | List / create layouts |
| GET/PUT/DELETE | `/api/v1/admin/cms/layouts/<id>` | Layout detail |
| GET/PUT | `/api/v1/admin/cms/styles` | Get / update global styles |

## Events

None emitted or consumed currently.

## Database

Tables: `cms_page`, `cms_category`, `cms_image`, `cms_widget`, `cms_layout`, `cms_style`

Migration: `alembic/versions/20260302_create_cms_tables.py`

## Frontend Bundle

- Admin: `vbwd-fe-admin/plugins/cms-admin/`
- User: `vbwd-fe-user/plugins/cms/`

## Testing

```bash
docker compose run --rm test python -m pytest plugins/cms/tests/ -v
```
