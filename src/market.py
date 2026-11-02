"""Which edition this repo is. The ONLY code difference between the two bots:
   WORLD = worldwide edition (AU, US, UK, CA, NZ, IE, UAE)      AU = Australia-only edition (+ ABN / AU columns)
Everything else (code, tests) is identical, so fixes can be copied between the two repos (keep this file)."""
import os

MARKET = (os.getenv("LEAD_MARKET") or "AU").strip().upper()          # this repo = Australia-only edition
