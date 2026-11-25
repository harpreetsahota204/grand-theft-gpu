"""Blinding primitives: signed A/B session tokens, HTML asset shims, and CDN URLs.

Used by `arena.app` at request time and tested directly by `tests/test_arena.py`.
Stays pure Python stdlib so blinding logic works and tests cleanly without
requiring web-framework dependencies.

Main entry points:
- `new_session`, `sign_session`, `verify_session`: counterbalanced A/B assignment
- `inject_slot_shim`: rewrites a Vite `index.html` so root-relative `/assets/`
  fetches route cleanly to `/play/{slot}/assets/` inside a blind iframe, and
  adds the input logger (`build_input_logger_script`)
- `shared_asset_cdn_url`: builds a pinned Hugging Face dataset URL for shared
  `assets/gt-gpu/` files
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Literal, TypedDict
from urllib.parse import quote

Slot = Literal["a", "b"]

# Matches root-relative `/assets/...` attributes in Vite's generated index.html.
_HTML_ASSET_ATTR_RE: re.Pattern[str] = re.compile(
    r"""(\b(?:src|href)\s*=\s*["'])(/assets/)""",
    re.IGNORECASE,
)

# Shared dataset asset prefix identical across both contenders.
SHARED_ASSET_PREFIX: str = "/assets/gt-gpu/"


class SessionPayload(TypedDict):
    """Data embedded inside a visitor's signed HttpOnly arena cookie.

    Attributes:
        sid: random 128-bit hex session identifier (used as primary key for votes)
        order: two opaque build IDs `[build_for_a, build_for_b]`; never contains
            contender or model names
    """

    sid: str
    order: list[str]


def new_session(build_ids: tuple[str, str]) -> SessionPayload:
    """Creates a fresh blind session with 50/50 counterbalanced A/B build order.

    Args:
        build_ids: pair of two distinct opaque build identifiers from manifest.json

    Returns:
        a new `SessionPayload` with a cryptographically random session ID and
        unbiased slot assignment

    Raises:
        ValueError: if the two build IDs are empty or identical
    """
    first, second = build_ids
    if not first or not second or first == second:
        raise ValueError("build_ids must contain two distinct non-empty IDs")

    # Coin flip via OS CSPRNG so order bias cancels out across visitors.
    order = [first, second] if secrets.randbelow(2) == 0 else [second, first]
    return {"sid": secrets.token_hex(16), "order": order}


def _sign_body(body: str, secret: str) -> str:
    """Computes the unpadded URL-safe base64 HMAC-SHA256 signature for `body`."""
    mac = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def sign_session(payload: SessionPayload, secret: str) -> str:
    """Serializes and HMAC-SHA256 signs a session payload into a cookie token.

    Args:
        payload: session dict (`sid` and two-element opaque `order`)
        secret: server-side signing key

    Returns:
        URL-safe `<base64_payload>.<base64_mac>` token string
    """
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{body}.{_sign_body(body, secret)}"


def verify_session(
    token: str | None,
    secret: str,
    valid_build_ids: set[str],
) -> SessionPayload | None:
    """Validates a signed session cookie and checks its build IDs against manifest.

    Args:
        token: raw cookie value, or None if missing
        secret: server-side signing key
        valid_build_ids: set of opaque build IDs currently served by the arena

    Returns:
        decoded `SessionPayload` when signature and build IDs are valid, else None
    """
    if not token:
        return None
    body, sep, sig = token.partition(".")
    if not sep or not body or not sig:
        return None

    # Verify HMAC in constant time before decoding untrusted JSON.
    if not hmac.compare_digest(sig, _sign_body(body, secret)):
        return None

    # Restore stripped base64 padding before decoding.
    padded = body + "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    sid = data.get("sid")
    order = data.get("order")
    if (
        not isinstance(sid, str)
        or len(sid) < 16
        or not isinstance(order, list)
        or len(order) != 2
        or set(order) != valid_build_ids
    ):
        return None
    return {"sid": sid, "order": [str(order[0]), str(order[1])]}


def build_slot_shim_script(asset_prefix: str) -> str:
    """Returns a tiny inline script that routes root-relative `/assets/` fetches to a slot.

    Built Vite Three.js games fetch `/assets/models/...` and `/assets/gt-gpu/...`
    via `fetch()`, `XMLHttpRequest`, and `Image` (`AudioLoader` uses `fetch`).
    Rewriting non-shared `/assets/...` paths to `asset_prefix` (for example
    `/play/a/<token>/assets/`) lets both games run unmodified inside cross-site
    iframes (like huggingface.co -> *.hf.space) without relying on cookies.

    Args:
        asset_prefix: URL prefix ending in `/assets/` for this session's blind slot

    Returns:
        an inline `<script>` tag to inject at the top of `<head>`
    """
    # Keep `/assets/gt-gpu/` untouched so shared assets hit the shared route/CDN once.
    return (
        "<script>(function(){"
        f'var P="{asset_prefix}",S="{SHARED_ASSET_PREFIX}";'
        "function rw(u){"
        'if(typeof u!=="string")return u;'
        'if(u.startsWith("/assets/")&&!u.startsWith(S))return P+u.slice(8);'
        "return u;}"
        "var of=window.fetch;"
        "if(of){window.fetch=function(i,n){"
        'if(typeof i==="string")return of.call(this,rw(i),n);'
        'if(i&&typeof i==="object"&&typeof i.url==="string"){'
        "var U=new URL(i.url,location.href),r=rw(U.pathname);"
        "if(U.origin===location.origin&&r!==U.pathname)"
        "return of.call(this,new Request(r+U.search+U.hash,i),n);"
        "}return of.call(this,i,n);};}"
        "var xo=XMLHttpRequest.prototype.open;"
        "XMLHttpRequest.prototype.open=function(m,u){"
        "var a=Array.prototype.slice.call(arguments);a[1]=rw(u);return xo.apply(this,a);};"
        "var id=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');"
        "if(id&&id.set){Object.defineProperty(HTMLImageElement.prototype,'src',{"
        "get:id.get,set:function(v){return id.set.call(this,rw(v));},configurable:true});}"
        "})();</script>"
    )


def build_input_logger_script(slot: Slot, token: str = "") -> str:
    """Returns an inline script that logs the player's inputs and posts them to `/api/events`.

    Records key down/up by physical key (`KeyboardEvent.code`, e.g. `KeyW`, never the
    typed character), mouse button down/up, pointer lock, focus and tab visibility,
    each as `[ms_since_page_load, kind, code]`. A `start` event carries the epoch ms
    so batches line up across slots. Batches flush every 5 s and on page exit (via
    `sendBeacon`). Both builds get this identical script, so logging stays fair.

    Args:
        slot: blind slot ("a" or "b") serving this document
        token: signed session token (already verified server-side, so URL-safe);
            empty falls back to the session cookie

    Returns:
        an inline `<script>` tag to inject right after the asset shim
    """
    return (
        "<script>(function(){"
        f'var T="{token}",L="{slot}",Q=[],F=window.fetch;'
        'function ev(k,c){Q.push([Math.round(performance.now()),k,c||""]);'
        "if(Q.length>5000)Q.shift();if(Q.length>=900)fl(0);}"
        "function fl(b){if(!Q.length)return;"
        "var p=JSON.stringify({token:T||null,slot:L,events:Q.splice(0,1000)});"
        'if(b&&navigator.sendBeacon&&navigator.sendBeacon("/api/events",'
        'new Blob([p],{type:"application/json"})))return;'
        'try{F.call(window,"/api/events",{method:"POST",credentials:"same-origin",'
        'headers:{"Content-Type":"application/json"},body:p,keepalive:true})'
        ".catch(function(){});}catch(e){}}"
        'ev("start",String(Date.now()));'
        'addEventListener("keydown",function(e){if(!e.repeat)ev("kd",e.code);},true);'
        'addEventListener("keyup",function(e){ev("ku",e.code);},true);'
        'addEventListener("mousedown",function(e){ev("md",String(e.button));},true);'
        'addEventListener("mouseup",function(e){ev("mu",String(e.button));},true);'
        'addEventListener("focus",function(){ev("focus");});'
        'addEventListener("blur",function(){ev("blur");});'
        'document.addEventListener("pointerlockchange",function(){'
        'ev(document.pointerLockElement?"lock":"unlock");});'
        'document.addEventListener("visibilitychange",function(){'
        'ev(document.visibilityState==="hidden"?"hidden":"visible");'
        'if(document.visibilityState==="hidden")fl(1);});'
        'addEventListener("pagehide",function(){ev("exit");fl(1);});'
        "setInterval(function(){fl(0);},5000);"
        "})();</script>"
    )


def inject_slot_shim(html: str, slot: Slot, token: str = "") -> str:
    """Rewrites static `/assets/` links in a build's `index.html` and injects the fetch shim.

    Args:
        html: raw `index.html` text from a contender's Vite `dist/` directory
        slot: blind slot ("a" or "b") serving this document
        token: optional signed session token embedded in the route path so
            asset requests stay bound to the same blind assignment without cookies

    Returns:
        transformed HTML ready to render inside the blind arena iframe
    """
    asset_prefix = f"/s/{token}/play/{slot}/assets/" if token else f"/play/{slot}/assets/"
    # Rewrite static <script src="/assets/..."> and <link href="/assets/..."> tags.
    rewritten = _HTML_ASSET_ATTR_RE.sub(rf"\1{asset_prefix}", html)
    shim = build_slot_shim_script(asset_prefix) + build_input_logger_script(slot, token)

    # Insert shim immediately after <head ...> so it executes before module scripts.
    head_match = re.search(r"<head\b[^>]*>", rewritten, re.IGNORECASE)
    if head_match:
        idx = head_match.end()
        return rewritten[:idx] + "\n" + shim + rewritten[idx:]
    return shim + "\n" + rewritten


def shared_asset_cdn_url(rel_path: str, hf_repo: str, hf_revision: str) -> str:
    """Constructs the pinned Hugging Face dataset resolve URL for one shared asset.

    Args:
        rel_path: path relative to `assets/gt-gpu/` (e.g. `sf-city/sf-city.glb`)
        hf_repo: Hugging Face dataset repository ID (`namespace/name`)
        hf_revision: pinned git commit SHA on the dataset repo

    Returns:
        direct HTTPS URL that streams the asset from Hugging Face Hub CDN
    """
    clean = rel_path.lstrip("/")
    encoded = quote(clean, safe="/")
    return f"https://huggingface.co/datasets/{hf_repo}/resolve/{hf_revision}/{encoded}"
