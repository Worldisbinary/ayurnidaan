"""Post-deploy smoke test. Stdlib only, so it runs anywhere CI does.

    python scripts/smoke.py --api https://ayurnidaan-api.onrender.com \
        [--web https://ayurnidaan.vercel.app] [--expect-commit <sha>] [--wait 900] [--production]

Checks the things that break in deploys, not business logic (pytest covers that):
the right commit is live, the database and knowledge pack are reachable, security headers
are set, protected endpoints refuse anonymous callers, CORS does not reflect strangers,
API docs are off in production, and the web app serves its bundle with its headers.
Exit code 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

API_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "strict-transport-security": None,
    "content-security-policy": None,
}
WEB_HEADERS = {"x-content-type-options": "nosniff", "content-security-policy": None}

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise SystemExit(f"refusing to call {url}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "ayurnidaan-smoke/1", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 - scheme checked above
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def wait_for_commit(api: str, sha: str, timeout: int) -> None:
    """Free-tier Render cold-starts and rebuilds take minutes; poll /health until it's ours."""
    deadline, seen = time.time() + timeout, None
    while time.time() < deadline:
        try:
            status, _, body = get(f"{api}/health")
            if status == 200:
                seen = json.loads(body).get("commit")
                if seen and seen != "dev" and (seen.startswith(sha) or sha.startswith(seen)):
                    print(f"deployed commit {seen[:12]} is live")
                    return
        except (OSError, ValueError):
            pass
        time.sleep(15)
    check(False, f"commit {sha[:12]} live within {timeout}s (last seen {seen})")


def check_headers(headers: dict[str, str], expected: dict[str, str | None], where: str) -> None:
    for name, value in expected.items():
        got = headers.get(name)
        check(got is not None and (value is None or got == value), f"{where}: {name} header")


def smoke_api(api: str, production: bool) -> None:
    print(f"API {api}")
    status, headers, body = get(f"{api}/health")
    check(status == 200 and json.loads(body).get("status") == "ok", "/health is ok")
    check_headers(headers, API_HEADERS, "/health")

    status, _, body = get(f"{api}/ready")
    ready = json.loads(body) if status == 200 else {}
    check(status == 200 and ready.get("database") is True, "/ready: database reachable")
    check(bool(ready.get("knowledge_pack")), "/ready: knowledge pack loaded")

    status, _, body = get(f"{api}/api/v1/meta")
    check(status == 200 and b"knowledge_pack" in body, "public knowledge endpoint serves data")

    status, _, _ = get(f"{api}/api/v1/me/profile")
    check(status == 401, "/api/v1/me/profile refuses anonymous callers (401)")

    status, headers, _ = get(f"{api}/health", {"Origin": "https://evil.example"})
    check(
        headers.get("access-control-allow-origin") not in ("*", "https://evil.example"),
        "CORS does not allow an unknown origin",
    )

    if production:
        status, _, _ = get(f"{api}/docs")
        check(status == 404, "interactive API docs are disabled in production")


def smoke_web(web: str) -> None:
    print(f"Web {web}")
    status, headers, body = get(web)
    check(status == 200 and b"/_expo/static/js/" in body, "index.html references the app bundle")
    check_headers(headers, WEB_HEADERS, "web")
    status, _, _ = get(f"{web}/some/deep/link")
    check(status == 200, "SPA deep links rewrite to index.html")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--web")
    ap.add_argument("--expect-commit")
    ap.add_argument("--wait", type=int, default=900)
    ap.add_argument("--production", action="store_true")
    args = ap.parse_args()
    api = args.api.rstrip("/")
    if args.expect_commit:
        wait_for_commit(api, args.expect_commit, args.wait)
    smoke_api(api, args.production)
    if args.web:
        smoke_web(args.web.rstrip("/"))
    print(f"\n{len(failures)} failure(s)" if failures else "\nall smoke checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
