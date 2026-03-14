# GitX — Building GitLab and Bitbucket Providers on Top of GHRM

The GHRM plugin is built against the `IGithubAppClient` interface. Any Git hosting provider
that implements this interface can be used as a drop-in replacement. This document explains
how to build GitLab and Bitbucket provider plugins.

---

## The contract: `IGithubAppClient`

All provider implementations must satisfy this Python Protocol exactly (Liskov Substitution):

```python
# plugins/ghrm/src/services/github_app_client.py

class IGithubAppClient(Protocol):
    # Collaboration management
    def add_collaborator(self, owner: str, repo: str, username: str, branch: str) -> bool: ...
    def remove_collaborator(self, owner: str, repo: str, username: str) -> bool: ...

    # Deploy tokens / access credentials
    def create_deploy_token(self, owner: str, repo: str, username: str) -> str: ...
    def revoke_deploy_token(self, token: str) -> None: ...

    # GitHub App authentication
    def get_installation_token(self, installation_id: str) -> str: ...

    # OAuth
    def exchange_oauth_code(self, code: str, client_id: str, client_secret: str, redirect_uri: str) -> str: ...
    def get_oauth_user(self, oauth_token: str) -> dict: ...  # returns {"login": str, "id": int}

    # Content fetching
    def fetch_readme(self, owner: str, repo: str) -> str: ...
    def fetch_changelog(self, owner: str, repo: str) -> Optional[str]: ...
    def fetch_docs_readme(self, owner: str, repo: str) -> Optional[str]: ...
    def fetch_releases(self, owner: str, repo: str) -> List[ReleaseDTO]: ...
    def fetch_screenshot_urls(self, owner: str, repo: str) -> List[str]: ...
```

**All methods must be implemented.** The GHRM service layer calls all of them and expects
exact return types. No method may raise `NotImplementedError` in a production implementation.

---

## Provider selection — `_make_github_client()`

```python
# plugins/ghrm/src/routes.py

def _make_github_client() -> Optional[IGithubAppClient]:
    if os.environ.get("GHRM_USE_MOCK_GITHUB", "").lower() == "true":
        from plugins.ghrm.src.services.github_app_client import MockGithubAppClient
        return MockGithubAppClient()

    provider = os.environ.get("GHRM_GIT_PROVIDER", "github").lower()

    if provider == "github":
        return _make_real_github_client()
    elif provider == "gitlab":
        from plugins.gitlab_ghrm.src.services.gitlab_client import GitLabClient
        return GitLabClient(
            base_url=os.environ.get("GITLAB_BASE_URL", "https://gitlab.com"),
            token=os.environ.get("GITLAB_TOKEN", ""),
        )
    elif provider == "bitbucket":
        from plugins.bitbucket_ghrm.src.services.bitbucket_client import BitbucketClient
        return BitbucketClient(
            workspace=os.environ.get("BITBUCKET_WORKSPACE", ""),
            token=os.environ.get("BITBUCKET_TOKEN", ""),
        )

    return None
```

`.env` additions:

```
GHRM_GIT_PROVIDER=github   # github | gitlab | bitbucket
GITLAB_BASE_URL=https://gitlab.com
GITLAB_TOKEN=glpat-xxxxxxxx
BITBUCKET_WORKSPACE=my-workspace
BITBUCKET_TOKEN=xxxxxxxxxxxx
```

---

## GitLab provider

### Plugin location

```
vbwd-backend/plugins/gitlab_ghrm/
├── __init__.py
├── config.json
└── src/
    └── services/
        └── gitlab_client.py
```

### API mapping — GitHub → GitLab

