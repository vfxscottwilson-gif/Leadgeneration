# AU Lead Bot: Australia-only edition ($0)

Daily lead generation for **Australian** businesses that can pay $500-$1,000+/month, plus Australian YouTube creators
($1k-2k):
- **Niches:** surgeons, dentists, clinics, independent real estate, boutique gyms, fine dining / restaurant groups,
  showrooms, builders and more.
- **What it writes per lead:**
  - Facts-only contact data: company, decision maker, personal/generic emails, phone, socials, address, website.
  - ABN facts.
  - Segment + ICP score (≥ 7/10).
  - A short **Lead Insight**.
- **Where:** ONE Google Sheet (`SHEET_ID_AU_ONLY`), one tab per niche, **append-only**: rows are never sorted or
  rewritten. **No email drafts.** The outreach bot reads the sheet via `CONTRACT.md`.

**Start here:**
- [`00_START_HERE_SETUP_GUIDE.md`](00_START_HERE_SETUP_GUIDE.md): setup.
- [`SECRETS_GUIDE.md`](SECRETS_GUIDE.md): one GitHub secret per key.
- [`AU_EDITION.md`](AU_EDITION.md): AU columns, leads/day, optional APIs.
- [`UPGRADE_V5.md`](UPGRADE_V5.md): what changed, tests, risks.

**Running it:**
- **GitHub Actions:** `.github/workflows/run-lead-bot.yml`. Its jobs (NSW+ACT, VIC+TAS, QLD, WA+SA+NT, YouTube,
  imports) run **one at a time**, because they share one sheet.
- **Try it without Google:** `python src/leadbot.py --local`. Tests: `python src/selftest.py` and
  `python -m unittest discover -s tests`.
- **Same code as the worldwide edition.** Only `src/market.py` differs (`MARKET = "AU"`).
