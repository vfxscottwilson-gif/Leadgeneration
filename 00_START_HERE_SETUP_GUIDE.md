# START HERE: Setup Guide (about 30 minutes, $0)

This bot finds Australian businesses that can pay you $500 to $1,000+ per project (surgeons, dentists, clinics, real estate agencies, showrooms, builders, solar, migration agents and more). It finds their public emails and social links, checks the emails, scores each lead, writes a personalised email draft, and saves everything into a Google Sheet, one tab per niche, best leads first. It runs by itself every day on GitHub. No credit card needed.

---

## A. What every file is (so nothing is confusing)

```
au-lead-bot/
├── 00_START_HERE_SETUP_GUIDE.md      <- THIS FILE. Read first.
├── README.md                          <- short front page GitHub shows
├── requirements.txt                   <- list of free Python libraries (installed automatically)
├── .gitignore                         <- stops key files being uploaded by mistake
│
├── .github/
│   └── workflows/
│       └── run-lead-bot.yml           <- THE FILE THAT RUNS THE AUTOMATION (daily + "Run workflow" button)
│
└── src/                               <- the bot's code. You never need to edit these.
    ├── leadbot.py                     <- MAIN PROGRAM (the workflow runs this one)
    ├── defaults.py                    <- first-time contents for your sheet: niches, areas, rules, columns
    ├── osm.py                         <- FREE lead finder (OpenStreetMap)
    ├── enrich.py                      <- reads business websites for emails + social links (free)
    ├── optional.py                    <- OPTIONAL helpers: Jina, Hunter, ZeroBounce, Apify, Apollo, Instagram
    ├── score.py                       <- scores each lead out of 100 and sets Tier A/B/C
    ├── drafts.py                      <- writes the email draft (AI or template)
    ├── ai.py                          <- talks to your free AI keys; switches key/provider if one fails
    └── places.py                      <- OPTIONAL Google Maps source (needs billing; leave alone)
```
Only ONE thing starts the bot: `.github/workflows/run-lead-bot.yml`. It installs `requirements.txt`, then runs `src/leadbot.py`. All the other code files are tools that `leadbot.py` uses.

---

## B. MANDATORY setup (all free, all easy)

You need exactly three secrets: **SHEET_ID**, **GOOGLE_SA**, **AI_API_KEYS**.

### Step 1. Make your Google Sheet and get SHEET_ID
1. Go to sheets.google.com and create a **new blank spreadsheet**. Name it e.g. "AU Leads". (Use a NEW sheet, not an old one.)
2. Look at the address bar: `https://docs.google.com/spreadsheets/d/`**`1AbC...xyz`**`/edit`
3. The long text between `/d/` and `/edit` is your **SHEET_ID**. Copy it somewhere safe.

