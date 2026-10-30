"""Australian local-business lead bot ($0 mode).

Sources (all free by default): your 'Leads Input' tab -> OpenStreetMap (Overpass, no key). Optional: Google Places.
Pipeline per business: filters -> free website read -> optional enrichers (Jina / Hunter / Apollo / Apify / Meta) ->
email verification (free MX check; ZeroBounce/Hunter if keys) -> score -> AI or template email draft -> sheet.
EVERY optional step is non-blocking: it can fail, be missing or be rate limited and the lead still goes through.
Run: python leadbot.py   |   python leadbot.py --dry"""
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import gspread
from gspread.utils import rowcol_to_a1

import defaults as D
import drafts as DR
import enrich as E
import optional as O
import osm as OSM
import score as SC
from ai import AI
from places import Places, AllKeysExhausted

RESERVED = {"rules", "niches", "locations", "seen", "searches", "blacklist", "run log", "summary", "playbook", "leads input"}
# Feature flags requested in the spec (safe os.getenv usage; see optional.py for the exact definitions)
ENRICH_WEBSITES = O.ENRICH_WEBSITES
VERIFY_EMAILS = O.VERIFY_EMAILS


# ------------------------------------------------------------------ helpers
def env(k, d=""):
    return (os.getenv(k, "") or d).strip()


def safe(fn, default, label="step"):
    """Run an optional step. On ANY exception: count it, stay silent, return the default (the unmodified base)."""
    try:
        return fn()
    except Exception as e:
        O.STATS[label] += 1
        return default


def retry(fn, tries=5):
    for i in range(tries):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", 0)
            if code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(15 * (i + 1))
                continue
            raise
        except Exception as e:
            if i < tries - 1 and "Connection" in type(e).__name__ + str(e):
                time.sleep(10 * (i + 1))
                continue
            raise


def get_all(ws):
    return retry(lambda: ws.get_all_values())


def append(ws, rows):
    for i in range(0, len(rows), 200):
        part = rows[i:i + 200]
        retry(lambda: ws.append_rows(part, value_input_option="RAW"))


def col_letter(n):
    return re.sub(r"\d", "", rowcol_to_a1(1, n))


def pad(r, n):
    return list(r) + [""] * (n - len(r))


class Settings(dict):
    def num(self, k, d=0.0):
        v = str(self.get(k, "")).strip().replace(" ", "")
        try:
            if v.endswith("%"):
                return float(v[:-1]) / 100
            if re.fullmatch(r"\d+,\d+", v):
                v = v.replace(",", ".")
            return float(v)
        except ValueError:
            return d

    def yes(self, k, d=True):
        v = str(self.get(k, "")).strip().lower()
        return d if not v else v in ("yes", "y", "true", "1", "on")

    def list(self, k):
        return [x.strip().lower() for x in str(self.get(k, "")).split(",") if x.strip()]


def num(v, d=0.0):
    return Settings({"x": v}).num("x", d)


def get_tab(sh, title, headers):
    """Open/create a tab. Never overwrites existing headers: missing ones are appended at the end."""
    try:
        ws = retry(lambda: sh.worksheet(title))
    except gspread.WorksheetNotFound:
        ws = retry(lambda: sh.add_worksheet(title, rows=1000, cols=len(headers) + 2))
        retry(lambda: ws.update(range_name="A1", values=[headers]))
        for fn in (lambda: ws.freeze(rows=1), lambda: ws.format("1:1", {"textFormat": {"bold": True}}),
                   lambda: ws.set_basic_filter()):
            try:
                fn()
            except Exception:
                pass
        return ws, list(headers)
    cur = [h.strip() for h in retry(lambda: ws.row_values(1))]
    if not any(cur):
        retry(lambda: ws.update(range_name="A1", values=[headers]))
        return ws, list(headers)
    missing = [h for h in headers if h not in cur]
    if missing:
        if ws.col_count < len(cur) + len(missing):
            retry(lambda: ws.resize(cols=len(cur) + len(missing)))
        retry(lambda: ws.update(range_name=rowcol_to_a1(1, len(cur) + 1), values=[missing]))
        cur += missing
    return ws, cur


def tab_name(niche):
    n = re.sub(r"[\[\]\*\?:/\\]", " ", niche).strip()[:90] or "Leads"
    return n + " Leads" if n.lower() in RESERVED else n


