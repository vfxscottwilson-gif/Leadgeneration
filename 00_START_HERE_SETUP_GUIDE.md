# START HERE: Australia-only Lead Bot (v5, about 30 minutes, $0)

This bot finds **Australian** businesses that can pay you $500 to $1,000+ per month, plus Australian YouTube
creators.

**What it does for each business:**
1. Finds the public emails, phone, socials, ABN facts and decision-maker name (facts only).
2. Scores the lead.
3. Writes a short **Lead Insight**: who they are and their likely pains.
4. Adds the lead to **one Google Sheet**, one tab per niche, always below the last row.

It never writes emails; your outreach bot does (`CONTRACT.md`). The worldwide edition is a separate repo with its
own sheets. The code is the same; only `src/market.py` says `AU`.

## Setup, step by step

1. **Robot account (`GOOGLE_SA`):**
   - console.cloud.google.com → New Project → enable **Google Sheets API**.
   - **IAM & Admin → Service Accounts → Create** → open it → **Keys → Add key → JSON**.
   - Copy the account's email (`…@….iam.gserviceaccount.com`).
   - Open the JSON file in Notepad and copy ALL its text. That text is the `GOOGLE_SA` value. Never upload the file.
2. **The sheet:** create a blank Google Sheet named, for example, `AU Leads`.
   - **Share** it with the robot email as **Editor** (untick Notify).
   - Copy its id: the part of the URL between `/d/` and `/edit`. The whole URL also works.
3. **GitHub:**
   - **Create the repo:** new **public** repo (unlimited free Actions minutes; there are no secrets in the files).
   - **Upload:** the contents of `au-only-lead-bot.zip`, including the `src`, `tests` and `.github` folders.
4. **Secrets:** go to **Settings → Secrets and variables → Actions → New repository secret**, one key per secret
   (exact names and formats: [SECRETS_GUIDE.md](SECRETS_GUIDE.md)).
   - `GOOGLE_SA`: the JSON text.
   - `SHEET_ID_AU_ONLY`: the sheet id or URL. The old `SHEET_ID` also works.
   - Recommended: `GEMINI_API_KEY_1` (Lead Insight) and `ABN_GUID` (free; official ABN, GST and business age).
     Register at abr.business.gov.au/Tools/WebServices.
   - Best optional upgrade: `SERPER_API_KEY` (Google rating + reviews, which makes PRIME leads possible).
5. **Run:**
   - Go to **Actions → Run AU Lead Bot → Run workflow**. `setup` runs first, then the 6 `collect` jobs **one after
     another** (they share one sheet), then `finish`.
   - The first lines of each job's log are the **registration report**: every key you added should say
     `registered`.
6. **Open the sheet:** tab 1 is **Stats** (totals, today, PRIME, last run, run health, keys registered). Then come
   one tab per niche and the control tabs.

## Working the leads

- **New leads:** always appear **at the bottom** of a niche tab. Rows are never sorted, moved or rewritten.
  - Use `Status` and `My Notes` freely, add your own columns, or reorder columns.
  - To sort for yourself, use Data → **Filter views**.
- **Australian columns** (`ABN`, `ABR Entity Name`, `GST Registered`, `Business Age (yrs)`, `Phone Type`,
  `AU Timezone`): see [AU_EDITION.md](AU_EDITION.md). Check mobiles against the Do Not Call Register before
  cold calling.
- **Rules:** `Niches`, `Locations` and `Rules` tabs control what is searched. Every Rules row explains itself.

## Troubleshooting

| You see | Fix |
|---|---|
| `ignored: <KEY> (bad format …)` | Re-paste the key with no quotes or spaces (or set the Variable `KEY_CHECK` = `warn`). |
| `no access. Share it with the service-account email as Editor` | Share the sheet with the robot email. |
| `SKIP sheet: another job is writing this sheet right now` | A second run or a local run overlapped. Nothing was written, and the next run continues. |
| `AI quota hit (429)` in Run health | The free AI limit was reached. Add `GEMINI_API_KEY_2`, or ignore it: leads still get a fact-only insight. |
| Green run but 0 leads | Read the **Run Log** tab: every reject reason with counts. |
