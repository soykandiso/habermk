# Troubleshooting

The bot reports problems in your private Telegram chat (`⚠️ habermk грешки`,
at most once every 3 hours per problem) and in each run's page under
*Actions → run* (the summary at the bottom). Find the message below.

## The bot does nothing
- *Actions → run* shows no runs: the variable `BOT_ENABLED` is not `true`, or
  GitHub disabled scheduled workflows after 60 days without activity. Fix: open
  *Actions*, select **run**, and press *Enable workflow* if GitHub asks.
- Runs are green but no drafts arrive: it may be outside 06:00–23:59 Skopje
  time, the bot may be paused (`/status` → "Пауза: да" → send `/resume`), or
  all AI models may be resting after a used-up free quota (`/status` →
  "Модели на пауза"). The stories wait; nothing is lost.
- Drafts come hours apart, or *Actions → run* shows long gaps between runs:
  GitHub's schedule alone runs only every few hours. Set up the external
  15-minute clock (docs/SETUP.md, "Required: a reliable 15-minute clock").
  If it is set up, check cron-job.org: errors 401/403 mean the token expired.
- *Actions → run* never shows runs with the event `schedule` after a change
  to a workflow file: GitHub took about 4.5 hours to start the schedule here.
  The external clock works regardless.

## Messages from the bot

| Message contains | Meaning | What to do |
|---|---|---|
| `Secret STATE_KEY is missing` | the encryption key secret is not set | add `STATE_KEY` (docs/SETUP.md, Phase 1) |
| `STATE_KEY does not match the saved state` | the key was changed or mistyped | put the old key back. If it is lost: delete the `state` branch (*Code → branches*); the bot starts fresh, and stories from the last hours could be drafted again |
| `telegram approvals: … Conflict … webhook` | someone set a webhook on the bot | open `https://api.telegram.org/bot<TOKEN>/deleteWebhook` once in a browser |
| `telegram … Forbidden: bot is not a member` / `not enough rights` | the bot is not an admin of the channel | channel → *Administrators* → add the bot with *Post messages* |
| `telegram … chat not found` | wrong `TELEGRAM_CHANNEL_ID` or `TELEGRAM_ADMIN_CHAT_ID` | check the `@` name of the channel and your chat number (SETUP, Phase 1 step 3) |
| `bluesky … Invalid identifier or password` | app password revoked or handle changed | create a new app password, update `BLUESKY_APP_PASSWORD` / `BLUESKY_HANDLE` |
| `bluesky … RateLimitExceeded` | too many logins in a day (limit 300) | nothing; it recovers by itself |
| `facebook … OAuthException` / `Error validating access token` | the Page token stopped working (password change, app removed) | run `scripts/fb_token.py` again and update `FB_PAGE_TOKEN` |
| `all models failed … is not set` | an AI key secret is missing | add `GROQ_API_KEY` and/or `GEMINI_API_KEY` |
| `all models failed … 401` / `invalid api key` | an AI key was revoked | create a new key at the provider, update the secret |
| `vesti.mk: … 0 parsed stories` / `no clusters found` | vesti.mk changed its page again | nothing to do on your side: the bot does not post until the parser is fixed (the `probe` branch keeps the page that failed) |
| `state push failed` | GitHub refused the bot's push | *Settings → Actions → General → Workflow permissions* → **Read and write** |
| `delete telegram … message can't be deleted` | Telegram allows deleting only for 48 hours | delete it by hand with the link in the message |

## A wrong post went out
Press **🗑 Избриши насекаде** under its `📣 ОБЈАВЕНО` copy in your chat and
confirm. The result comes at the next run (15–30 min). If you need it gone
immediately, also delete it by hand on the platform. To stop everything at
once, send `/pause`.