def legacy_check(sh):
    for title, marker in (("Niches", "Search Keywords (separate with ;)"), ("Seen", "Channel Id")):
        try:
            hdr = retry(lambda: sh.worksheet(title).row_values(1))
        except gspread.WorksheetNotFound:
            continue
        if marker in hdr:
            sys.exit("This Google Sheet was used by the old YouTube lead bot. Use a NEW Google Sheet, or delete the tabs "
                     "Rules, Niches, Seen, Run Log, Summary and Playbook (and old niche tabs) first.")


# ------------------------------------------------------------------ config in the sheet
def load_config(sh):
    legacy_check(sh)
    ws, _ = get_tab(sh, "Rules", D.SETTINGS_H)
    rows = get_all(ws)
    have = {r[0].strip() for r in rows[1:] if r and r[0].strip()}
    new = [[k, v, why] for k, v, why in D.SETTINGS if k not in have]
    if new:
        append(ws, new)
        rows = get_all(ws)
    S = Settings({r[0].strip(): (r[1].strip() if len(r) > 1 else "") for r in rows[1:] if r and r[0].strip()})

    nws, nhdr = get_tab(sh, "Niches", D.NICHES_H)
    nrows = get_all(nws)
    if len(nrows) < 2:
        append(nws, [list(n) for n in D.NICHES])
        nrows = get_all(nws)
    ix = {h: nhdr.index(h) for h in D.NICHES_H if h in nhdr}
    g = lambda r, h: (r[ix[h]].strip() if h in ix and ix[h] < len(r) else "")
    niches, skipped = [], []
    for r in nrows[1:]:
        name = g(r, "Niche")
        if not name or g(r, "Enabled (Yes/No)").lower() not in ("yes", "y", "true", "1"):
            continue
        low, high = num(g(r, "Budget Low AUD"), 0), num(g(r, "Budget High AUD"), 0)
        if low < S.num("MIN_BUDGET_AUD", 500):
            skipped.append(name)
            continue
        niches.append({"niche": name, "group": g(r, "Group"),
                       "terms": [t.strip() for t in re.split(r"[;\n]", g(r, "Search Terms (separate with ;)")) if t.strip()],
                       "osm": [t.strip() for t in re.split(r"[;\n]", g(r, "Free Map Selectors (OSM, separate with ;)")) if t.strip()],
                       "fit": num(g(r, "Budget Fit (1-5)"), 3), "low": int(low), "high": int(high or low),
                       "tpl": g(r, "Pitch Angle Template") or "{name}. Gap: {gap}. Offer a free 30-60s sample reel.",
                       "why": g(r, "Why this niche fits")})
    lws, lhdr = get_tab(sh, "Locations", D.LOC_H)
    lrows = get_all(lws)
    if len(lrows) < 2:
        append(lws, [list(x) for x in D.LOCATIONS])
        lrows = get_all(lws)
    li = {h: lhdr.index(h) for h in D.LOC_H if h in lhdr}
    lg = lambda r, h: (r[li[h]].strip() if h in li and li[h] < len(r) else "")
    locs = []
    for i, r in enumerate(lrows[1:], start=2):
        if not lg(r, "Search Area") or lg(r, "Enabled (Yes/No)").lower() not in ("yes", "y", "true", "1"):
            continue
        lat, lon = num(lg(r, "Latitude"), 0), num(lg(r, "Longitude"), 0)
        locs.append({"country": lg(r, "Country") or "Australia", "state": lg(r, "State"), "city": lg(r, "City"),
                     "area": lg(r, "Search Area"), "priority": int(num(lg(r, "Priority (1-3)"), 2) or 2),
                     "lat": lat, "lon": lon, "radius": num(lg(r, "Radius km"), 6) or 6,
                     "_row": i, "_lat_col": li.get("Latitude"), "_ws": lws})
    pws, _ = get_tab(sh, "Playbook", ["Playbook (ICP + how to use these leads). Edit freely; the bot never overwrites it."])
    if len(get_all(pws)) < 2:
        append(pws, [[l] for l in D.PLAYBOOK])
    return S, niches, locs, skipped


