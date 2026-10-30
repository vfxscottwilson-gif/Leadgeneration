"""Finds public contact info: emails + social links from the channel description, the creator's own
website / link-in-bio page (robots.txt respected), plus optional Hunter / Apollo / Instagram lookups."""
import os
import re
import time
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests

UA = "Mozilla/5.0 (compatible; LeadResearchBot/1.0)"
MAX_BYTES = 1_500_000
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+|(?:www\.)[^\s<>\"')\]]+|"
                    r"\b(?:[a-z]{2,3}\.)?(?:instagram|linkedin|facebook|twitter|tiktok|x)\.com/[^\s<>\"')\]]+", re.I)
JUNK_EXT = ("png", "jpg", "jpeg", "gif", "webp", "svg", "js", "css", "woff", "woff2", "ico", "mp4", "pdf")
JUNK_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "domain.com", "email.com", "yoursite.com",
                "youtube.com", "google.com", "gstatic.com", "schema.org", "w3.org")
BAD_LOCAL = ("noreply", "no-reply", "donotreply", "abuse", "privacy", "postmaster", "webmaster", "mailer-daemon")
ROLE_LOCAL = ("business", "collab", "partnership", "partnerships", "sponsor", "sponsors", "hello", "hi", "contact",
              "info", "team", "inquiries", "enquiries", "work", "booking", "bookings", "mgmt", "management", "press", "reception", "admin", "enquiries", "enquiry",
              "appointments", "office", "sales", "clinic", "practice", "marketing", "manager", "reservations")
FREE_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "proton.me",
             "protonmail.com", "live.com", "msn.com", "me.com", "gmx.com")
AGGREGATORS = ("linktr.ee", "beacons.ai", "bio.link", "stan.store", "carrd.co", "lnk.bio", "linktree.com",
               "campsite.bio", "taplink.cc", "solo.to", "withkoji.com", "allmylinks.com", "komi.io", "hoo.be")
SOCIALS = {  # platform: (host regex, handle path regex)
    "Instagram": (r"(?:www\.)?instagram\.com", r"/([A-Za-z0-9._]{2,30})/?(?:\?|$)"),
    "LinkedIn": (r"(?:[a-z]{2,3}\.)?linkedin\.com", r"/((?:in|company|school)/[A-Za-z0-9\-_%.]+)/?"),
    "Facebook": (r"(?:www\.|m\.)?facebook\.com", r"/((?!sharer|share|dialog|tr\b|plugins|watch|groups/?$)[A-Za-z0-9.\-]{3,}(?:/[A-Za-z0-9.\-]+)?)/?(?:\?|$)"),
    "Twitter / X": (r"(?:www\.)?(?:twitter|x)\.com", r"/((?!intent|share|home|i/)[A-Za-z0-9_]{2,15})/?(?:\?|$)"),
    "TikTok": (r"(?:www\.)?tiktok\.com", r"/(@[A-Za-z0-9._]{2,24})/?(?:\?|$)"),
    "YouTube": (r"(?:www\.|m\.)?youtube\.com", r"/((?:@|channel/|c/|user/)[A-Za-z0-9._\-]+)/?(?:\?|$)"),
}
OTHER = {"threads.net": "Threads", "pinterest.com": "Pinterest", "snapchat.com": "Snapchat", "discord.gg": "Discord",
         "discord.com": "Discord", "patreon.com": "Patreon", "t.me": "Telegram", "twitch.tv": "Twitch",
         "substack.com": "Substack", "skool.com": "Skool", "medium.com": "Medium", "calendly.com": "Calendly"}
SKIP_WEBSITE = ("youtube.com", "youtu.be", "amzn.to", "amazon.", "bit.ly", "tinyurl.com", "geni.us", "go.", "shareasale",
                "tubebuddy", "vidiq", "epidemicsound", "artlist", "canva.com", "notion.so", "apple.com", "spotify.com",
                "google.com", "goo.gl", "ow.ly", "t.co", "rb.gy", "cutt.ly", "paypal.", "buymeacoffee", "ko-fi",
                "kit.co", "kit.com")
_robots = {}


def _host(u):
    h = (urlparse(u if "://" in u else "http://" + u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def allowed(url):
    host = urlparse(url).netloc
    rp = _robots.get(host)
    if rp is None:
        rp = RobotFileParser()
        try:
            r = requests.get(f"{urlparse(url).scheme}://{host}/robots.txt", headers={"User-Agent": UA}, timeout=(4, 6))
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[host] = rp
    return rp.can_fetch(UA, url)


def fetch(url):
    """Return page text or None. Never raises."""
    try:
        if not allowed(url):
            return None
        with requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}, timeout=(5, 10),
                          stream=True, allow_redirects=True) as r:
            if r.status_code != 200 or "text" not in r.headers.get("content-type", "text"):
                return None
            data = b""
            for chunk in r.iter_content(65536):
                data += chunk
                if len(data) > MAX_BYTES:
                    break
            return data.decode(r.encoding or "utf-8", errors="ignore")
    except Exception:
        return None


