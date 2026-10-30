"""OPTIONAL enrichment services: Jina AI Reader, Hunter.io, ZeroBounce, Apify, Apollo, Meta Instagram.

HARD RULES (defensive programming):
  * Every public helper has its OWN try/except and NEVER raises.
  * Missing/empty/invalid key, 4xx, 5xx, timeout, bad JSON, rate limit -> the helper logs ONE silent line
    ("[Enrichment Skipped] <Service> API unavailable (...)") and returns None. The caller keeps the base lead unchanged.
  * 429 (rate limit) or 401/402/403 (bad key / no credit) trips a per-run circuit breaker: every later lead skips that
    service INSTANTLY (no waiting, no retries). 3 consecutive failures also trip it.
  * Keys are read with os.getenv(KEY, "") only. No os.environ[...] indexing anywhere.
"""
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone

import requests

import enrich as E

# ---- feature flags (safe: computed with os.getenv(..., "")) ---------------------------------------------
# Jina Reader works keyless (lower rate limit), so it is ON unless you set USE_JINA=false.
ENRICH_WEBSITES = os.getenv("USE_JINA", "true").strip().lower() not in ("0", "false", "no", "off")
# Verification turns on only when at least one verifier key exists. Otherwise raw leads are treated as valid.
VERIFY_EMAILS = bool(os.getenv("HUNTER_API_KEY", "").strip() or os.getenv("ZEROBOUNCE_API_KEY", "").strip())

STATS = Counter()      # service -> number of times it was skipped/failed this run
OK = Counter()         # service -> successful calls
_WARNED, _OFF, _FAILS = set(), {}, Counter()
NAMES = {"jina": "Jina", "hunter": "Hunter", "zerobounce": "ZeroBounce", "apify": "Apify", "apollo": "Apollo", "meta_ig": "Instagram (Meta)"}


def key(name):
    return os.getenv(name, "").strip()


def _skip(service, why):
    STATS[service] += 1
    if service not in _WARNED:
        _WARNED.add(service)
        print(f"[Enrichment Skipped] {NAMES.get(service, service)} API unavailable ({why})")


def _trip(service, why):
    _OFF[service] = why
    _skip(service, why)


def available(service):
    return service not in _OFF


def _call(service, method, url, **kw):
    """Single guarded HTTP call. Returns a Response (status < 400) or None. Never raises."""
    if not available(service):
        STATS[service] += 1
        return None
    try:
        r = requests.request(method, url, timeout=kw.pop("timeout", 20), **kw)
        code = int(getattr(r, "status_code", 0) or 0)
    except Exception as e:
        _FAILS[service] += 1
        _skip(service, type(e).__name__)
        if _FAILS[service] >= 3:
            _trip(service, "3 consecutive failures")
        return None
    if code == 429:
        _trip(service, "rate limited (429)")
        return None
    if code in (401, 402, 403):
        _trip(service, f"{code}: key invalid or no credit")
        return None
    if code >= 400:
        _FAILS[service] += 1
        _skip(service, f"HTTP {code}")
        if _FAILS[service] >= 3:
            _trip(service, "3 consecutive failures")
        return None
    _FAILS[service] = 0
    OK[service] += 1
    return r


def _json(r):
    try:
        return r.json()
    except Exception:
        return None


# ---- Jina AI Reader: deep website context (works on JS-heavy sites) -------------------------------------
def jina_read(url):
    """Returns {'emails': [...], 'socials': {...}, 'summary': str} or None."""
    try:
        if not ENRICH_WEBSITES or not url:
            return None
        headers = {"Accept": "text/plain", "X-Return-Format": "markdown"}
        if key("JINA_API_KEY"):
            headers["Authorization"] = "Bearer " + key("JINA_API_KEY")
        r = _call("jina", "GET", "https://r.jina.ai/" + url, headers=headers, timeout=30)
        if r is None:
            return None
        text = (r.text or "")[:200000]
        if len(text) < 50:
            return None
        clean = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
        clean = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", clean)
        clean = re.sub(r"[#*_>`|]+", " ", clean)
        clean = " ".join(clean.split())
        return {"emails": E.emails_in(text), "socials": E.socials_in(text), "summary": clean[:350]}
    except Exception as e:
        _skip("jina", type(e).__name__)
        return None


# ---- Hunter.io: email finder + verifier ---------------------------------------------------------------------
def hunter_find(domain):
    """Returns {'emails': [...], 'org': str} or None."""
    try:
        if not key("HUNTER_API_KEY") or not domain:
            return None
        r = _call("hunter", "GET", "https://api.hunter.io/v2/domain-search",
                  params={"domain": domain, "api_key": key("HUNTER_API_KEY"), "limit": 5})
        d = (_json(r) or {}).get("data") if r is not None else None
        if not d:
            return None
        es = [x["value"].lower() for x in d.get("emails", []) if x.get("value") and (x.get("confidence") or 0) >= 70]
        return {"emails": es[:5], "org": d.get("organization") or ""}
    except Exception as e:
        _skip("hunter", type(e).__name__)
        return None


def _hunter_verify(email):
    if not key("HUNTER_API_KEY"):
        return None
    r = _call("hunter", "GET", "https://api.hunter.io/v2/email-verifier", params={"email": email, "api_key": key("HUNTER_API_KEY")})
    d = (_json(r) or {}).get("data") if r is not None else None
    s = (d or {}).get("status", "")
    return {"valid": "valid", "accept_all": "risky", "invalid": "invalid", "disposable": "invalid"}.get(s)


