"""Access token for a viewer shared on a network, and a same-origin check for writes.

With a token, every request needs it, except the built JS and CSS under
`/assets/`, which hold no data (sandboxed figure frames load them without
cookies). Opening any page with `?token=<token>` signs the browser in with a
cookie and redirects to the same page without the token. Scripts can send
`Authorization: token <token>` instead. Without a cookie, pages show a sign-in
form and API calls get a 401.

Writes (`POST`, `PUT`, `PATCH`, `DELETE`) from a browser must come from the
viewer's own pages: an `Origin` (or `Referer`) of another site is refused, so
another website cannot make your browser change runs or artifacts.
"""

from __future__ import annotations

import hashlib
import hmac
import html
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from .._meta import NAME

Scope = dict[str, Any]
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def cookie_name(token: str) -> str:
    """Return the cookie name for `token`; viewers with different tokens on one host don't clash."""
    return f"{NAME}-auth-" + hashlib.sha256(token.encode()).hexdigest()[:8]


def cookie_value(token: str) -> str:
    """Return the cookie value that proves the token was entered (not the token itself)."""
    return hashlib.sha256(f"{NAME}:{token}".encode()).hexdigest()


def _eq(a: str, b: str) -> bool:
    """Compare two strings in constant time (any characters)."""
    return hmac.compare_digest(a.encode(), b.encode())


def _headers(scope: Scope) -> dict[str, str]:
    """Return the request headers, lowercased, last value winning."""
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


def _cookies(header: str) -> dict[str, str]:
    """Parse a `Cookie` header."""
    out = {}

    for part in header.split(";"):
        k, _, v = part.strip().partition("=")

        if k:
            out[k] = v

    return out


def _same_origin(headers: dict[str, str]) -> bool:
    """Return False when `Origin` (or else `Referer`) names a host other than `Host`."""
    source = headers.get("origin") or headers.get("referer")

    if not source or source == "null":
        return source is None  # no header: not a browser form or fetch from another site

    netloc = urlsplit(source).netloc
    return netloc in (headers.get("host", ""), headers.get("x-forwarded-host", ""))


class Guard:
    """ASGI middleware: the access token (if any) and the same-origin check for writes.

    Args:
        app: The wrapped app.
        token: The access token, or None to check only the origin of writes.
    """

    def __init__(self, app: Any, token: str | None = None) -> None:
        self.app = app
        self.token = token
        self.cookie = cookie_name(token) if token else ""
        self.value = cookie_value(token) if token else ""

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        """Pass the request on, or answer it with a redirect, sign-in page or error."""

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        method = scope["method"]
        by_header = False

        if self.token and not scope["path"].startswith("/assets/"):
            auth = headers.get("authorization", "")
            by_header = auth.startswith("token ") and _eq(auth[6:], self.token)
            signed_in = by_header or _eq(
                _cookies(headers.get("cookie", "")).get(self.cookie, ""), self.value
            )

            if scope["path"] == "/login" and method == "POST":
                await self._login(scope, receive, send)
                return

            query = dict(parse_qsl(scope.get("query_string", b"").decode("latin-1")))

            if method == "GET" and "token" in query:
                if _eq(query["token"], self.token):
                    query.pop("token")
                    rest = urlencode(query)
                    await self._redirect(send, scope["path"] + (f"?{rest}" if rest else ""))
                else:
                    await self._page(send, scope["path"], "That token is not right.")

                return

            if not signed_in:
                if method == "GET" and "text/html" in headers.get("accept", ""):
                    await self._page(send, scope["path"] + _qs(scope), "")
                else:
                    await _plain(send, 401, "a token is needed: open the link nuboard up printed")

                return

        if method in _UNSAFE and not by_header and not _same_origin(headers):
            await _plain(send, 403, "refused: the request came from another site")
            return

        await self.app(scope, receive, send)

    async def _login(self, scope: Scope, receive: Any, send: Any) -> None:
        """Handle the sign-in form: set the cookie and go to `next`, or show the form again."""
        body = b""

        while True:
            msg = await receive()
            body += msg.get("body", b"")

            if not msg.get("more_body") or len(body) > 8192:
                break

        form = dict(parse_qsl(body.decode("utf-8", "replace")))
        target = form.get("next") or "/"

        if not target.startswith("/") or target.startswith("//") or "\\" in target:
            target = "/"

        if _eq(form.get("token", "").strip(), self.token or ""):
            await self._redirect(send, target)
        else:
            await self._page(send, target, "That token is not right.")

    async def _redirect(self, send: Any, location: str) -> None:
        """Answer with a 303 to `location` that also sets the sign-in cookie."""
        cookie = f"{self.cookie}={self.value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
        await send(
            {
                "type": "http.response.start",
                "status": 303,
                "headers": [
                    (b"location", location.encode("latin-1", "replace")),
                    (b"set-cookie", cookie.encode()),
                    (b"cache-control", b"no-store"),
                    (b"content-length", b"0"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def _page(self, send: Any, target: str, error: str) -> None:
        """Answer with the sign-in form (401)."""
        body = _LOGIN.format(
            name=html.escape(NAME),
            next=html.escape(target, quote=True),
            error=f'<p class="err">{html.escape(error)}</p>' if error else "",
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _qs(scope: Scope) -> str:
    """Return the request's query string with its `?`, or an empty string."""
    q = scope.get("query_string", b"").decode("latin-1")
    return f"?{q}" if q else ""


async def _plain(send: Any, status: int, text: str) -> None:
    """Answer with a plain-text error."""
    body = text.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


_LOGIN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · {name}</title>
<style>
  :root {{ color-scheme: light dark; --bg: #eef1f5; --panel: #fff; --text: #16191d;
    --muted: #5b6573; --border: #d7dce3; --accent: #0b6fb3; --err: #b3261e; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #0f1216; --panel: #181c22;
    --text: #e6eaf0; --muted: #98a2b3; --border: #2a313b; --accent: #4aa8e8; --err: #f28b82; }} }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg);
    color: var(--text); font: 15px/1.5 system-ui, sans-serif; }}
  form {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 28px; width: min(360px, calc(100vw - 32px)); box-sizing: border-box; }}
  h1 {{ font-size: 19px; margin: 0 0 6px; }}
  p {{ color: var(--muted); margin: 0 0 16px; font-size: 14px; }}
  input {{ width: 100%; box-sizing: border-box; padding: 9px 11px; border-radius: 8px;
    border: 1px solid var(--border); background: transparent; color: inherit;
    font: 14px ui-monospace, Menlo, monospace; }}
  button {{ margin-top: 12px; width: 100%; padding: 9px; border: 0; border-radius: 8px;
    background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }}
  .err {{ color: var(--err); margin: 10px 0 0; }}
</style></head>
<body><form method="post" action="/login">
<h1>Sign in to {name}</h1>
<p>Paste the token that <code>{name} up</code> printed, or open the link it printed.</p>
<input name="token" type="password" autocomplete="current-password" aria-label="Token"
  autofocus required>
<input type="hidden" name="next" value="{next}">
{error}
<button type="submit">Sign in</button>
</form></body></html>
"""
