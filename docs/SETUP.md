# habermk: setup, step by step

Everything runs on GitHub Actions in this (public) repo. You never need your own
computer on. Do the steps in order; each phase works on its own.

Where things go:
- **Secret** = repo → *Settings* → *Secrets and variables* → *Actions* → tab **Secrets** → *New repository secret*.
- **Variable** = the same page, tab **Variables** → *New repository variable*.

Never paste a key into chat, code or an issue. If one leaks, delete it at the
provider and create a new one.

---

## Phase 0: source probe + model evaluation (no posting)

**Already running:** the `probe` workflow snapshots vesti.mk every 15 minutes
for about 30 hours, then stops by itself. The result is on the `probe` branch:
open `REPORT.md` there (GitHub → branch selector → `probe`). It tells us
whether vesti.mk keeps the same cluster ID while the headline changes.

1. **Actions permission:** *Settings* → *Actions* → *General* → *Workflow permissions* → **Read and write permissions** → *Save*.
2. **Groq key:** https://console.groq.com → sign in → *API Keys* → *Create API Key* → copy → Secret `GROQ_API_KEY`.
3. **Gemini key:** https://aistudio.google.com → *Get API key* → *Create API key* → copy → Secret `GEMINI_API_KEY`.
4. *(Optional, paid quality comparison)* https://console.anthropic.com → *Billing* → add $5 → *API Keys* → *Create* → Secret `ANTHROPIC_API_KEY`.
5. **Run the evaluation:** *Actions* → **eval** → *Run workflow*. Leave "models" empty to use the list in `config.yaml`. To also test Claude, put e.g.
   `groq:openai/gpt-oss-120b,gemini:gemini-2.5-flash,anthropic:claude-haiku-4-5`.
6. When it finishes (about 30–60 min for 40 stories because of the free-tier speed
   limits), open the run → *Artifacts* → download **eval-results** → open the
   `.csv` in Excel. Fill the `YOUR_…` columns: Macedonian quality 1–5, correct
   Y/N, invented fact Y/N.
7. Tell me which model wins. I put it first in `config.yaml` (`llm.models`); the
   others stay as fallback.

## Phase 1: Telegram + Bluesky with your approval

1. **Bot:** in Telegram open **@BotFather** → `/newbot` → a name → a username ending in `bot` → copy the token → Secret `TELEGRAM_BOT_TOKEN`.
2. **Channel:** Telegram → *New Channel* → *Public* → choose the link (e.g. `@badijala_klik`).
   Channel → *Administrators* → *Add Admin* → your bot → allow *Post messages*.
   Variable `TELEGRAM_CHANNEL_ID` = `@badijala_klik` (your link, with `@`).
3. **Your chat ID:** open your bot in Telegram and press *Start*. Then open in a browser
   `https://api.telegram.org/bot<TOKEN>/getUpdates` (your token instead of `<TOKEN>`).
   Find `"chat":{"id":123456789` → Secret `TELEGRAM_ADMIN_CHAT_ID` = that number.
   (Do this before step 6: once the bot runs, it reads these updates itself.)
4. **Bluesky:** create the account → *Settings* → *Privacy and security* → *App passwords* → *Add* → name `habermk` → copy.
   Secrets `BLUESKY_HANDLE` (e.g. `badijalaklik.bsky.social`) and `BLUESKY_APP_PASSWORD`.
5. Variable `APPROVAL_MODE` = `manual`.
6. Variable `BOT_ENABLED` = `true`. From now on the bot runs every 15 minutes, 06:00–23:59 Skopje time.
7. **Test without posting:** *Actions* → **run** → *Run workflow* → dry_run `1`.
   Drafts arrive in your private chat with ✅ / ❌. Nothing is posted in dry-run.
8. **Live:** press ✅ on a draft. Within the next run (≤15–30 min) it appears in
   the channel and on Bluesky. Run the workflow again by hand: no duplicate.