def load_seen(sh, S):
    ws, _ = get_tab(sh, "Seen", D.SEEN_H)
    block, domains, emails = set(), set(), set()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(S.num("RECHECK_DAYS", 120)))).date().isoformat()
    for r in get_all(ws)[1:]:
        pid, dom, em, _, date, res = (x.strip() for x in pad(r, 6)[:6])
        if not pid:
            continue
        if res.startswith("Added"):
            block.add(pid)
            if dom:
                domains.add(dom.lower())
            emails.update(e for e in em.lower().split(";") if e)
        elif date >= cutoff:
            block.add(pid)
    bws, _ = get_tab(sh, "Blacklist", D.BLACKLIST_H)
    bl = {r[0].strip().lower() for r in get_all(bws)[1:] if r and r[0].strip()}
    sws, _ = get_tab(sh, "Searches", D.SEARCH_H)
    last = {}
    for r in get_all(sws)[1:]:
        r = pad(r, 5)
        if r[0] and r[1] > last.get(r[0], ""):
            last[r[0]] = r[1]
    return ws, sws, block, domains, emails, bl, last


# ------------------------------------------------------------------ place handling
def norm_name(n):
    n = re.sub(r"\b(pty|ltd|p/l|the|and|&|clinic|centre|center|group)\b", " ", n.lower())
    return re.sub(r"[^a-z0-9]+", "", n)


def parse_address(p):
    comp = {}
    for c in p.get("addressComponents", []):
        for t in c.get("types", []):
            comp.setdefault(t, c)
    gg = lambda t, k="longText": comp.get(t, {}).get(k, "")
    return {"suburb": gg("locality") or gg("sublocality_level_1") or gg("sublocality"),
            "state": gg("administrative_area_level_1", "shortText"), "postcode": gg("postal_code"),
            "country": gg("country") or "Australia", "cc": gg("country", "shortText")}


def reject_reason(p, a, S, ctx, state):
    if p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
        return "not operating"
    if a["cc"] and a["cc"] != "AU":
        return "not in Australia"
    name = p.get("displayName", {}).get("text", "")
    if any(w in name.lower() for w in S.list("BLOCK_NAME_WORDS")):
        return "blocked name (chain/public)"
    if set(p.get("types", [])) & set(S.list("EXCLUDE_TYPES")):
        return "excluded place type"
    nometrics = p.get("_nometrics")
    if not nometrics:
        n, rt = int(p.get("userRatingCount", 0) or 0), float(p.get("rating", 0) or 0)
        if n < S.num("MIN_REVIEWS", 8):
            return "too few reviews"
        if n > S.num("MAX_REVIEWS", 600):
            return "too many reviews (big brand)"
        if rt and rt < S.num("MIN_RATING", 3.5):
            return "low rating"
    needs_site = S.yes("REQUIRE_WEBSITE_OSM", True) if p.get("_source") == "OpenStreetMap" else S.yes("REQUIRE_WEBSITE", False)
    if needs_site and not p.get("websiteUri") and not p.get("_email"):
        return "no website"
    chain = int(S.num("CHAIN_LOCATIONS", 3))
    nm = norm_name(name)
    host = E._host(p.get("websiteUri", "")) if p.get("websiteUri") else ""
    if ctx["names"][nm] >= chain or state["names_run"][nm] >= chain:
        return "chain (same name in many places)"
    if host and (ctx["hosts"][host] >= chain or state["hosts_run"][host] >= chain):
        return "chain (same website in many places)"
    state["names_run"][nm] += 1
    if host:
        state["hosts_run"][host] += 1
    return None


