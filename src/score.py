"""Scoring for local-business leads. Every threshold/weight comes from the Rules tab."""


def score(d, S):
    """d: fit(1-5), reviews, rating, has_website, email, email_type, instagram, other_social, phone, gap_sev, priority."""
    w = S.num
    niche = w("W_NICHE_BUDGET", 30) * max(0, min(5, d["fit"])) / 5
    r = d["reviews"]
    est = 0.7 if r is None else 1.0 if 30 <= r <= 400 else 0.7 if (15 <= r < 30 or 400 < r <= 600) else 0.4 if r >= 8 else 0.1
    established = w("W_ESTABLISHED", 15) * est
    website = w("W_WEBSITE", 10) * (1.0 if d["has_website"] else 0.0)
    c = 0.0
    if d["email"]:
        c = 0.7 + (0.3 if d["email_type"].startswith("Business") else 0.1)
        c += {"valid": 0.1, "risky": -0.1}.get(d.get("email_status"), 0.0)
    if d["instagram"]:
        c += 0.2
    if d["other_social"]:
        c += 0.1
    if d["phone"]:
        c += 0.1
    contact = w("W_CONTACT", 20) * min(c, 1.0)
    gap = w("W_SOCIAL_GAP", 15) * d["gap_sev"]
    rt = d["rating"]
    rep = w("W_REPUTATION", 5) * (0.5 if rt is None else 1.0 if rt >= 4.5 else 0.8 if rt >= 4.0 else 0.5 if rt >= 3.5 else 0.2)
    loc = w("W_LOCATION", 5) * {1: 1.0, 2: 0.8, 3: 0.6}.get(d["priority"], 0.6)
    return round(min(100, niche + established + website + contact + gap + rep + loc))


def tier_of(sc, S):
    return "A" if sc >= S.num("TIER_A_MIN", 72) else "B" if sc >= S.num("TIER_B_MIN", 55) else "C"


def social_gap(soc, igs):
    """Returns (severity 0-1, plain-English gap). Facts only."""
    has_ig, has_fb = "Instagram" in soc, "Facebook" in soc
    if not has_ig and not has_fb:
        return 1.0, "no Instagram or Facebook found on their website"
    if igs:
        if igs["posts30"] < 4:
            return 0.85, f"their Instagram posted only {igs['posts30']}x in the last 30 days"
        if igs["engagement"] < 1.0:
            return 0.8, f"their Instagram engagement is only {igs['engagement']}%"
        return 0.15, "their Instagram looks active"
    if has_ig:
        return 0.5, "they have Instagram but activity could not be measured"
    return 0.6, "no Instagram found (Facebook only)"


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def pitch(template, facts):
    try:
        return template.format_map(_Safe(facts))
    except Exception:
        return f"{facts.get('name', '')}: {facts.get('gap', '')}. Offer a free 30-60s sample reel."