What you will see in your private chat:
- `📝 НАЦРТ` drafts: the sentence, the source, the original headline, the
  evidence sentence copied from the article, and the model used. A `⚠️` line
  asks you to double-check the first word.
- `⚠️ habermk грешки` when something failed (a platform, all models, the source).
  The same problem is reported at most once every 3 hours.
- Drafts you don't answer expire after 6 hours (stale news). An approved post
  that is more than 12 hours old (e.g. approved late at night) is not published.
- When a free AI quota is used up, that model rests until the quota resets and
  the stories wait; they are not thrown away.

**After each publication** you get `📣 ОБЈАВЕНО` with links to the posts and a
**🗑 Избриши насекаде** button. It asks for confirmation, then deletes the post
on Telegram, Bluesky and Facebook and tells you the result per platform. If a
platform refuses (Telegram only allows deleting within 48 hours), you get the
link to delete it by hand.

**Commands** (type them in your chat with the bot; only you can use them):

| Command | What it does |
|---|---|
| `/status` | mode, pause, posts today, drafts waiting, models resting |
| `/pause` | emergency stop: no new drafts and no posts (buttons still work) |
| `/resume` | continue after `/pause` |
| `/help` | list of commands |

The bot reads commands and button presses at its next run (within 15–30 min).

Every evening at 22:30 you get `🗓 Преглед`: stories published (per platform),
your decisions, and how many were skipped and why.

**Full auto later:** change Variable `APPROVAL_MODE` to `auto`. No code change.

Limits (in `config.yaml` → `run`): max 2 posts per run, 30 per day, stories
need ≥4 articles on vesti.mk and must be <8 h old.

## Phase 2: Facebook Page

1. Create the Facebook Page.
2. https://developers.facebook.com → *My Apps* → *Create App* → use case **"Manage everything on your Page"**. It can stay in development mode for your own Page.
3. *Tools* → *Graph API Explorer* → select your app → *Get User Access Token* with
   `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` → copy the token.
4. On any computer with Python (or a GitHub Codespace of this repo):
   ```
   pip install httpx
   python scripts/fb_token.py
   ```
   Paste the App ID, App Secret and token when asked. It prints `FB_PAGE_ID` and
   a Page token with *Expires: Never*. Save both as Secrets `FB_PAGE_ID` and `FB_PAGE_TOKEN`.
5. The next approved draft also appears on the Page. The weekly **healthcheck**
   warns you in Telegram if the token stops working (password change, app removed).

## Phase 3: image cards (already on)

Every post gets our own 1080×1080 card: the sentence, "Извор: <outlet>" and
the date, in Noto Sans, on a dark background. It never uses the outlet's photo.
- **Drafts** show the card above the ✅/❌ message, so you approve the picture too.
- **Telegram**: the card is posted with the sentence, source and link as caption.
- **Bluesky**: the card is the picture of the link card; the post still links to the article.
- **Facebook** keeps the outlet's own link preview.

Change the brand name on the card or switch cards off in `config.yaml` → `cards`.

## Switches at a glance

| Variable | Values | Effect |
|---|---|---|
| `BOT_ENABLED` | `true` / anything else | the bot and the healthcheck run |
| `APPROVAL_MODE` | `manual` / `auto` | drafts wait for ✅, or post directly |
| `DRY_RUN` | `0` / `1` | `1` = never publish (drafts only) |
| `PROBE_ENABLED` | `false` | stops the Phase 0 probe early |

## Optional: ask Time.mk for permission

A ready email (Macedonian + English) is in
[timemk-permission-email.md](timemk-permission-email.md). With their written
consent, their RSS could become a second trend signal.

## Legal reminders

- Every post names the outlet and links the article (Art. 52 copyright law).
- We write our own one sentence; no photos or paragraphs are copied.
- Put a contact for corrections in the channel/profile bio.
- This is not legal advice. Before switching to `auto`, consider a short
  consult with a Macedonian media lawyer.