def qualify(p, nic, loc, S, ai, state, ctx, found):
    a = parse_address(p)
    r = reject_reason(p, a, S, ctx, state)
    if r:
        return r, None
    name, site = p["displayName"]["text"], p.get("websiteUri", "")
    bl = state["blacklist"]
    if p["id"].lower() in bl or name.lower() in bl or (site and E._host(site) in bl):
        return "blacklisted", None
    used = []                                                   # which enrichers contributed (for the 'Enrichment' column)

    # 1) free built-in website read (own try/except via safe)
    base = {"website": site, "domain": E._host(site) if site else "", "emails": [], "email_source": "", "socials": {}, "notes": []}
    info = safe(lambda: E.enrich_site(site, int(S.num("MAX_SITE_PAGES", 5)), S.yes("READ_WEBSITES")), base, "site-read") if site else base
    domain, emails, source, soc, notes = info["domain"], list(info["emails"]), info["email_source"], dict(info["socials"]), list(info["notes"])
    # seed from structured tags/inputs (OSM tags or your Leads Input tab)
    for e in E.emails_in(p.get("_email", "")):
        if e not in emails:
            emails.insert(0, e)
            source = source or ("Input tab" if p.get("_source") == "Manual input" else "OpenStreetMap tag")
    for plat, k in (("Instagram", "_ig"), ("Facebook", "_fb")):
        if p.get(k):
            soc.setdefault(plat, p[k])
    summary = ""

    # 2) OPTIONAL Jina Reader fallback: only when the normal read found little (never blocks)
    if (ENRICH_WEBSITES and site and domain and (not emails or len(soc) < 2) and O.available("jina")
            and state["jina"] < S.num("USE_JINA_MAX", 40)):
        state["jina"] += 1
        j = O.jina_read(site)
        if j:
            used.append("jina")
            summary = j["summary"]
            for e in j["emails"]:
                if e not in emails:
                    emails.append(e)
                    source = source or "Jina Reader"
            for k, v in j["socials"].items():
                soc.setdefault(k, v)
    emails = E.rank_emails(emails, domain)[:5]

    # 3) OPTIONAL Hunter domain search (only when still no email)
    org, employees = "", ""
    if (domain and not emails and S.yes("USE_HUNTER") and O.key("HUNTER_API_KEY") and O.available("hunter")
            and state["hunter"] < S.num("MAX_HUNTER_PER_RUN", 8)):
        state["hunter"] += 1
        h = O.hunter_find(domain)
        if h and h["emails"]:
            emails, source, org = h["emails"], "Hunter", h["org"]
            used.append("hunter")
    # 4) OPTIONAL Apollo company info
    if (domain and S.yes("USE_APOLLO") and O.key("APOLLO_API_KEY") and O.available("apollo")
            and state["apollo"] < S.num("MAX_APOLLO_PER_RUN", 20)):
        state["apollo"] += 1
        ap = O.apollo_org(domain)
        if ap:
            org, employees = ap[0] or org, ap[1]
            used.append("apollo")

    emails = [e for e in emails if e.lower() not in bl and e.split("@")[1].lower() not in bl]
    if any(e.lower() in state["emails"] for e in emails):
        return "duplicate email (already added)", None
    if domain and domain in state["domains"]:
        return "same website already added", None

    # 5) email verification: free MX check always; ZeroBounce/Hunter only if keys. Unknown/skipped => keep the email.
    status, dropped = "", 0
    if emails and state["verify"] < S.num("MAX_VERIFY_PER_RUN", 80):
        kept, first = [], True
        for e in emails[:3]:
            state["verify"] += 1
            v = O.verify_email(e)
            if v == "invalid":
                dropped += 1
                continue
            kept.append(e)
            if first:
                status, first = v or "", False
        emails = kept + emails[3:]
        if status:
            used.append({"valid": "verified", "risky": "catch-all", "mx-ok": "mx-ok"}.get(status, status))
        if dropped:
            notes.append(f"{dropped} email(s) dropped: failed verification")
    email_status = {"valid": "valid", "risky": "catch-all (risky)", "mx-ok": "domain accepts mail"}.get(status, "unverified" if emails else "")

    phone = p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber") or ""
    social_any = any(k in soc for k in ("Instagram", "LinkedIn", "Facebook", "Twitter / X"))
    mode = S.get("REQUIRE_CONTACT", "email_or_social").lower()
    if mode == "email" and not emails:
        return "no email found", None
    if mode == "email_or_social" and not emails and not social_any:
        return "no way to contact", None
    if mode == "any" and not (emails or social_any or phone):
        return "no way to contact", None

    # 6) OPTIONAL Instagram activity: Meta first, Apify as optional fallback
    igs, ig_handle = None, (soc.get("Instagram", "").rstrip("/").split("/")[-1] if soc.get("Instagram") else "")
    if ig_handle and S.yes("USE_INSTAGRAM_STATS"):
        if O.key("IG_ACCESS_TOKEN") and O.available("meta_ig") and state["ig"] < S.num("MAX_IG_PER_RUN", 40):
            state["ig"] += 1
            igs = O.ig_meta(ig_handle)
            used += ["meta-ig"] if igs else []
        if not igs and S.yes("USE_APIFY", False) and O.key("APIFY_API_TOKEN") and O.available("apify") \
                and state["apify"] < S.num("MAX_APIFY_PER_RUN", 10):
            state["apify"] += 1
            igs = O.ig_apify(ig_handle)
            used += ["apify"] if igs else []
    sev, gap = SC.social_gap(soc, igs)
    etype = E.email_type(emails[0], domain) if emails else ""
    rating = float(p["rating"]) if p.get("rating") else None
    reviews = int(p["userRatingCount"]) if p.get("userRatingCount") else None
    sc = SC.score({"fit": nic["fit"], "reviews": reviews, "rating": rating, "has_website": bool(site and domain),
                   "email": bool(emails), "email_type": etype, "email_status": status, "instagram": "Instagram" in soc,
                   "other_social": social_any, "phone": bool(phone), "gap_sev": sev, "priority": loc["priority"]}, S)
    if sc < S.num("MIN_SCORE", 50):
        return f"score {sc} below minimum", None

    facts = {"name": name, "city": loc["city"], "rating": rating or "", "reviews": reviews or "", "gap": gap,
             "niche": nic["niche"], "summary": summary}
    pitch_line = SC.pitch(nic["tpl"], facts)
    if rating is None:
        pitch_line = pitch_line.replace(" at  stars", "").replace("  reviews", "")
    # 7) email draft: AI (free keys) or template. AI failure trips a breaker so later leads skip AI instantly.
    ai_ok = (ai is not None and not state["ai_off"] and S.yes("USE_AI_EMAIL") and state["ai_email"] < S.num("MAX_AI_EMAILS_PER_RUN", 40))
    if ai_ok:
        state["ai_email"] += 1
    subj, body, used_ai, ai_failed = DR.build(ai if ai_ok else None, facts)
    if ai_failed:
        state["ai_off"] = True
        state["ai_fail"] += 1
    if used_ai:
        used.append("ai-draft")
    if not emails:
        notes.append("No public email: use Instagram/contact form" + (" or phone" if phone else ""))
    if nic["group"] == "Medical":
        notes.append("Health advertising rules (AHPRA/TGA) apply")
    if emails and etype.endswith("(role)"):
        notes.append("Role mailbox: ask for the owner / practice or marketing manager")
    if p.get("_nometrics"):
        notes.append("Rating/reviews not available from this free source")
    other = [f"{k[6:]}: {v}" for k, v in soc.items() if k.startswith("Other:")]
    now = datetime.now(timezone.utc).date().isoformat()
    return None, {
        "Niche": nic["niche"], "Group": nic["group"], "Score": sc, "Tier": SC.tier_of(sc, S), "Business Name": name,
        "Country": a["country"], "City": loc["city"], "State": a["state"] or loc["state"], "Suburb": a["suburb"],
        "Postcode": a["postcode"], "Full Address": p.get("formattedAddress", ""), "Map Url": p.get("googleMapsUri", ""),
        "Email": emails[0] if emails else "", "Email Verified": email_status, "Phone": phone, "Website": site,
        "Instagram": soc.get("Instagram", ""), "Facebook": soc.get("Facebook", ""), "LinkedIn": soc.get("LinkedIn", ""),
        "Twitter / X": soc.get("Twitter / X", ""), "TikTok": soc.get("TikTok", ""), "YouTube": soc.get("YouTube", ""),
        "Other Socials": " | ".join(other), "Pitch Angle": pitch_line, "Social Gap": gap, "Email Subject": subj,
        "Email Draft": body, "Website Summary": summary, "Budget Low AUD": nic["low"], "Budget High AUD": nic["high"],
        "Google Rating": rating or "", "Review Count": reviews or "", "Employee Count": employees,
        "Business Type": p.get("primaryTypeDisplayName", {}).get("text", ""),
        "IG Followers": igs["followers"] if igs else "", "IG Engagement %": igs["engagement"] if igs else "",
        "IG Posts 30d": igs["posts30"] if igs else "", "All Emails": ";".join(emails), "Email Source": source,
        "Email Type": etype, "Owner / Contact Name": org, "Notes": "; ".join(notes),
        "Enrichment": ", ".join(used) or "base only", "Data Source": p.get("_source", "Google Maps"), "Found On": found,
        "Status": "New", "My Notes": "", "Last Checked": now, "Lead Added On": now, "Place Id": p["id"], "_domain": domain}