| GHRM method | GitHub API | GitLab API |
|-------------|-----------|-----------|
| `add_collaborator` | `PUT /repos/{owner}/{repo}/collaborators/{username}` | `POST /projects/{id}/members` with `access_level=30` (Developer) |
| `remove_collaborator` | `DELETE /repos/{owner}/{repo}/collaborators/{username}` | `DELETE /projects/{id}/members/{user_id}` |
| `create_deploy_token` | GitHub: `POST /repos/{owner}/{repo}/keys` (deploy key) or OAuth token | `POST /projects/{id}/deploy_tokens` with `scopes=["read_repository"]` |
| `revoke_deploy_token` | N/A (tokens are personal) | `DELETE /projects/{id}/deploy_tokens/{token_id}` |
| `get_installation_token` | GitHub App installation token exchange | Not applicable — return `self._token` directly |
| `exchange_oauth_code` | `POST https://github.com/login/oauth/access_token` | `POST https://gitlab.com/oauth/token` with `grant_type=authorization_code` |
| `get_oauth_user` | `GET https://api.github.com/user` | `GET https://gitlab.com/api/v4/user` — map `username` → `login` |
| `fetch_readme` | `GET /repos/{owner}/{repo}/readme` | `GET /projects/{id}/repository/files/README.md/raw?ref=main` |
| `fetch_changelog` | `GET /repos/{owner}/{repo}/contents/CHANGELOG.md` | `GET /projects/{id}/repository/files/CHANGELOG.md/raw?ref=main` |
| `fetch_docs_readme` | `GET /repos/{owner}/{repo}/contents/docs/README.md` | `GET /projects/{id}/repository/files/docs%2FREADME.md/raw?ref=main` |
| `fetch_releases` | `GET /repos/{owner}/{repo}/releases` | `GET /projects/{id}/releases` — map tags to `ReleaseDTO` |
| `fetch_screenshot_urls` | List `screenshots/` directory | `GET /projects/{id}/repository/tree?path=screenshots&ref=main` → map to raw URLs |

### Key differences

**Project ID vs owner/repo:**
GitLab uses a numeric `project_id` or URL-encoded `namespace/project` path:

```python
def _project_id(self, owner: str, repo: str) -> str:
    return urllib.parse.quote(f"{owner}/{repo}", safe="")
    # Used as: /projects/{id}/...
```

**Deploy tokens:**
GitLab's deploy tokens are tied to the project and have an explicit expiry and scope:

```python
def create_deploy_token(self, owner: str, repo: str, username: str) -> str:
    url = f"{self._base_url}/api/v4/projects/{self._project_id(owner, repo)}/deploy_tokens"
    payload = {
        "name": f"vbwd-{username}-{int(time.time())}",
        "scopes": ["read_repository"],
        "expires_at": (datetime.utcnow() + timedelta(days=365)).strftime("%Y-%m-%d"),
    }
    resp = httpx.post(url, json=payload, headers=self._headers())
    resp.raise_for_status()
    token_data = resp.json()
    # Store token_id for revocation: token_data["id"]
    # Return the token value: token_data["token"]
    return token_data["token"]
```

