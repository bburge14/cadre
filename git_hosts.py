from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import requests

import config
import settings

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")

_GIT_LINKS_FILE = config.INSTANCE_DIR / "git_links.json"


def _load_tokens() -> dict:
    if not config.OAUTH_TOKENS_FILE.exists():
        return {}
    return json.loads(config.OAUTH_TOKENS_FILE.read_text())


def _save_tokens(tokens: dict) -> None:
    config.OAUTH_TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    config.OAUTH_TOKENS_FILE.chmod(0o600)


def get_token(provider: str) -> str | None:
    return _load_tokens().get(provider)


def set_token(provider: str, token: str) -> None:
    tokens = _load_tokens()
    tokens[provider] = token
    _save_tokens(tokens)
    relink_all(provider)


def clear_token(provider: str) -> None:
    tokens = _load_tokens()
    tokens.pop(provider, None)
    _save_tokens(tokens)
    relink_all(provider)


def slugify_repo_name(name: str) -> str:
    return _SLUG_RE.sub("-", name).strip("-") or "repo"


# ---- Per-repo credential persistence ----
#
# Cadre's own clone step already authenticates fine (a one-off
# --config http.extraheader passed just to that `git clone` subprocess
# call), but that header was never written into the resulting repo's own
# .git/config -- so every `git push`/`git pull` an agent runs afterward,
# from inside the session itself, hit a bare unauthenticated remote with
# no connection back to the account connected in Settings. link_workdir()
# fixes that by persisting the same header into the repo's own config, and
# remembers the link (_GIT_LINKS_FILE) so relink_all() -- called
# automatically on every reconnect/disconnect in set_token/clear_token --
# can re-apply the current token to every previously-linked repo without
# anyone needing to re-clone or re-touch it by hand.


def _load_links() -> list[dict]:
    if not _GIT_LINKS_FILE.exists():
        return []
    return json.loads(_GIT_LINKS_FILE.read_text())


def _save_links(links: list[dict]) -> None:
    _GIT_LINKS_FILE.write_text(json.dumps(links, indent=2))
    _GIT_LINKS_FILE.chmod(0o600)


def _apply_credentials(workdir: str, token: str | None) -> None:
    git_dir = Path(workdir) / ".git"
    if not git_dir.exists():
        return
    if token:
        subprocess.run(
            ["git", "-C", workdir, "config", "http.extraheader", f"Authorization: Bearer {token}"],
            capture_output=True, text=True, timeout=10,
        )
        try:
            (git_dir / "config").chmod(0o600)
        except OSError:
            pass
    else:
        subprocess.run(
            ["git", "-C", workdir, "config", "--unset", "http.extraheader"],
            capture_output=True, text=True, timeout=10,
        )


def link_workdir(workdir: str, provider: str) -> None:
    workdir = str(Path(workdir).resolve())
    links = _load_links()
    if not any(link["workdir"] == workdir and link["provider"] == provider for link in links):
        links.append({"workdir": workdir, "provider": provider})
        _save_links(links)
    _apply_credentials(workdir, get_token(provider))


def relink_all(provider: str) -> None:
    token = get_token(provider)
    for link in _load_links():
        if link["provider"] != provider:
            continue
        if Path(link["workdir"]).is_dir():
            _apply_credentials(link["workdir"], token)


def detect_git_host(workdir: str) -> str | None:
    """Best-effort: does this already-existing local repo's origin remote
    point at GitHub or the configured GitLab instance? Used when a session
    is pointed at a pre-existing folder (not one Cadre itself just cloned),
    so it can still be linked to a connected account for push/pull."""
    result = subprocess.run(
        ["git", "-C", workdir, "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    if "github.com" in url:
        return "github"
    gitlab_host = (settings.get("gitlab_base_url") or "").replace("https://", "").replace("http://", "").rstrip("/")
    if gitlab_host and gitlab_host in url:
        return "gitlab"
    return None


# ---- GitHub ----


def github_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.get("github_client_id"),
        "redirect_uri": redirect_uri,
        "scope": "repo",
        "state": state,
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"https://github.com/login/oauth/authorize?{query}"


def github_exchange_code(code: str, redirect_uri: str) -> str:
    resp = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.get("github_client_id"),
            "client_secret": settings.get("github_client_secret"),
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"GitHub token exchange failed: {data}")
    return data["access_token"]


def github_list_repos(token: str) -> list[dict]:
    repos = []
    url = "https://api.github.com/user/repos?per_page=100&sort=updated"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    for _ in range(20):  # hard cap on pages, just in case
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        for repo in resp.json():
            repos.append(
                {
                    "full_name": repo["full_name"],
                    "clone_url": repo["clone_url"],
                    "private": repo["private"],
                }
            )
        next_url = resp.links.get("next", {}).get("url")
        if not next_url:
            break
        url = next_url
    return repos


def github_clone_url_for(full_name: str, repos: list[dict]) -> str:
    for repo in repos:
        if repo["full_name"] == full_name:
            return repo["clone_url"]
    raise ValueError(f"Unknown repo: {full_name}")


def github_create_repo(token: str, name: str, private: bool = True) -> str:
    resp = requests.post(
        "https://api.github.com/user/repos",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"name": name, "private": private},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["clone_url"]


# ---- GitLab ----


def gitlab_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.get("gitlab_client_id"),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "read_api read_repository",
        "state": state,
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    base = settings.get("gitlab_base_url")
    return f"{base}/oauth/authorize?{query}"


def gitlab_exchange_code(code: str, redirect_uri: str) -> str:
    base = settings.get("gitlab_base_url")
    resp = requests.post(
        f"{base}/oauth/token",
        data={
            "client_id": settings.get("gitlab_client_id"),
            "client_secret": settings.get("gitlab_client_secret"),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"GitLab token exchange failed: {data}")
    return data["access_token"]


def gitlab_list_repos(token: str) -> list[dict]:
    repos = []
    base = settings.get("gitlab_base_url")
    url = f"{base}/api/v4/projects?membership=true&per_page=100&order_by=last_activity_at"
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(20):  # hard cap on pages, just in case
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        for repo in resp.json():
            repos.append(
                {
                    "full_name": repo["path_with_namespace"],
                    "clone_url": repo["http_url_to_repo"],
                    "private": repo["visibility"] != "public",
                }
            )
        next_url = None
        next_page = resp.headers.get("X-Next-Page")
        if next_page:
            sep = "&" if "?" in url else "?"
            next_url = f"{base}/api/v4/projects?membership=true&per_page=100&order_by=last_activity_at{sep}page={next_page}"
        if not next_url:
            break
        url = next_url
    return repos


def gitlab_clone_url_for(full_name: str, repos: list[dict]) -> str:
    for repo in repos:
        if repo["full_name"] == full_name:
            return repo["clone_url"]
    raise ValueError(f"Unknown repo: {full_name}")


def gitlab_create_repo(token: str, name: str, private: bool = True) -> str:
    base = settings.get("gitlab_base_url")
    resp = requests.post(
        f"{base}/api/v4/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "visibility": "private" if private else "public"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["http_url_to_repo"]