def process_places(places, nic, loc, S, ai, state, cap_left, found):
    ctx = {"names": Counter(norm_name(p.get("displayName", {}).get("text", "")) for p in places),
           "hosts": Counter(E._host(p["websiteUri"]) for p in places if p.get("websiteUri"))}
    leads, seen_rows, stats = [], [], Counter()
    today = datetime.now(timezone.utc).date().isoformat()
    for p in places:
        if not p.get("id") or p["id"] in state["block"]:
            continue
        if len(leads) >= cap_left or time.time() > state["deadline"]:
            break
        try:
            reason, lead = qualify(p, nic, loc, S, ai, state, ctx, found)
        except Exception as e:                         # last-resort guard: one bad business never stops the loop
            reason, lead = f"error: {type(e).__name__}", None
            state["problems"].append(f"{str(p.get('id', '?'))[:14]}: {type(e).__name__} {str(e)[:60]}")
        state["block"].add(p["id"])
        if lead:
            dom = lead.pop("_domain")
            state["emails"].update(e.lower() for e in lead["All Emails"].split(";") if e)
            if dom:
                state["domains"].add(dom)
            leads.append(lead)
            seen_rows.append([p["id"], dom, lead["All Emails"], nic["niche"], today, "Added"])
            stats["added"] += 1
        else:
            seen_rows.append([p["id"], "", "", nic["niche"], today, "Rejected: " + reason])
            stats["rej: " + reason] += 1
    stats["places"] = len(places)
    return leads, seen_rows, stats