### Step 2. Make the Google "robot account" and get GOOGLE_SA
This lets the bot write into your sheet. It is free and needs no billing.
1. Go to console.cloud.google.com (sign in with the same Google account). Top bar > project picker > **New Project** > name it "lead-bot" > **Create**.
2. Left menu > **APIs & Services > Library**. Search **Google Sheets API** > **Enable**. (Also search **Google Drive API** > **Enable**, it is harmless and avoids edge-case errors.)
3. Left menu > **IAM & Admin > Service Accounts > Create service account**. Name: "lead-bot" > **Create and continue** > skip the optional steps > **Done**.
4. Click the new service account (its email looks like `lead-bot@lead-bot-123.iam.gserviceaccount.com`). Open the **Keys** tab > **Add key > Create new key > JSON > Create**. A `.json` file downloads. **Keep it private, never upload it to GitHub.**
5. **Copy the `client_email`** (the robot's email address; also shown on the service account page).
6. Go back to your Google Sheet > **Share** > paste that robot email > set **Editor** > uncheck "notify" > **Share**.
7. Open the downloaded `.json` file with Notepad/TextEdit. **Select ALL the text (it starts with `{` and ends with `}`)**. This whole text is your **GOOGLE_SA**.

If step 4 says key creation is blocked, you are on a work/school Google account with a policy. Use a normal personal Gmail account instead.

### Step 3. Get free AI keys (AI_API_KEYS)
The AI writes the personalised email drafts. Without it the bot still works and uses a template, but drafts are better with it. Get at least one (two or three is best: if one hits its free limit the bot switches to the next automatically). None need a credit card.
- **Gemini** (easiest): aistudio.google.com/apikey > **Create API key**. Starts with `AIza`.
- **Groq**: console.groq.com/keys > **Create API Key**. Starts with `gsk_`.
- **OpenRouter**: openrouter.ai/keys > **Create Key**. Starts with `sk-or-v1-`. (Free models only; daily limit is small.)

**Format:** ONE secret named `AI_API_KEYS`. Paste one key per line. Never type a model name.
```
AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXX
gsk_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
sk-or-v1-XXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

### Step 4. Put the files on GitHub
1. Create a free account at github.com > **New repository** > name it `au-lead-bot` > choose **Private** > **Create repository**.
2. Unzip `au-lead-bot.zip` on your computer.
3. **Easiest way:** in your new repo click **Add file > Upload files**, then drag the **contents** of the unzipped folder in (the files AND the folders `src` and `.github`). Click **Commit changes**.
4. **Check** that your repo now shows: `00_START_HERE_SETUP_GUIDE.md`, `README.md`, `requirements.txt`, `.gitignore`, the `src` folder and the `.github` folder.
5. **If `.github` did not upload** (hidden folders are sometimes skipped by your computer): in the repo click **Add file > Create new file**, and in the name box type exactly `.github/workflows/run-lead-bot.yml` (typing the slashes creates the folders). Open `run-lead-bot.yml` from the zip in Notepad, copy everything, paste it into GitHub, **Commit changes**.

### Step 5. Add the 3 secrets in GitHub
Repo > **Settings > Secrets and variables > Actions > New repository secret**. Add these one by one (Name, then Secret value, then Add secret):
| Name | Value |
|---|---|
| `SHEET_ID` | the ID from Step 1 |
| `GOOGLE_SA` | the entire JSON text from Step 2 |
| `AI_API_KEYS` | your AI keys, one per line |

### Step 6. Add your sender details (strongly recommended)
Same page > **Variables** tab > **New repository variable**. These print in the email footer (Australian law requires you to identify yourself):
| Name | Example |
|---|---|
| `SENDER_NAME` | Ahmed |
| `AGENCY_NAME` | Your Agency Name |
| `SENDER_ADDRESS` | Your business address or city, state |

### Step 7. First run
1. Repo > **Actions** tab. If asked, click **"I understand my workflows, enable them"**.
2. Click **Run Lead Bot** in the left list > **Run workflow** > green **Run workflow** button.
3. Wait 5-15 minutes. A green tick = success.
4. Open your Google Sheet. New tabs appear: **Rules, Niches, Locations, Playbook, Run Log, Summary, Seen, Searches, Blacklist, Leads Input** plus one lead tab per niche.
5. **Read the Run Log tab first**: it says how many leads were added and exactly why others were rejected.
From now on it runs by itself every day.

---

## C. What you do inside the sheet (no code ever)
| Tab | What to do |
|---|---|
| **Niches** | Switch niches on/off (Yes/No), edit budgets and pitch lines, add a new niche in a new row. |
| **Locations** | Add any suburb or town (Country, State, City, Search Area). Coordinates are filled in for you. |
| **Rules** | Change minimum score, leads per day, minimum budget and more. Every row explains itself. |
| **Leads Input** | Paste any business you found yourself (name, website, Instagram, email, phone, niche, city, state). The bot enriches, scores and files it. This is how you cover surgeons and clinics that the free map misses. |
| **Blacklist** | Paste a business name, email or website you never want to see. |
| **Niche tabs** | Your leads, best first. Use **Status** (New > Contacted > Replied > Client) and **My Notes**. |
| **Playbook** | Who to target and how to work the leads. |

How to read a lead: **Tier A** (best) > B > C. **Social Gap** says why they need you. **Pitch Angle** is your opening line. **Email Draft** is ready to copy. **Email Verified** shows how trusted the email is. **Enrichment** shows which modules helped.

---

## D. OPTIONAL quality multipliers

**The keys listed below are 100% OPTIONAL. Leaving these secret values blank in GitHub Actions will NOT cause errors. The system automatically disables these modules if keys are omitted.**

To add one: Settings > Secrets and variables > Actions > New repository secret, use the exact name shown. Ordered easiest first.

| Secret name | Where to get it | Difficulty | How it improves your leads |
|---|---|---|---|
| *(nothing to add)* **Free email check** | built in | none | Drops emails whose domain cannot receive mail. |
| *(nothing to add)* **Jina Reader** | works without a key | none | Reads JavaScript-heavy websites the normal reader cannot: more emails and social links found, better Social Gap, fills **Website Summary** for better drafts. Optional free key: jina.ai > API key, secret `JINA_API_KEY`. Turn it off with variable `USE_JINA` = `false`. |
| `HUNTER_API_KEY` | hunter.io > sign up > Dashboard > API | easy | Finds a company email when the site shows none, and verifies emails. Small free monthly quota. |
| `ZEROBOUNCE_API_KEY` | zerobounce.net > sign up > API > API Keys | easy | Checks whether the mailbox really exists. Removes bad addresses so your sender reputation stays safe. Small free monthly quota. |
| `APIFY_API_TOKEN` | console.apify.com > Settings > API & Integrations | medium | Measures Instagram activity (posts in 30 days, engagement) so Social Gap is measured instead of guessed. Also set **Rules > USE_APIFY = Yes**. Uses your free monthly credit. |
| `APOLLO_API_KEY` | apollo.io > Settings > Integrations > API | medium | Fills Employee Count and company name. Limited on the free plan. |
| `IG_ACCESS_TOKEN` and variable `IG_USER_ID` | developers.facebook.com (Instagram Graph API) | HARD | Official Instagram activity for business accounts. Skip unless you are technical. |
| `PLACES_API_KEYS` | Google Cloud > Places API (New) | NEEDS BILLING CARD | Adds Google ratings and review counts. Not needed. Skip while you are at $0. |

Free limits change over time: check each site's current free quota.

---

## E. Honest limits of the free version
- The free map (OpenStreetMap) is volunteer-made. It is strong for dentists, real estate, furniture, dealers and law firms and **thin for surgeons and clinics**. It has no Google ratings or review counts, so those columns stay blank. Cover the gap with the **Leads Input** tab.
- Many clinics publish only reception/info emails. The bot flags these: ask for the owner or marketing manager.
- The free email check proves the domain accepts mail, not that the mailbox exists. Only ZeroBounce/Hunter prove that.
- Free AI keys have daily limits. The bot caps drafts per run and falls back to templates, so it never stops.

## F. Australian rules (not legal advice)
Spam Act 2003: identify yourself, include an unsubscribe (the draft footer does), email only businesses where your offer is relevant, honour opt-outs. Health providers: AHPRA/TGA advertising rules (no testimonials, no promoting prescription-only treatments). Check the Do Not Call Register before phoning.

## G. Troubleshooting
| You see | Fix |
|---|---|
| Run is red: "MISSING CORE SETTING" | `SHEET_ID` or `GOOGLE_SA` secret is missing or misspelled (names are exact, capital letters). |
| "APIError 403 / PERMISSION_DENIED" | Sheet is not shared with the robot email as **Editor**, or Google Sheets API not enabled (Step 2.2). |
| "Spreadsheet not found / 404" | Wrong SHEET_ID: copy only the text between `/d/` and `/edit`. |
| "JSONDecodeError" | GOOGLE_SA is incomplete: paste the whole file, from `{` to `}`. |
| "old YouTube lead bot" message | Use a brand-new Google Sheet. |
| Green run but 0 leads | Read **Run Log > Summary**. Common: Rules `MIN_SCORE` too high, or `REQUIRE_CONTACT` too strict (try `any`). |
| "Overpass servers failed" | The free map servers were busy. Nothing is lost; it retries tomorrow, or click Run workflow again later. |
| Emails say "Your name" | Add the Step 6 variables. |