def _zerobounce_verify(email):
    if not key("ZEROBOUNCE_API_KEY"):
        return None
    r = _call("zerobounce", "GET", "https://api.zerobounce.net/v2/validate", params={"api_key": key("ZEROBOUNCE_API_KEY"), "email": email})
    s = ((_json(r) or {}).get("status") or "").lower() if r is not None else ""
    return {"valid": "valid", "catch-all": "risky", "invalid": "invalid", "spamtrap": "invalid", "abuse": "invalid",
            "do_not_mail": "invalid"}.get(s)


_MX = {}


def mx_check(email):
    """FREE local check (no key): can this email's domain receive mail at all?
    'mx-ok' | 'invalid' (no mail server / domain does not exist) | None (cannot tell, e.g. dnspython missing)."""
    try:
        dom = email.rsplit("@", 1)[1].lower()
        if dom in _MX:
            return _MX[dom]
        try:
            import dns.resolver
            import dns.exception
        except Exception:
            return None
        try:
            res = dns.resolver.resolve(dom, "MX", lifetime=5)
            out = "mx-ok" if len(res) else "invalid"
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            try:                                   # RFC: a plain A record also accepts mail
                dns.resolver.resolve(dom, "A", lifetime=5)
                out = "mx-ok"
            except Exception:
                out = "invalid"
        except dns.exception.DNSException:
            out = None                             # timeout / resolver trouble: do not punish the lead
        _MX[dom] = out
        return out
    except Exception as e:
        _skip("mxcheck", type(e).__name__)
        return None


def verify_email(email):
    """'valid' | 'risky' | 'invalid' | 'mx-ok' | None. None means unknown: the caller keeps the email.
    Order: ZeroBounce -> Hunter (only if their keys exist and are not tripped) -> free MX check."""
    try:
        if not email:
            return None
        if VERIFY_EMAILS:
            for fn in (_zerobounce_verify, _hunter_verify):
                v = fn(email)
                if v:
                    return v
        if os.getenv("USE_MX_CHECK", "true").strip().lower() not in ("0", "false", "no", "off"):
            return mx_check(email)
        return None
    except Exception as e:
        _skip("verify", type(e).__name__)
        return None


# ---- Apollo: company + employee count -------------------------------------------------------------------------
def apollo_org(domain):
    """Returns (name, employees) or None."""
    try:
        if not key("APOLLO_API_KEY") or not domain:
            return None
        r = _call("apollo", "GET", "https://api.apollo.io/api/v1/organizations/enrich", params={"domain": domain},
                  headers={"X-Api-Key": key("APOLLO_API_KEY"), "accept": "application/json"})
        o = ((_json(r) or {}).get("organization") or {}) if r is not None else {}
        if not o:
            return None
        return o.get("name") or "", o.get("estimated_num_employees") or ""
    except Exception as e:
        _skip("apollo", type(e).__name__)
        return None


# ---- Instagram activity: Meta official API first, Apify as optional fallback -----------------------------
def _stats(followers, posts):
    """posts: list of (timestamp_iso, likes, comments). Returns dict or None."""
    if not followers or not posts:
        return None
    now = datetime.now(timezone.utc)
    p30, eng = 0, []
    for ts, likes, comments in posts:
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if (now - t).days < 30:
                p30 += 1
        except Exception:
            pass
        eng.append((likes or 0) + (comments or 0))
    return {"followers": int(followers), "engagement": round(sum(eng) / len(eng) / followers * 100, 2), "posts30": p30}


def ig_meta(handle):
    try:
        if not (key("IG_ACCESS_TOKEN") and key("IG_USER_ID") and handle):
            return None
        f = (f"business_discovery.username({handle})"
             "{followers_count,media.limit(12){like_count,comments_count,timestamp}}")
        r = _call("meta_ig", "GET", f"https://graph.facebook.com/{key('GRAPH_VERSION') or 'v24.0'}/{key('IG_USER_ID')}",
                  params={"fields": f, "access_token": key("IG_ACCESS_TOKEN")}, timeout=30)
        d = ((_json(r) or {}).get("business_discovery") or {}) if r is not None else {}
        media = (d.get("media") or {}).get("data", [])
        return _stats(d.get("followers_count"), [(m.get("timestamp"), m.get("like_count"), m.get("comments_count")) for m in media])
    except Exception as e:
        _skip("meta_ig", type(e).__name__)
        return None


def ig_apify(handle):
    """Optional fallback for personal/private-API-blocked profiles. Costs Apify credits. Check Apify/Instagram terms."""
    try:
        if not (key("APIFY_API_TOKEN") and handle):
            return None
        actor = (key("APIFY_IG_ACTOR") or "apify/instagram-profile-scraper").replace("/", "~")
        r = _call("apify", "POST", f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
                  params={"token": key("APIFY_API_TOKEN"), "timeout": 80}, json={"usernames": [handle]}, timeout=100)
        items = _json(r) if r is not None else None
        if not isinstance(items, list) or not items:
            return None
        it = items[0] or {}
        posts = [(p.get("timestamp"), p.get("likesCount"), p.get("commentsCount")) for p in (it.get("latestPosts") or [])]
        return _stats(it.get("followersCount"), posts)
    except Exception as e:
        _skip("apify", type(e).__name__)
        return None
