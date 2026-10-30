# AU Lead Bot ($0)

Daily lead generation for Australian local businesses (surgeons, dentists, clinics, real estate, showrooms, builders and more) that can pay $500 to $1,000+ per project. Writes scored leads, verified emails, social links and an email draft into a Google Sheet.

**Start here: [`00_START_HERE_SETUP_GUIDE.md`](00_START_HERE_SETUP_GUIDE.md)**

- Runs on GitHub Actions: `.github/workflows/run-lead-bot.yml`
- Main program: `src/leadbot.py`
- Mandatory secrets: `SHEET_ID`, `GOOGLE_SA`, `AI_API_KEYS`. Everything else is optional and switches itself off when blank.
