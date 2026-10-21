# habermk

A Macedonian anti-clickbait micro-news bot, in the spirit of the Turkish
"Boşuna Tıklama". It takes the top stories on [vesti.mk](https://vesti.mk),
reads the **full original article**, finds the fact the headline hides and
writes it as **one Macedonian sentence**. That sentence goes to Telegram and
Bluesky (Facebook in Phase 2), always with the source outlet and a link.

- **Free to run:** GitHub Actions (public repo) plus free AI tiers (Groq, Gemini).
- **No invented facts:** the model must copy an evidence sentence that appears
  word for word in the article. Every number and name in its sentence must be
  in the article too. Otherwise the story is skipped.
- **Your approval first:** drafts come to your private Telegram chat with
  ✅ / ❌. One variable (`APPROVAL_MODE=auto`) turns on full auto.
- **Never twice:** stable cluster ID, plus same-URL and similar-title checks.
  State is saved and pushed after every single post, per platform.
- **Private where it matters:** the bot's memory on the public `state` branch
  is encrypted (STATE_KEY) and keeps no history; secrets are scrubbed from
  logs, stored errors and alerts.
- **Under your control:** a 🗑 "delete everywhere" button under every post,
  `/pause` `/resume` `/status` in Telegram, a daily overview, throttled alerts.

Setup: **[docs/SETUP.md](docs/SETUP.md)** (step by step) ·
Plan and status: **[docs/ROADMAP.md](docs/ROADMAP.md)**

## How a run works

```
cron */15 ─► read ✅/❌ presses ─► vesti.mk top stories ─► dedupe
          ─► full text (trafilatura, robots.txt respected) ─► model (fallback chain)
          ─► checks (one sentence, Cyrillic, length, evidence, names, numbers)
          ─► draft to you  ──✅──► Telegram │ Bluesky │ Facebook (each on its own)
```

## Code

| Path | What |
|---|---|
| `src/habermk/sources/vesti.py` | vesti.mk parser (cluster id, outlets, article count) |
| `src/habermk/extract.py` | article text (trafilatura → JSON-LD → meta) |
| `src/habermk/llm/` | prompt, providers (Groq, Gemini, optional Claude), fallback router |
| `src/habermk/validate.py` | every check before anything is posted |
| `src/habermk/dedupe.py`, `state.py` | duplicates; state on the `state` branch |
| `src/habermk/approval.py` | Telegram drafts and buttons |
| `src/habermk/publishers/` | Telegram, Bluesky, Facebook |
| `src/habermk/cards.py` | our 1080×1080 image card (Noto Sans, OFL) |
| `src/habermk/main.py` | one run |
| `scripts/` | Phase 0 probe and model evaluation, Facebook token helper |

Settings without secrets are in `config.yaml`. Secrets come only from
environment variables / GitHub Secrets (see `.env.example`).

```
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```