**OAuth scope:**
GitLab OAuth needs `read_user` scope (equivalent to GitHub's `read:user`).
Authorization URL: `https://gitlab.com/oauth/authorize?client_id=...&scope=read_user&response_type=code&redirect_uri=...`

### Minimal implementation

```python
# plugins/gitlab_ghrm/src/services/gitlab_client.py
import httpx
from typing import Optional, List
from plugins.ghrm.src.services.github_app_client import IGithubAppClient, ReleaseDTO, ReleaseAsset

class GitLabClient:
    """GitLab implementation of IGithubAppClient."""

    def __init__(self, base_url: str, token: str):
        self._base_url = base_url.rstrip("/")
        self._token    = token

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self._token, "Content-Type": "application/json"}

    def _pid(self, owner: str, repo: str) -> str:
        import urllib.parse
        return urllib.parse.quote(f"{owner}/{repo}", safe="")

    def add_collaborator(self, owner: str, repo: str, username: str, branch: str) -> bool:
        # Resolve user ID first
        user_resp = httpx.get(f"{self._base_url}/api/v4/users?username={username}", headers=self._headers())
        user_resp.raise_for_status()
        users = user_resp.json()
        if not users:
            return False
        user_id = users[0]["id"]
        resp = httpx.post(
            f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/members",
            json={"user_id": user_id, "access_level": 30},  # 30 = Developer
            headers=self._headers(),
        )
        return resp.status_code in (200, 201, 409)  # 409 = already member

    def remove_collaborator(self, owner: str, repo: str, username: str) -> bool:
        user_resp = httpx.get(f"{self._base_url}/api/v4/users?username={username}", headers=self._headers())
        users = user_resp.json()
        if not users:
            return True
        user_id = users[0]["id"]
        resp = httpx.delete(
            f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/members/{user_id}",
            headers=self._headers(),
        )
        return resp.status_code in (200, 204, 404)

    def create_deploy_token(self, owner: str, repo: str, username: str) -> str:
        from datetime import datetime, timedelta
        import time
        url = f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/deploy_tokens"
        resp = httpx.post(url, json={
            "name": f"vbwd-{username}-{int(time.time())}",
            "scopes": ["read_repository"],
            "expires_at": (datetime.utcnow() + timedelta(days=365)).strftime("%Y-%m-%d"),
        }, headers=self._headers())
        resp.raise_for_status()
        return resp.json()["token"]

    def revoke_deploy_token(self, token: str) -> None:
        # GitLab requires the token_id for revocation, not the token value.
        # Store token_id externally (e.g. in ghrm_user_github_access.provider_data JSON).
        raise NotImplementedError("revoke_deploy_token requires stored token_id — see ghrm_user_github_access.provider_data")

    def get_installation_token(self, installation_id: str) -> str:
        return self._token  # GitLab uses a static PAT

    def exchange_oauth_code(self, code: str, client_id: str, client_secret: str, redirect_uri: str) -> str:
        resp = httpx.post(f"{self._base_url}/oauth/token", json={
            "client_id":     client_id,
            "client_secret": client_secret,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  redirect_uri,
        })
        resp.raise_for_status()
        return resp.json()["access_token"]

    def get_oauth_user(self, oauth_token: str) -> dict:
        resp = httpx.get(f"{self._base_url}/api/v4/user", headers={"Authorization": f"Bearer {oauth_token}"})
        resp.raise_for_status()
        data = resp.json()
        return {"login": data["username"], "id": data["id"]}

    def fetch_readme(self, owner: str, repo: str) -> str:
        resp = httpx.get(
            f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/repository/files/README.md/raw",
            params={"ref": "main"}, headers=self._headers()
        )
        resp.raise_for_status()
        return resp.text

    def fetch_changelog(self, owner: str, repo: str) -> Optional[str]:
        resp = httpx.get(
            f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/repository/files/CHANGELOG.md/raw",
            params={"ref": "main"}, headers=self._headers()
        )
        return resp.text if resp.status_code == 200 else None

    def fetch_docs_readme(self, owner: str, repo: str) -> Optional[str]:
        import urllib.parse
        path = urllib.parse.quote("docs/README.md", safe="")
        resp = httpx.get(
            f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/repository/files/{path}/raw",
            params={"ref": "main"}, headers=self._headers()
        )
        return resp.text if resp.status_code == 200 else None

    def fetch_releases(self, owner: str, repo: str) -> List[ReleaseDTO]:
        resp = httpx.get(
            f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/releases",
            headers=self._headers()
        )
        resp.raise_for_status()
        results = []
        for r in resp.json():
            assets = [
                ReleaseAsset(name=a["name"], url=a["direct_asset_url"])
                for a in r.get("assets", {}).get("links", [])
            ]
            results.append(ReleaseDTO(tag=r["tag_name"], date=r["released_at"], notes=r.get("description", ""), assets=assets))
        return results

    def fetch_screenshot_urls(self, owner: str, repo: str) -> List[str]:
        resp = httpx.get(
            f"{self._base_url}/api/v4/projects/{self._pid(owner, repo)}/repository/tree",
            params={"path": "screenshots", "ref": "main"}, headers=self._headers()
        )
        if resp.status_code != 200:
            return []
        base = f"{self._base_url}/{owner}/{repo}/-/raw/main/screenshots"
        return [f"{base}/{f['name']}" for f in resp.json() if f["type"] == "blob"]
```

---

## Bitbucket provider

### Plugin location

```
vbwd-backend/plugins/bitbucket_ghrm/
├── __init__.py
├── config.json
└── src/
    └── services/
        └── bitbucket_client.py
```

### API mapping — GitHub → Bitbucket

| GHRM method | GitHub API | Bitbucket API |
|-------------|-----------|--------------|
| `add_collaborator` | `PUT /repos/{owner}/{repo}/collaborators/{username}` | `POST /2.0/repositories/{workspace}/{slug}/permissions-config/users/{user_slug}` with `permission=write` |
| `remove_collaborator` | `DELETE` same | `DELETE /2.0/repositories/{workspace}/{slug}/permissions-config/users/{user_slug}` |
| `create_deploy_token` | Deploy key | `POST /2.0/repositories/{workspace}/{slug}/deploy-keys` (SSH key) OR App Password via workspace API |
| `revoke_deploy_token` | N/A | `DELETE /2.0/repositories/{workspace}/{slug}/deploy-keys/{key_id}` |
| `exchange_oauth_code` | GitHub OAuth | `POST https://bitbucket.org/site/oauth2/access_token` with `grant_type=authorization_code` |
| `get_oauth_user` | `GET /user` | `GET https://api.bitbucket.org/2.0/user` — map `username` → `login` |
| `fetch_readme` | Contents API | `GET /2.0/repositories/{workspace}/{slug}/src/main/README.md` |
| `fetch_changelog` | Same | `GET /2.0/repositories/{workspace}/{slug}/src/main/CHANGELOG.md` |
| `fetch_releases` | Releases API | Bitbucket has no releases. Use `GET /2.0/repositories/{workspace}/{slug}/tags` |
| `fetch_screenshot_urls` | Directory listing | `GET /2.0/repositories/{workspace}/{slug}/src/main/screenshots/?format=meta` |

### Key differences

**Workspace model:**
Bitbucket organises repos under a **workspace** (equivalent to GitHub org/user). The `owner`
parameter in GHRM maps to the Bitbucket workspace slug.

**Deploy credentials:**
Bitbucket does not have per-user deploy tokens in the same sense. The closest equivalents are:
- **Deploy keys** — SSH public keys with read-only repo access
- **App passwords** — scoped repository read access tied to a Bitbucket user account

For VBWD's use case (git clone/pip install), **App Passwords** are recommended:
the VBWD server generates an App Password for the subscriber's linked Bitbucket account
using Bitbucket's `POST /2.0/users/{user}/app-passwords` endpoint.

**Releases → Tags:**
Bitbucket has no "releases" concept. Map repository tags to `ReleaseDTO`:

```python
def fetch_releases(self, owner: str, repo: str) -> List[ReleaseDTO]:
    resp = httpx.get(
        f"https://api.bitbucket.org/2.0/repositories/{owner}/{repo}/tags",
        auth=(self._username, self._token)
    )
    resp.raise_for_status()
    results = []
    for tag in resp.json().get("values", []):
        results.append(ReleaseDTO(
            tag=tag["name"],
            date=tag["target"]["date"],
            notes="",       # Bitbucket tags have no release notes
            assets=[],
        ))
    return results
```

**Authentication:**
Bitbucket uses HTTP Basic Auth with `username:app_password`:

```python
self._auth = (workspace_user, app_password)
# Used as: httpx.get(url, auth=self._auth)
```

### OAuth 2.0 differences

| Step | GitHub | Bitbucket |
|------|--------|-----------|
| Auth URL | `https://github.com/login/oauth/authorize` | `https://bitbucket.org/site/oauth2/authorize` |
| Token URL | `https://github.com/login/oauth/access_token` | `https://bitbucket.org/site/oauth2/access_token` |
| Scope | `read:user` | `account` |
| Token response | JSON with `access_token` | JSON with `access_token` (OAuth 2.0 standard) |

---

## Testing a new provider

Use the same test patterns as for the GitHub provider:

```python
# plugins/gitlab_ghrm/tests/unit/test_gitlab_client.py
from unittest.mock import patch, MagicMock
from plugins.gitlab_ghrm.src.services.gitlab_client import GitLabClient

def _make_client():
    return GitLabClient(base_url="https://gitlab.com", token="test-token")

class TestAddCollaborator:
    def test_adds_member_successfully(self):
        client = _make_client()
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [{"id": 42}])
            mock_post.return_value = MagicMock(status_code=201)
            result = client.add_collaborator("myorg", "myrepo", "alice", "main")
        assert result is True

    def test_returns_true_when_already_member(self):
        client = _make_client()
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [{"id": 42}])
            mock_post.return_value = MagicMock(status_code=409)  # already member
            result = client.add_collaborator("myorg", "myrepo", "alice", "main")
        assert result is True
```

Also create a `MockGitLabClient` (same structure as `MockGithubAppClient`) for use in
GHRM service unit tests without HTTP calls.

---

## Checklist: adding a new provider

- [ ] Create `plugins/<provider>_ghrm/` plugin directory
- [ ] Implement `IGithubAppClient` protocol — all 14 methods
- [ ] Create `Mock<Provider>Client` for test doubles
- [ ] Add env var `GHRM_GIT_PROVIDER=<provider>` to `.env.example`
- [ ] Add provider config vars to `.env.example` (token, base URL, etc.)
- [ ] Add provider branch to `_make_github_client()` in `plugins/ghrm/src/routes.py`
- [ ] Write unit tests for all implemented methods (mocked HTTP)
- [ ] Write integration tests behind `GHRM_USE_REAL_<PROVIDER>=true` feature flag
- [ ] Register plugin in `plugins/plugins.json` (disabled by default)
- [ ] Add to `plugins/config.json` with provider-specific config schema
- [ ] Update GHRM admin settings to expose provider selection UI
- [ ] Document OAuth setup in provider's own README.md
