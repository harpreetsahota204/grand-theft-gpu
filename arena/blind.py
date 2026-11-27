"""Blinding primitives: signed A/B session tokens, HTML asset shims, and CDN URLs.

Used by `arena.app` at request time and tested directly by `tests/test_arena.py`.
Stays pure Python stdlib so blinding logic works and tests cleanly without
requiring web-framework dependencies.

Main entry points:
- `new_session`, `sign_session`, `verify_session`: counterbalanced A/B assignment
  that is never readable from the token itself (`slot_order`)
- `inject_slot_shim`: rewrites a Vite `index.html` so root-relative `/assets/`
  fetches route cleanly to `/play/{slot}/assets/` inside a blind iframe, and
  adds the input and snapshot logger (`build_input_logger_script`)
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
    """A visitor's blind session, as resolved server-side from their signed token.

    Only `sid` travels in the token. `order` is derived on the server from the sid and
    the signing secret, so a visitor who decodes their token learns nothing about which
    build sits in which slot.

    Attributes:
        sid: random 128-bit hex session identifier (used as primary key for votes)
        order: two opaque build IDs `[build_for_a, build_for_b]`; never contains
            contender or model names
    """

    sid: str
    order: list[str]


def _check_pair(build_ids: tuple[str, str] | set[str]) -> list[str]:
    """Returns the two build IDs sorted, or raises if they aren't two distinct non-empty IDs."""
    ids = sorted(build_ids)
    if len(ids) != 2 or not ids[0] or not ids[1] or ids[0] == ids[1]:
        raise ValueError("build_ids must contain two distinct non-empty IDs")
    return ids


def slot_order(sid: str, build_ids: tuple[str, str] | set[str], secret: str) -> list[str]:
    """Derives a session's `[build_for_a, build_for_b]` from its sid with a keyed hash.

    A keyed coin flip is 50/50 across random sids (counterbalanced) and stable for one
    sid, yet nobody without the secret can predict it, so a reveal one visitor shares
    says nothing about anyone else's slots.

    Args:
        sid: session ID
        build_ids: the two opaque build IDs currently served
        secret: server-side signing key

    Returns:
        the two build IDs in slot order (A first)
    """
    ids = _check_pair(build_ids)
    flip = hmac.new(secret.encode("utf-8"), f"order:{sid}".encode(), hashlib.sha256).digest()
    return ids if flip[0] & 1 == 0 else [ids[1], ids[0]]


def new_session(build_ids: tuple[str, str], secret: str) -> SessionPayload:
    """Creates a fresh blind session with a counterbalanced, secret A/B build order.

    Args:
        build_ids: pair of two distinct opaque build identifiers from manifest.json
        secret: server-side signing key (decides the hidden slot order)

    Returns:
        a new `SessionPayload` with a cryptographically random session ID

    Raises:
        ValueError: if the two build IDs are empty or identical
    """
    sid = secrets.token_hex(16)
    return {"sid": sid, "order": slot_order(sid, build_ids, secret)}


