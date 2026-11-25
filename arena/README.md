---
title: Grand Theft GPU Blind Arena
emoji: 🏎️
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
short_description: Play two mystery $100 AI-built GTA games and vote blind
pinned: false
---

# Grand Theft GPU — Blind Play & Vote Arena

Play two browser-based *Grand Theft GPU* builds side by side without knowing which model built which, then cast a blind pairwise vote on the four rubric questions from `scoring/checklist.md`:

1. **Plays better**
2. **Looks better**
3. **Better main character**
4. **Overall**

Each visitor receives a randomized, server-signed A/B assignment (50/50 counterbalanced). Real contender identities stay server-side until after the ballot is submitted.

## Prepare builds from a race

From the repo root (packages `kimi` and `opus` builds into opaque folders, strips the 650 MB shared `assets/gt-gpu/` directory so it loads from the pinned Hugging Face dataset CDN, and scans for identity leaks):

```bash
uv run python arena/prepare.py --race-id v15-full-100usd-001 --link-local-assets
```

## Run locally

```bash
uv run --with fastapi --with "uvicorn[standard]" uvicorn app:app --app-dir arena --port 7860
```

Open `http://127.0.0.1:7860`.

## Deploy to Hugging Face Spaces

1. Re-run `prepare.py` **without** `--link-local-assets` so shared assets stream from Hugging Face CDN instead of bloating the Space repo:

   ```bash
   uv run python arena/prepare.py --race-id v15-full-100usd-001
   ```

2. Create a private or public Docker Space on free `cpu-basic` hardware (and optionally a private dataset for durable vote backups):

   ```bash
   hf repos create <namespace>/grand-theft-gpu-arena --type space --space-sdk docker --public --exist-ok
   hf repos create <namespace>/grand-theft-gpu-votes --type dataset --private --exist-ok
   ```

3. Set Space secrets (`ARENA_SECRET` for signing session cookies; `ARENA_MANIFEST_JSON` so the Files tab on a public Space never reveals which opaque build belongs to which model; `HF_TOKEN` + `VOTE_DATASET_REPO` for durable vote sync across Space restarts):

   ```bash
   hf spaces secrets add <namespace>/grand-theft-gpu-arena \
     -s ARENA_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
     -s ARENA_MANIFEST_JSON="$(python3 -c 'import json; print(json.dumps(json.load(open("arena/builds/manifest.json")), separators=(",", ":")))')" \
     -s VOTE_DATASET_REPO="<namespace>/grand-theft-gpu-votes" \
     -s HF_TOKEN
   ```

4. Upload the `arena/` directory (excluding local `data/` and `builds/manifest.json`):

   ```bash
   hf upload <namespace>/grand-theft-gpu-arena arena/ . --repo-type space --exclude "data/*" --exclude "builds/manifest.json" --exclude "__pycache__/*"
   ```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ARENA_SECRET` | random key saved in `data/` (lost when the Space restarts) | HMAC secret for signing session cookies (set persistently in production) |
| `ARENA_MANIFEST_JSON` | *(read from `builds/manifest.json`)* | Keep contender mapping secret even on a public Space |
| `MIN_PLAY_SECONDS` | `60` | Active seconds required in **each** build before unlocking the vote form |
| `REVEAL_ON_VOTE` | `1` | Set to `0` to withhold model reveal & community tallies until launch day |
| `VOTE_DATASET_REPO` | *(empty)* | Optional HF Dataset repo (`ns/name`) to persist and restore `votes.jsonl` |
| `HF_TOKEN` | *(empty)* | Write token for `VOTE_DATASET_REPO` |
| `MAX_SESSIONS_PER_IP_PER_HOUR` | `30` | New sessions one IP may open per hour (`0` disables) |
| `MAX_VOTES_PER_IP_PER_DAY` | `20` | Ballots one IP may cast per day (`0` disables) |
| `TRUSTED_PROXY_HOPS` | `1` | Which `X-Forwarded-For` entry, counted from the right, is the client. The first request on each worker logs the chain's shape (`public`/`private` per hop, no addresses); set this so it picks the public hop |

## What gets recorded

- **Votes** (`votes.jsonl`): picks per question (blind slot and de-blinded contender), verified active seconds in each build, race id, and a keyed hash of the IP (for the vote cap; the raw IP is never stored).
- **Input logs** (`events/events-<boot>-<pid>.jsonl`, one file per process boot so restarts never overwrite pushed logs): every few seconds, a batch of `[ms_since_page_load, kind, code]` events per session and slot, tagged with the opaque build, the contender, and the slot's play seconds so far. Kinds: `start` (code = epoch ms), `kd`/`ku` (key down/up by physical key, e.g. `KeyW`), `md`/`mu` (mouse button), `lock`/`unlock` (pointer lock), `focus`/`blur`, `hidden`/`visible`, `exit`. Capped at 200,000 events per session. Non-voters are logged too.

Both sync to `VOTE_DATASET_REPO` when set. Play time counts only while the page is visible and the vote dialog is closed, and accrues at most in real time across both builds combined.