def deobfuscate(t):
    t = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", t, flags=re.I)
    t = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", t, flags=re.I)
    return t.replace("&#64;", "@").replace("%40", "@")


def emails_in(text):
    out = []
    for e in EMAIL_RE.findall(deobfuscate(text or "")):
        e = e.strip(".,;:").lower()
        local, _, dom = e.partition("@")
        if e.rsplit(".", 1)[-1] in JUNK_EXT or any(dom.endswith(j) for j in JUNK_DOMAINS):
            continue
        if any(local.startswith(b) for b in BAD_LOCAL) or re.search(r"\d{6,}", local) or e in out:
            continue
        out.append(e)
    return out


def socials_in(text, found=None):
    """Extract social profile links from text/HTML. Returns {platform: url}."""
    found = found if found is not None else {}
    for u in URL_RE.findall(text or "") + re.findall(r'href=["\']([^"\']+)', text or ""):
        u = u.rstrip(".,;)")
        if u.startswith("/") or u.startswith("#") or u.startswith("mailto") or u.startswith("tel"):
            continue
        full = u if u.startswith("http") else "https://" + u
        host, path = _host(full), urlparse(full).path + ("?" if "?" in full else "")
        for plat, (hre, pre) in SOCIALS.items():
            if re.fullmatch(hre, host) and plat not in found:
                m = re.match(pre, path if path.endswith("?") or "?" in path else path + "?") or re.match(pre, path)
                if m and m.group(1).lower() not in ("p", "reel", "reels", "explore", "stories", "accounts", "about", "login"):
                    base = {"Instagram": "https://www.instagram.com/", "LinkedIn": "https://www.linkedin.com/",
                            "Facebook": "https://www.facebook.com/", "Twitter / X": "https://x.com/",
                            "TikTok": "https://www.tiktok.com/", "YouTube": "https://www.youtube.com/"}[plat]
                    found[plat] = base + m.group(1)
        for dom, name in OTHER.items():
            if host == dom or host.endswith("." + dom):
                found.setdefault("Other:" + name, full)
    return found


def pick_website(desc, title):
    """Choose the creator's own website from the channel description (best effort)."""
    cands = []
    for m in URL_RE.finditer(desc or ""):
        u = m.group(0).rstrip(".,;)")
        if not u.startswith("http"):
            u = "https://" + u
        h = _host(u)
        if not h or any(s in h for s in SKIP_WEBSITE) or any(re.fullmatch(p[0], h) for p in SOCIALS.values()):
            continue
        if any(h == o or h.endswith("." + o) for o in OTHER):
            continue
        before = (desc[max(0, m.start() - 40):m.start()]).lower()
        toks = [t for t in re.findall(r"[a-z0-9]{4,}", (title or "").lower())]
        score = (3 if re.search(r"website|my site|business|work with|coaching|agency|book|hire|course|official", before) else 0) \
            + (3 if any(t in h for t in toks) else 0) + (2 if h in AGGREGATORS else 0)
        cands.append((score, -m.start(), u))
    cands.sort(reverse=True)
    return cands[0][2] if cands else ""


def rank_emails(emails, site_domain):
    def key(e):
        local, _, dom = e.partition("@")
        return (dom == site_domain or dom.endswith("." + site_domain) if site_domain else False,
                dom not in FREE_MAIL, local in ROLE_LOCAL)
    return sorted(emails, key=key, reverse=True)


def email_type(e, site_domain):
    local, _, dom = e.partition("@")
    if site_domain and (dom == site_domain or dom.endswith("." + site_domain)):
        return "Business domain" + (" (role)" if local in ROLE_LOCAL else "")
    if dom in FREE_MAIL:
        return "Free mail (personal/creator)"
    return "Other domain"


def enrich(desc, title, enrich_site=True, max_pages=4):
    """Returns dict: website, emails[list], email_source, socials{}, notes[list]."""
    notes, emails, source = [], [], ""
    socials = socials_in(desc)
    d_emails = emails_in(desc)
    if d_emails:
        emails, source = d_emails, "YouTube description"
    site = pick_website(desc, title)
    domain = "" if (not site or _host(site) in AGGREGATORS) else _host(site)
    if enrich_site and site:
        pages = [site]
        if domain:
            base = f"{urlparse(site).scheme}://{urlparse(site).netloc}"
            pages += [urljoin(base, p) for p in ("/contact", "/about", "/contact-us", "/work-with-me")]
        got_any = False
        for u in pages[:max_pages + 1]:
            html = fetch(u)
            if html is None:
                continue
            got_any = True
            socials_in(html, socials)
            for e in emails_in(html):
                if e not in emails:
                    emails.append(e)
                    source = source or ("Link page" if _host(site) in AGGREGATORS else "Website")
            if _host(site) in AGGREGATORS:
                break
            time.sleep(0.5)
        if not got_any:
            notes.append("Website unreachable or blocked by robots.txt")
    emails = rank_emails(emails, domain)[:5]
    return {"website": site, "domain": domain, "emails": emails, "email_source": source if emails else "",
            "socials": socials, "notes": notes}


