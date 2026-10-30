"""Outreach email draft per lead. Uses your free AI key when available; otherwise (or on ANY AI failure) a
fact-based template. Never raises."""
import os
import re

FOOT = "If this isn't relevant, just reply 'no thanks' and I won't email you again."


def _env(k, d=""):
    return (os.getenv(k, "") or d).strip()


def _sign():
    me, ag, addr = _env("SENDER_NAME", "Your name"), _env("AGENCY_NAME", "Your agency"), _env("SENDER_ADDRESS")
    return f"\n\n{me}\n{ag}" + (f"\n{addr}" if addr else "") + f"\n\n{FOOT}"


def _you(gap):
    """The gap text is written about them; the email speaks to them."""
    return (gap.replace("their ", "your ").replace("they have", "you have").replace("they ", "you ")
            .replace("Their ", "Your "))


def template(f):
    f = dict(f, gap=_you(f["gap"]))
    rep = f"{f['reviews']} Google reviews at {f['rating']} stars is a strong reputation. " if f.get("reviews") else ""
    body = (f"Hi {f['name']} team,\n\nI came across {f['name']} in {f['city']}. {rep}One thing I noticed: {f['gap']}.\n\n"
            f"We make short social videos and content for local businesses like yours. I'd like to send you a free "
            f"30-60 second sample reel made for {f['name']}, no strings attached.\n\nWould that be useful?")
    return f"Free sample reel for {f['name']}", body


def _ok(subject, body):
    words = len(body.split())
    return (5 <= len(subject) <= 90 and 40 <= words <= 140 and not re.search(r"https?://|www\.", body)
            and re.search(r"\bfree\b", body, re.I) and "!" not in subject and body.count("!") <= 1)


def build(ai, f):
    """Returns (subject, body, ai_used, ai_failed)."""
    failed = False
    if ai is not None:
        try:
            raw = ai.generate(
                "Write a short, friendly cold email (60-100 words) from a social-media/video agency to this Australian "
                "business. Use ONLY the facts below; invent nothing (no results, clients, numbers). Mention the free "
                "30-60 second sample reel. End with one easy question. No links, no emojis, no signature.\n"
                f"Business: {f['name']} ({f['niche']}, {f['city']}). Google rating: {f.get('rating') or 'unknown'}, reviews: "
                f"{f.get('reviews') or 'unknown'}. Social gap observed: {_you(f['gap'])}. Website says: {f.get('summary') or 'n/a'}.\n"
                "Output exactly: first line 'SUBJECT: <subject>', then a blank line, then the email body.", 400)
            m = re.match(r"\s*SUBJECT:\s*(.+?)\s*\n+(.*)", raw, re.S | re.I)
            if m:
                subject, body = m.group(1).strip().strip('"'), m.group(2).strip()
                if _ok(subject, body):
                    return subject, body + _sign(), True, False
        except Exception:
            failed = True
    try:
        s, b = template(f)
    except Exception:
        s, b = "Free sample reel", "Hi there,\n\nWe'd like to send you a free 30-60 second sample reel. Would that be useful?"
    return s, b + _sign(), False, failed