# ------------------------------------------------------------------ manual input tab (always free)
def manual_places(sh, S, niches):
    ws, hdr = get_tab(sh, "Leads Input", D.INPUT_H)
    rows = get_all(ws)
    ix = {h: hdr.index(h) for h in D.INPUT_H if h in hdr}
    g = lambda r, h: (r[ix[h]].strip() if h in ix and ix[h] < len(r) else "")
    out = []
    for r in rows[1:]:
        name = g(r, "Business Name")
        if not name:
            continue
        site = g(r, "Website")
        site = site if (not site or site.startswith("http")) else "https://" + site
        key = hashlib.md5((norm_name(name) + E._host(site)).encode()).hexdigest()[:12]
        nt = g(r, "Niche").lower()
        nic = next((n for n in niches if nt and (nt in n["niche"].lower() or n["niche"].lower() in nt)), None) or {
            "niche": g(r, "Niche") or "Manual Leads", "group": "Manual", "fit": 3, "low": int(S.num("MIN_BUDGET_AUD", 500)),
            "high": 2000, "tpl": "{name}. Gap: {gap}. Offer a free 30-60s sample reel.", "why": ""}
        st = g(r, "State")
        loc = {"city": g(r, "City"), "state": st, "area": "Manual", "priority": 2}
        ig = g(r, "Instagram")
        place = {"id": "input:" + key, "displayName": {"text": name}, "websiteUri": site, "nationalPhoneNumber": g(r, "Phone"),
                 "formattedAddress": ", ".join(x for x in (g(r, "City"), st, "Australia") if x), "businessStatus": "OPERATIONAL",
                 "addressComponents": [{"longText": g(r, "City"), "shortText": g(r, "City"), "types": ["locality"]},
                                       {"longText": st, "shortText": st, "types": ["administrative_area_level_1"]},
                                       {"longText": "Australia", "shortText": "AU", "types": ["country"]}],
                 "_nometrics": True, "_source": "Manual input", "_email": g(r, "Email"),
                 "_ig": (ig if ig.startswith("http") else ("https://www.instagram.com/" + ig.lstrip("@/") if ig else "")),
                 "primaryTypeDisplayName": {"text": g(r, "Niche")}}
        out.append((nic, loc, place))
    return out


# ------------------------------------------------------------------ output
def finish_tabs(sh, tabs, S):
    if S.yes("SORT_TABS"):
        for ws, hdr in tabs.values():
            try:
                n = max(2, len(retry(lambda: ws.col_values(1))))
                retry(lambda: ws.sort((hdr.index("Score") + 1, "des"), range=f"A2:{rowcol_to_a1(n, len(hdr))}"))
            except Exception:
                pass
    sws, _ = get_tab(sh, "Summary", ["Tab"])
    rows = [["Tab", "Total leads", "Tier A", "Tier B", "With email", "With Instagram", "Added today"]]
    today = datetime.now(timezone.utc).date().isoformat()
    for name, (ws, hdr) in sorted(tabs.items()):
        q = "'" + ws.title.replace("'", "''") + "'!"
        L = lambda h: col_letter(hdr.index(h) + 1) if h in hdr else "A"
        rows.append([ws.title, f"=COUNTA({q}{L('Place Id')}2:{L('Place Id')})",
                     f'=COUNTIF({q}{L("Tier")}2:{L("Tier")},"A")', f'=COUNTIF({q}{L("Tier")}2:{L("Tier")},"B")',
                     f'=COUNTIF({q}{L("Email")}2:{L("Email")},"*@*")', f'=COUNTIF({q}{L("Instagram")}2:{L("Instagram")},"http*")',
                     f'=COUNTIF({q}{L("Lead Added On")}2:{L("Lead Added On")},"{today}")'])
    retry(lambda: sws.clear())
    retry(lambda: sws.update(range_name="A1", values=rows, value_input_option="USER_ENTERED"))


