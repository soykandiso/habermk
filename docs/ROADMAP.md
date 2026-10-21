# habermk roadmap

Status as of 21 Oct 2026. ✅ done and merged · ⏳ waiting on you · 🔜 next · 💡 later / optional.

## Where we are

| Phase | What | Status |
|---|---|---|
| 0 | vesti.mk parser, cluster-ID probe, full-text extraction, model evaluation script | ✅ code · ⏳ eval needs your keys |
| 1 | Telegram + Bluesky, drafts with ✅/❌, state, duplicates, platform isolation | ✅ code · ⏳ needs accounts |
| 2 | Facebook Page publisher, token helper, weekly token check | ✅ code · ⏳ needs Page + token |
| 3 | Our own 1080×1080 image cards (Noto Sans, OFL) | ✅ |
| — | Hardening, takedown, commands, digest (see below) | ✅ |
| 4 | X (paid API) | 💡 your decision |

### Verified on the live site (from GitHub's servers)
- vesti.mk was **redesigned** after the September research. The parser now reads the
  new markup (`data-tv-cluster`): 36 stories with outlet, article count, age,
  category and related outlets.
- Full text: **10 of 10** top stories gave usable text (Телма refuses; the bot
  falls back to the next outlet). Re-checked every ~4 h in `EXTRACT.md` on the
  `probe` branch.

### Hardening done in this round
- Secret-safe logs: request URLs (which contain the Telegram token) are never
  logged; the Actions logs of this repo are public.
- Every post names a source: the outlet, or the article's domain if the name is missing.
- Free AI quota used up → that model **rests** until the quota resets (kept
  across runs); stories wait instead of being thrown away; no 90-second sleeps.
- One broken article can't stop the run; the same problem is alerted at most every 3 h.
- Approved posts more than 12 h old are not published (stale news).
- **🗑 Takedown**: every published post comes with a "delete everywhere"
  button (with confirmation).
- **/pause, /resume, /status, /help** in your chat with the bot.
- Daily overview at 22:30; per-run summary in the Actions job page.
- **Encrypted state** (STATE_KEY) on the public `state` branch, one commit
  only (no history, no repository bloat); no-op saves write nothing.
- **Secret scrubbing** on every log line, stored error and alert (bot token
  in Telegram URLs, Facebook tokens in Graph URLs, any *_TOKEN/_KEY/_PASSWORD).
- Tests for the scripts you run (eval table, health check, Facebook token
  helper) and actionlint + shellcheck on every workflow in CI.
- Fixed: old button presses (Telegram won't "answer" them after a few
  minutes) aborted the processing of later presses.

## ⏳ Waiting on you (in this order)
1. Actions permission: Read and write (docs/SETUP.md, Phase 0 step 1).
2. Secrets `GROQ_API_KEY`, `GEMINI_API_KEY` → run the **eval** workflow → score the CSV.
3. Pick the final channel name/handle (the card says "Бадијала клик" for now).
4. Telegram bot + channel, Bluesky app password, `STATE_KEY` → `BOT_ENABLED=true` → dry run → live with approval.
5. Optional: send the Time.mk email (docs/timemk-permission-email.md).
6. Before `APPROVAL_MODE=auto`: about a week of manual approval, and a short consult with a media lawyer.

## 🔜 Next (I do these as soon as the inputs exist)
- **Model choice from your eval scores**: put the winner first in `config.yaml`,
  tune the prompt on the stories it got wrong, and add those stories as test cases.
- **Tune the story filters with 24 h of probe data**: `max_age_hours` (now 8)
  and `min_outlets` (now 4). The first snapshots: 23 of 36 stories pass today's filters.
- **Check cluster-ID stability** in the probe report (headline changes under one
  ID; URLs moving between IDs). If IDs prove unstable, lean harder on the
  URL/title duplicate checks.
- **First live week**: read the digest and the skip reasons; tighten or loosen
  the checks where they reject good sentences or let weak ones through.

## 💡 Later / optional
- **Instant approvals**: a free Cloudflare Worker receives the button press and
  starts the run at once (today: up to 15–30 min delay).
- **X (Phase 4)**: pay-per-use; without links ~$13.50/month at 30 posts/day.
- **Time.mk RSS** as a second trend signal, only with their written permission.
- **Weekly "most hidden facts" post**: a summary of the week's best sentences.
- **Corrections note**: when you delete a post, optionally publish a short correction.

## Decisions log
| Date | Decision | Why |
|---|---|---|
| 29 Sep | Source: vesti.mk, not Time.mk | Time.mk terms forbid robots; vesti.mk allows them |
| 29 Sep | All MK + region stories; one switch for auto mode | your choice |
| 29 Sep | Run on GitHub Actions, state on a `state` branch | €0, no server |
| 21 Oct | Parser keyed on `data-tv-cluster` | vesti.mk redesign; numeric IDs in the markup |
| 21 Oct | Cards on Telegram and as the Bluesky link-card image; Facebook keeps the outlet preview | keep a clickable source link everywhere |
| 21 Oct | Rest a model on long rate limits instead of skipping stories | free quotas (Groq ≈ 50 articles/day) |
| 21 Oct | Encrypt the state, single-commit branch | public repo: rejected drafts and deleted posts must not stay readable |