def _sign_body(body: str, secret: str, build_ids: list[str]) -> str:
    """Computes the unpadded URL-safe base64 HMAC-SHA256 signature for `body`.

    The served build pair is part of the signed message, so a token minted for one
    race stops verifying once the Space switches to another race's builds.
    """
    message = f"{body}|{','.join(build_ids)}".encode("ascii")
    mac = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def sign_session(payload: SessionPayload, secret: str) -> str:
    """Signs a session into a cookie token that carries only its sid.

    Args:
        payload: session dict (`sid` and the derived `order`)
        secret: server-side signing key

    Returns:
        URL-safe `<base64_payload>.<base64_mac>` token string
    """
    raw = json.dumps({"sid": payload["sid"]}, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{body}.{_sign_body(body, secret, _check_pair(set(payload['order'])))}"


def verify_session(
    token: str | None,
    secret: str,
    valid_build_ids: set[str],
) -> SessionPayload | None:
    """Validates a signed session token for the build pair currently served.

    Args:
        token: raw cookie value, or None if missing
        secret: server-side signing key
        valid_build_ids: set of opaque build IDs currently served by the arena

    Returns:
        the `SessionPayload` (with its derived slot order) when the signature is valid
        for this build pair, else None; tokens in the old format that spelled out the
        order are rejected so those visitors get a fresh session
    """
    if not token:
        return None
    body, sep, sig = token.partition(".")
    if not sep or not body or not sig:
        return None

    try:
        ids = _check_pair(valid_build_ids)
        expected = _sign_body(body, secret, ids)
    except (ValueError, UnicodeEncodeError):
        return None
    # Verify HMAC in constant time before decoding untrusted JSON.
    if not hmac.compare_digest(sig, expected):
        return None

    # Restore stripped base64 padding before decoding.
    padded = body + "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict) or set(data) != {"sid"}:
        return None
    sid = data["sid"]
    if not isinstance(sid, str) or len(sid) < 16:
        return None
    return {"sid": sid, "order": slot_order(sid, ids, secret)}


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


def build_input_logger_script(
    slot: Slot,
    token: str = "",
    snapshot_ms: int = 200,
    snapshot_width: int = 320,
    max_frames: int = 36_000,
) -> str:
    """Returns an inline script that logs inputs and gameplay snapshots for one build iframe.

    Inputs go to `/api/events` as `[ms_since_page_load, kind, code]` triples: key
    down/up by physical key (`KeyboardEvent.code`, e.g. `KeyW`, never the typed
    character), mouse button down/up (code `button,x,y` with the pointer position as a
    0-1 fraction of the viewport), summed mouse movement every 100 ms (`mv`, code
    `dx,dy`, which is how pointer-locked games aim), pointer lock, focus and tab
    visibility. Every batch carries `epoch`, the page's navigation start in epoch ms,
    so `epoch + ms` is an absolute time that survives iframe reloads, and `auto`, true
    when the browser is automated (`navigator.webdriver`), so test runs can be filtered.

    Snapshots go to `/api/frame`: a JPEG of the game's largest canvas, `snapshot_width`
    px wide, every `snapshot_ms` while the tab is visible, on the same clock as the
    inputs. The cadence holds steady (a late capture doesn't push the next one back),
    and the copy canvas is read-optimised, since every capture reads it. The copy is taken
    right after the game's own `requestAnimationFrame` callback, the only moment a
    WebGL canvas without `preserveDrawingBuffer` still holds the frame; a blank copy is
    retried for up to 30 frames so a mid-frame read doesn't store a black image.

    Both builds get this identical script, so logging stays fair.

    Args:
        slot: blind slot ("a" or "b") serving this document
        token: signed session token (already verified server-side, so URL-safe);
            empty falls back to the session cookie
        snapshot_ms: milliseconds between snapshots
        snapshot_width: snapshot width in pixels (never wider than the game's canvas)
        max_frames: snapshots one page load may send (the server enforces its own cap)

    Returns:
        an inline `<script>` tag to inject right after the asset shim
    """
    period, width, cap = int(snapshot_ms), int(snapshot_width), int(max_frames)
    return (
        "<script>(function(){"
        f'var T="{token}",L="{slot}",Q=[],F=window.fetch,'
        f"P={period},W={width},MF={cap},A=navigator.webdriver===true,"
        "E=Math.round(Date.now()-performance.now());"
        'function ev(k,c){Q.push([Math.round(performance.now()),k,c||""]);'
        "if(Q.length>5000)Q.shift();if(Q.length>=900)fl(0);}"
        "function fl(b){if(!Q.length)return;"
        "var p=JSON.stringify({token:T||null,slot:L,epoch:E,auto:A,events:Q.splice(0,1000)});"
        'if(b&&navigator.sendBeacon&&navigator.sendBeacon("/api/events",'
        'new Blob([p],{type:"application/json"})))return;'
        'try{F.call(window,"/api/events",{method:"POST",credentials:"same-origin",'
        'headers:{"Content-Type":"application/json"},body:p,keepalive:true})'
        ".catch(function(){});}catch(e){}}"
        "function pos(e){return e.button+','+(e.clientX/(innerWidth||1)).toFixed(4)+','"
        "+(e.clientY/(innerHeight||1)).toFixed(4);}"
        'ev("start",String(Date.now()));'
        'addEventListener("keydown",function(e){if(!e.repeat)ev("kd",e.code);},true);'
        'addEventListener("keyup",function(e){ev("ku",e.code);},true);'
        # A game that calls preventDefault() on mousedown also cancels the browser's
        # click-to-focus, so inside the arena iframe its keys would go to the parent page.
        # Focusing the frame on every press makes it behave as it does at top level.
        'addEventListener("mousedown",function(e){ev("md",pos(e));'
        "try{window.focus();}catch(x){}},true);"
        'addEventListener("mouseup",function(e){ev("mu",pos(e));},true);'
        "var mx=0,my=0;"
        'addEventListener("mousemove",function(e){mx+=e.movementX||0;my+=e.movementY||0;},true);'
        "setInterval(function(){var rx=Math.round(mx),ry=Math.round(my);"
        'if(rx||ry){ev("mv",rx+","+ry);mx-=rx;my-=ry;}},100);'
        'addEventListener("focus",function(){ev("focus");});'
        'addEventListener("blur",function(){ev("blur");});'
        'document.addEventListener("pointerlockchange",function(){'
        'ev(document.pointerLockElement?"lock":"unlock");});'
        'document.addEventListener("visibilitychange",function(){'
        'ev(document.visibilityState==="hidden"?"hidden":"visible");'
        'if(document.visibilityState==="hidden")fl(1);});'
        'addEventListener("pagehide",function(){ev("exit");fl(1);});'
        "setInterval(function(){fl(0);},5000);"
        # Gameplay snapshots, taken right after the game's own frame callback.
        'var cv=document.createElement("canvas"),cx=cv.getContext("2d",{willReadFrequently:true}),'
        "due=performance.now()+3000,tries=0,busy=0,NF=0;"
        "function big(){var b=null,a=0,l=document.getElementsByTagName('canvas');"
        "for(var i=0;i<l.length;i++){var r=l[i].width*l[i].height;if(r>a){a=r;b=l[i];}}return b;}"
        "function snap(){var n=performance.now();"
        'if(busy||n<due||NF>=MF||document.visibilityState!=="visible")return;'
        "var c=big();if(!c||!c.width||!c.height){due=n+1000;return;}"
        "var w=Math.min(W,c.width),h=Math.max(1,Math.round(c.height*w/c.width));"
        "if(cv.width!==w)cv.width=w;if(cv.height!==h)cv.height=h;"
        "try{cx.drawImage(c,0,0,w,h);var d=cx.getImageData(0,0,w,h).data,s=0;"
        "for(var i=0;i<d.length;i+=4000)s+=d[i]+d[i+1]+d[i+2];"
        "if(!s){if(++tries<30)return;tries=0;due=n+P;return;}}catch(e){due=Infinity;return;}"
        "tries=0;due=n-due>P?n+P:due+P;busy=1;var t=Math.round(n);"
        "cv.toBlob(function(b){busy=0;if(!b)return;NF++;"
        'try{F.call(window,"/api/frame?token="+encodeURIComponent(T)+"&slot="+L+"&t="+t'
        '+"&epoch="+E+"&w="+w+"&h="+h+(A?"&auto=1":""),{method:"POST",credentials:"same-origin",'
        'headers:{"Content-Type":"image/jpeg"},body:b}).catch(function(){});}catch(e){}'
        '},"image/jpeg",0.7);}'
        "var R=window.requestAnimationFrame;"
        "if(R)window.requestAnimationFrame=function(cb){"
        "return R.call(window,function(ts){cb(ts);snap();});};"
        "})();</script>"
    )


def inject_slot_shim(
    html: str,
    slot: Slot,
    token: str = "",
    snapshot_ms: int = 200,
    snapshot_width: int = 320,
    max_frames: int = 36_000,
) -> str:
    """Rewrites static `/assets/` links in a build's `index.html` and injects the fetch shim.

    Args:
        html: raw `index.html` text from a contender's Vite `dist/` directory
        slot: blind slot ("a" or "b") serving this document
        token: optional signed session token embedded in the route path so
            asset requests stay bound to the same blind assignment without cookies
        snapshot_ms: milliseconds between gameplay snapshots
        snapshot_width: snapshot width in pixels
        max_frames: snapshots one page load may send

    Returns:
        transformed HTML ready to render inside the blind arena iframe
    """
    asset_prefix = f"/s/{token}/play/{slot}/assets/" if token else f"/play/{slot}/assets/"
    # Rewrite static <script src="/assets/..."> and <link href="/assets/..."> tags.
    rewritten = _HTML_ASSET_ATTR_RE.sub(rf"\1{asset_prefix}", html)
    logger_script = build_input_logger_script(
        slot, token, snapshot_ms=snapshot_ms, snapshot_width=snapshot_width, max_frames=max_frames
    )
    shim = build_slot_shim_script(asset_prefix) + logger_script

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
