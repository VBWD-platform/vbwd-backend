# GHRM — GitHub Repo Manager Plugin

Connects your vbwd subscription platform to GitHub repositories. Subscribers get collaborator access to private repos; cancellations trigger a configurable grace period before access is revoked.

---

## Configuration reference

All settings live in the admin panel under **Plugins → ghrm → Settings**.

| Key | Description |
|-----|-------------|
| `github_app_id` | Numeric ID of your GitHub App |
| `github_installation_id` | Installation ID of the App on your org/account |
| `github_app_private_key_path` | Absolute path to the `.pem` file inside the container |
| `github_oauth_client_id` | OAuth App Client ID (for user login via GitHub) |
| `github_oauth_client_secret` | OAuth App Client Secret |
| `github_oauth_redirect_uri` | Full callback URL registered in the OAuth App |
| `software_category_slugs` | Comma-separated tariff plan category slugs that expose the Software tab |
| `software_catalogue_cms_layout_slug` | CMS layout slug for category index and package list pages |
| `software_detail_cms_layout_slug` | CMS layout slug for package detail pages |
| `grace_period_fallback_days` | Days after cancellation before GitHub access is revoked |

---

## Step-by-step: obtaining all required IDs

### 1. Create a GitHub App

A GitHub App is used server-side to add/remove repository collaborators automatically.

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
   (or for an organisation: **Org Settings → Developer settings → GitHub Apps**)
2. Fill in:
   - **GitHub App name** — any unique name, e.g. `MyPlatform Packages`
   - **Homepage URL** — your platform URL, e.g. `https://myplatform.com`
   - **Webhook** — uncheck *Active* (not needed)
3. Under **Permissions → Repository permissions**, grant:
   - **Administration** → Read & Write (to add/remove collaborators)
4. Under **Where can this GitHub App be installed?** select **Only on this account**
5. Click **Create GitHub App**
6. On the next page, note the **App ID** — this is `github_app_id`
   Example: `App ID: 123456`
7. Scroll down to **Private keys** → click **Generate a private key**
   A `.pem` file is downloaded. Place it inside the container at the path you set in `github_app_private_key_path`, e.g.:
   ```
   /app/plugins/ghrm/github-app.pem
   ```
   Make sure the file is bind-mounted or copied into the image.

### 2. Install the GitHub App on your organisation/account

1. In the GitHub App settings page, click **Install App** (left sidebar)
2. Select your organisation or personal account
3. Choose **All repositories** or select specific repos
4. After installation, look at the URL in your browser:
   ```
   https://github.com/settings/installations/XXXXXXXX
   ```
   The number at the end (`XXXXXXXX`) is your **Installation ID** → `github_installation_id`

   Alternatively, via API:
   ```bash
   curl -H "Authorization: Bearer <your-PAT>" \
     https://api.github.com/app/installations
   ```
   Look for `"id"` in the response for your account.

### 3. Create a GitHub OAuth App (for user login)

The OAuth App lets users connect their GitHub account to the platform (to receive collaborator invitations).

1. Go to **GitHub → Settings → Developer settings → OAuth Apps → New OAuth App**
   (or for an org: **Org Settings → Developer settings → OAuth Apps**)
2. Fill in:
   - **Application name** — e.g. `MyPlatform Login`
   - **Homepage URL** — your platform URL
   - **Authorization callback URL** — this must exactly match `github_oauth_redirect_uri`, e.g.:
     ```
     https://myplatform.com/ghrm/auth/github/callback
     ```
     For local dev: `http://localhost:8080/ghrm/auth/github/callback`
3. Click **Register application**
4. On the next page:
   - **Client ID** is shown immediately → `github_oauth_client_id`
     Example: `Iv1.a1b2c3d4e5f6g7h8`
   - Click **Generate a new client secret** → copy it immediately (shown only once) → `github_oauth_client_secret`

### 4. Summary of values to paste into admin

| Setting | Where to find it |
|---------|-----------------|
| `github_app_id` | GitHub App settings page → **App ID** field |
| `github_installation_id` | URL after installing the App: `.../installations/<ID>` |
| `github_app_private_key_path` | Path where you placed the downloaded `.pem` inside the container |
| `github_oauth_client_id` | OAuth App page → **Client ID** |
| `github_oauth_client_secret` | OAuth App page → **Generate a new client secret** |
| `github_oauth_redirect_uri` | Must match the **Authorization callback URL** you registered |

---

## Populating CMS layouts, widgets and pages

After configuring the plugin, run the population script to create the required CMS records:

```bash
make populate-ghrm
```

This creates (idempotent — safe to re-run):

| Type | Slug | Purpose |
|------|------|---------|
| CMS Category | `ghrm` | Groups all GHRM pages in the CMS |
| Layout | `ghrm-software-catalogue` | Category index + package list pages |
| Layout | `ghrm-software-detail` | Package detail pages |
| Widget | `ghrm-category-index` | Vue component — category grid |
| Widget | `ghrm-package-list` | Vue component — paginated package list |
| Widget | `ghrm-package-detail` | Vue component — full package detail with tabs |
| Widget | `ghrm-search-bar` | Vue component — search input |
| Page | `category` | Root catalogue index |
| Page | `category/<slug>` | One page per entry in `software_category_slugs` |

The layout slugs and category slugs are read directly from `config.json`, so if you change `software_catalogue_cms_layout_slug` or `software_category_slugs` in the admin and re-run `make populate-ghrm`, the script will create the new records.

---

## Setting up software packages

After configuring the plugin, create a package for each private GitHub repo:

1. In admin, go to **Tariff Plans** and open a plan that belongs to a software category
2. Open the **Software** tab
3. Fill in **GitHub Owner** (your org or username) and **GitHub Repo** (repo name)
4. Click **Create Software Package**
5. Copy the generated **Sync API Key** and add it as a secret named `VBWD_SYNC_KEY` in the GitHub repo
6. Add a GitHub Action that calls:
   ```
   curl "$VBWD_API_URL/api/v1/ghrm/sync?package=<slug>&key=$VBWD_SYNC_KEY"
   ```
   on push to your release branch — this syncs the README, changelog, and release data to the platform

---

## Grace period

When a subscription is cancelled, the subscriber's GitHub collaborator access is not removed immediately. The `grace_period_fallback_days` setting controls how many days they retain access. After the grace period expires the background scheduler calls `revoke_access` and removes the collaborator from all repos linked to that plan.

Default: **7 days**. Set to `0` to revoke immediately on cancellation.