def hunter(domain, key):
    """Optional: public emails Hunter already knows for a domain. Returns (emails, organization)."""
    try:
        r = requests.get("https://api.hunter.io/v2/domain-search",
                         params={"domain": domain, "api_key": key, "limit": 5}, timeout=20)
        if r.status_code != 200:
            return [], ""
        d = r.json().get("data", {})
        es = [x["value"].lower() for x in d.get("emails", []) if x.get("value") and x.get("confidence", 0) >= 70]
        return es, d.get("organization") or ""
    except Exception:
        return [], ""


def apollo(domain, key):
    """Optional: company name + employee estimate (Apollo organization enrichment). Returns (name, employees)."""
    try:
        r = requests.get("https://api.apollo.io/api/v1/organizations/enrich", params={"domain": domain},
                         headers={"X-Api-Key": key, "accept": "application/json"}, timeout=20)
        if r.status_code != 200:
            return "", ""
        o = r.json().get("organization") or {}
        return o.get("name") or "", o.get("estimated_num_employees") or ""
    except Exception:
        return "", ""


def instagram_stats(handle):
    """Official Meta Business Discovery. Only business/creator accounts are readable; else None."""
    token, uid = os.getenv("IG_ACCESS_TOKEN", "").strip(), os.getenv("IG_USER_ID", "").strip()
    if not (token and uid and handle):
        return None
    f = (f"business_discovery.username({handle})"
         "{followers_count,media_count,media.limit(12){like_count,comments_count,timestamp}}")
    try:
        r = requests.get(f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION', 'v24.0')}/{uid}",
                         params={"fields": f, "access_token": token}, timeout=30)
        if r.status_code != 200:
            return None
        d = r.json().get("business_discovery", {})
        fol = d.get("followers_count") or 0
        media = d.get("media", {}).get("data", [])
        if not fol or not media:
            return None
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        posts30 = 0
        for m in media:
            try:
                if (now - datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")).days < 30:
                    posts30 += 1
            except Exception:
                pass
        er = sum((m.get("like_count") or 0) + (m.get("comments_count") or 0) for m in media) / len(media) / fol
        return {"followers": fol, "engagement": round(er * 100, 2), "posts30": posts30}
    except Exception:
        return None


def _cf_decode(h):
    """Decode Cloudflare 'email protection' (very common on AU business sites)."""
    try:
        b = bytes.fromhex(h)
        return "".join(chr(c ^ b[0]) for c in b[1:])
    except Exception:
        return ""


def enrich_site(site, max_pages=4, read_site=True):
    """For a KNOWN business website (from Google Places). Returns website, domain, emails, source, socials, notes."""
    notes, emails, socials, source = [], [], {}, ""
    host = _host(site) if site else ""
    is_social = any(re.fullmatch(p[0], host) for p in SOCIALS.values()) if host else False
    if site and is_social:                      # the 'website' on Maps is really a Facebook/Instagram page
        socials_in(site, socials)
        return {"website": "", "domain": "", "emails": [], "email_source": "", "socials": socials,
                "notes": ["Listed 'website' is a social page"]}
    domain = "" if (not host or host in AGGREGATORS) else host
    if read_site and site:
        base = f"{urlparse(site).scheme}://{urlparse(site).netloc}"
        pages = [site] + ([urljoin(base, p) for p in ("/contact", "/contact-us", "/about", "/privacy-policy", "/about-us", "/team", "/our-team")]
                          if domain else [])
        got, form_only = False, False
        for u in pages[:max_pages]:
            html = fetch(u)
            if html is None:
                continue
            got = True
            for h in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html):
                dec = _cf_decode(h)
                if dec:
                    html += " " + dec
            socials_in(html, socials)
            found = emails_in(html)
            for e in found:
                if e not in emails:
                    emails.append(e)
                    source = source or ("Link page" if host in AGGREGATORS else "Website")
            if not found and "<form" in html.lower() and "contact" in u.lower():
                form_only = True
            time.sleep(0.4)
        if not got:
            notes.append("Website unreachable or blocked by robots.txt")
        elif not emails and form_only:
            notes.append("Contact form only (no public email)")
    emails = rank_emails(emails, domain)[:5]
    return {"website": site or "", "domain": domain, "emails": emails, "email_source": source if emails else "",
            "socials": socials, "notes": notes}