def all_lead_tabs(sh):
    tabs = {}
    for ws in sh.worksheets():
        if ws.title.lower() in RESERVED:
            continue
        hdr = [h.strip() for h in retry(lambda: ws.row_values(1))]
        if "Place Id" in hdr and "Score" in hdr:
            tabs[ws.title] = (ws, hdr)
    return tabs


# ------------------------------------------------------------------ main
def main(dry=False):
    t0 = time.time()
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON") or env("GOOGLE_SA")
    sheet_id = env("SHEET_ID")
    if not raw or not sheet_id:
        sys.exit("MISSING CORE SETTING: SHEET_ID and GOOGLE_SA are required. See README.md.")
    info = json.loads(raw) if raw.lstrip().startswith("{") else json.load(open(raw))
    sh = retry(lambda: gspread.service_account_from_dict(info).open_by_key(sheet_id))
    S, niches, locs, skipped = load_config(sh)
    run_ws, _ = get_tab(sh, "Run Log", D.RUN_H)
    problems, totals, pl, searches_done = [], Counter(), None, 0
    if skipped:
        problems.append("Skipped (budget below MIN_BUDGET_AUD): " + ", ".join(skipped))
    try:
        ai = None                                                  # AI is optional: no key / dead key => template drafts
        if env("AI_API_KEYS"):
            try:
                ai = AI(env("AI_API_KEYS"))
            except Exception as e:
                problems.append(f"AI unavailable, template drafts used: {str(e)[:100]}")
        seen_ws, search_ws, block, domains, emails, bl, last = load_seen(sh, S)
        state = {"block": block, "domains": domains, "emails": emails, "blacklist": bl, "problems": problems,
                 "hunter": 0, "apollo": 0, "ig": 0, "apify": 0, "jina": 0, "verify": 0, "ai_email": 0, "ai_fail": 0,
                 "ai_off": False, "names_run": Counter(), "hosts_run": Counter(),
                 "deadline": t0 + S.num("MAX_RUNTIME_MIN", 40) * 60}
        total_cap = int(S.num("NEW_LEADS_PER_RUN", 40))
        tabs, added = {}, Counter()

        def commit(nic, leads, seen_rows, key=None, pages=1, places_n=0):
            if dry:
                return
            ws, hdr = get_tab(sh, tab_name(nic["niche"]), D.LEAD_H)
            tabs[ws.title] = (ws, hdr)
            if leads:
                append(ws, [[l.get(h, "") for h in hdr] for l in leads])
            if seen_rows:
                append(seen_ws, seen_rows)
            if key:
                append(search_ws, [[key, datetime.now(timezone.utc).date().isoformat(), pages, places_n, len(leads)]])

        # A) your own Leads Input tab (free, always first)
        for nic, loc, place in safe(lambda: manual_places(sh, S, niches), [], "manual-tab"):
            if sum(added.values()) >= total_cap or time.time() > state["deadline"]:
                break
            leads, seen_rows, st = process_places([place], nic, loc, S, ai, state, 1, "Leads Input tab")
            totals.update(st)
            added[nic["niche"]] += st["added"]
            if leads or seen_rows:
                commit(nic, leads, seen_rows)

        # B) discovery: free OpenStreetMap by default; Google Places only if you added a key and SOURCE allows it
        src = S.get("SOURCE", "auto").lower()
        use_places = src == "places" or (src == "auto" and bool(env("PLACES_API_KEYS")))
        use_osm = src == "osm" or (src == "auto" and not env("PLACES_API_KEYS"))
        if use_places:
            pl = Places(re.split(r"[\s,;]+", env("PLACES_API_KEYS")))
        budget = int(S.num("MAX_SEARCH_REQUESTS_PER_RUN", 12))
        if niches and locs and (use_places or use_osm):
            queues = {}
            for n in niches:
                combos = [(last.get(f"{n['niche']}|{l['area']}", ""), l["priority"], random.random(), l) for l in locs]
                combos.sort(key=lambda x: x[:3])
                queues[n["niche"]] = [x[3] for x in combos]
            order = list(niches)
            random.shuffle(order)
            per_cap = math.ceil(total_cap / max(1, min(len(niches), budget)))
            while searches_done < budget and time.time() < state["deadline"] and any(queues.values()):
                progressed = False
                for nic in order:
                    if searches_done >= budget or time.time() > state["deadline"] or sum(added.values()) >= total_cap:
                        break
                    if not queues[nic["niche"]] or added[nic["niche"]] >= per_cap:
                        continue
                    loc = queues[nic["niche"]].pop(0)
                    progressed = True
                    cap_left = min(per_cap - added[nic["niche"]], total_cap - sum(added.values()))
                    try:
                        if use_places:
                            term = random.choice(nic["terms"] or [nic["niche"]])
                            q, places, token, pages = f"{term} in {loc['area']}", [], None, 0
                            for _ in range(int(max(1, min(3, S.num("MAX_PAGES_PER_SEARCH", 2))))):
                                if pl.requests >= budget:
                                    break
                                data = pl.search(q, token)
                                pages += 1
                                places += data.get("places", [])
                                token = data.get("nextPageToken")
                                if not token:
                                    break
                            searches_done = pl.requests
                            found = f"Google Maps: {q}"
                        else:
                            if not nic["osm"]:
                                problems.append(f"{nic['niche']}: no Free Map Selectors in Niches tab (skipped)")
                                queues[nic["niche"]] = []
                                continue
                            if not (loc["lat"] and loc["lon"]):
                                g = OSM.geocode(loc["area"] + ", Australia")
                                if not g:
                                    problems.append(f"{loc['area']}: add Latitude/Longitude in Locations (geocode failed)")
                                    continue
                                loc["lat"], loc["lon"] = g
                                if loc["_lat_col"] is not None:           # save so we never geocode it again
                                    safe(lambda: loc["_ws"].update(range_name=rowcol_to_a1(loc["_row"], loc["_lat_col"] + 1),
                                                                   values=[[g[0], g[1], loc["radius"]]]), None, "geocode-save")
                            places = OSM.search(nic["osm"], loc, int(S.num("OSM_LIMIT", 150)))
                            pages, found = 1, f"OpenStreetMap: {nic['niche']} near {loc['area']}"
                            searches_done += 1
                            time.sleep(S.num("OSM_DELAY_SEC", 6))
                        leads, seen_rows, st = process_places(places, nic, loc, S, ai, state, cap_left, found)
                    except AllKeysExhausted:
                        problems.append("Google Places keys exhausted/billing off: falling back to free sources next run.")
                        use_places = False
                        break
                    except OSM.OSMUnavailable as e:
                        problems.append(str(e)[:120])
                        searches_done += 1
                        continue
                    except Exception as e:
                        problems.append(f"{nic['niche']} / {loc['area']}: {type(e).__name__} {str(e)[:100]}")
                        searches_done += 1
                        continue
                    totals.update(st)
                    added[nic["niche"]] += st["added"]
                    print(f"{nic['niche']} | {loc['area']}: {dict(st)}")
                    commit(nic, leads, seen_rows, f"{nic['niche']}|{loc['area']}", pages, st["places"])
                if not progressed or not use_places and not use_osm:
                    break
        if not dry:
            for name, v in all_lead_tabs(sh).items():
                tabs.setdefault(name, v)
            finish_tabs(sh, tabs, S)
        if pl:
            problems += pl.notes
        if ai:
            problems += ai.notes
        if state["ai_fail"]:
            problems.append("AI failed: template email drafts used for the remaining leads.")
    except SystemExit:
        raise
    except Exception as e:
        problems.append(f"CRASH: {type(e).__name__}: {str(e)[:200]}")
        raise
    finally:
        rej = "; ".join(f"{k[5:]}={v}" for k, v in totals.most_common() if k.startswith("rej: "))[:380]
        skipped_en = ", ".join(f"{k}={v}" for k, v in O.STATS.items() if v)
        okc = ", ".join(f"{k}={v}" for k, v in O.OK.items() if v)
        summ = (f"added={totals['added']}, businesses_seen={totals['places']}, searches={searches_done}, "
                f"minutes={(time.time() - t0) / 60:.1f}" + (f" | rejected: {rej}" if rej else "")
                + (f" | enrich ok: {okc}" if okc else "") + (f" | enrich skipped: {skipped_en}" if skipped_en else ""))
        try:
            retry(lambda: run_ws.append_row([datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), summ,
                                             searches_done, " | ".join(problems)[:900]]))
        except Exception:
            pass
        print("Done:", summ)
        if problems:
            print("Problems:", " | ".join(problems))


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
