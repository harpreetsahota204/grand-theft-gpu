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
| `MAX_SESSIONS_PER_IP_PER_HOUR` | `300` | New sessions one IP may open per hour (`0` disables). A meetup or office shares one IP: raise it for a bigger crowd |
| `MAX_VOTES_PER_IP_PER_DAY` | `100` | Ballots one IP may cast per day (`0` disables) |
| `TRUSTED_PROXY_HOPS` | `1` | Which `X-Forwarded-For` entry, counted from the right, is the client. The first request on each worker logs the chain's shape (`public`/`private` per hop, no addresses); set this so it picks the public hop |

## What gets recorded

- **Votes** (`votes.jsonl`): picks per question (blind slot and de-blinded contender), verified active seconds in each build, race id, and a keyed hash of the IP (for the vote cap; the raw IP is never stored).
- **Input logs** (`events/events-<window>-<process>-<n>.jsonl`): every few seconds, a batch of `[ms_since_page_load, kind, code]` events per session and slot, tagged with the opaque build, the contender, the slot's play seconds so far, and `epoch_ms` (the page's navigation start, so `epoch_ms + ms` is an absolute time). Kinds: `start` (code = epoch ms), `kd`/`ku` (key down/up by physical key, e.g. `KeyW`), `md`/`mu` (mouse button; code `button,x,y` with the pointer as a 0-1 fraction of the viewport), `mv` (mouse movement summed over 100 ms, code `dx,dy`: how pointer-locked games aim), `lock`/`unlock` (pointer lock), `focus`/`blur`, `hidden`/`visible`, `exit`. Capped at 200,000 events per session per worker. Non-voters are logged too.
- **Gameplay snapshots** (`frames/frames-<window>-<process>-<n>.jsonl`): a 480-px-wide JPEG of the game canvas every 2 s while the tab is visible, base64 in `jpeg_b64`, with `epoch_ms` and `t_ms` on the same clock as the input log, plus build, contender, slot and play seconds. The copy is taken right after the game's own animation-frame callback, so WebGL games don't come out black. Capped at 4,000 per session (over an hour of play), and at a burst of 10 plus one per second since the session began, so a script can't upload faster than real play.

Event and snapshot files start fresh every 10 minutes (or at 32 MB) under a name unique to each process, so a restart never overwrites anything already pushed. Inputs and snapshots skip the SQLite write lock, so heavy logging never slows heartbeats or votes. When the data disk drops below 2 GB free, inputs and snapshots are dropped; votes still save.

All of it syncs to `VOTE_DATASET_REPO` when set, every 2 minutes and once more on shutdown. Once a file's 10-minute window has closed and it is safely on the Hub, it is deleted from the Space, so the Space's disk holds only what hasn't synced yet. A crash, as opposed to a clean restart, can lose up to 2 minutes of logs. Play time counts only while the page is visible and the vote dialog is closed, and accrues at most in real time across both builds combined.

### Export to COCO4GUI

`export_coco4gui.py` joins snapshots, inputs and votes into a [COCO4GUI](https://github.com/harpreetsahota204/gui_dataset_creator) dataset per race (`<out>/<race_id>/images/<sid>/<slot>_<n>.jpg` + `annotations_coco.json`), ready for FiftyOne. It reads one play at a time, so memory stays flat; a race past `--max-images` (default 50,000) is split into `annotations_coco_00001.json`, `_00002.json`, ... with no play split across parts:

```bash
uv run python arena/export_coco4gui.py --repo <ns>/<votes-dataset> --out-dir out   # or --data-dir arena/data/jsonl
```

- **Images:** one per snapshot. Each blind play of one build is a sequence (`sequence_id` = `<sid>_<slot>`, `sequence_position` = frame order). Extra fields: race, build, contender, slot, play seconds, keys and buttons held, pointer lock, focus, and that build's vote result per question (`vote_overall`: `win`/`loss`/`tie`).
- **Annotations:** every input between the previous snapshot and this one (`key_down`, `key_up`, `mouse_down`, `mouse_up`, summed `look`), plus every key or button still held at capture (`key_hold`, `mouse_hold`, with `held_ms`). Inputs after a play's last snapshot go on that snapshot with a negative `ms_before_frame`. Key and look actions box the whole frame; mouse buttons also get a keypoint at the pointer (the screen centre under pointer lock). `attributes` follow COCO4GUI: `task_description` (e.g. "Hold KeyW"), `action_type`, `element_info` (key code or `mouse_left`), `custom_metadata` (`ms_before_frame`, `pointer_locked`, `held_ms`, `dx`/`dy`), and the step chain (`previous_*`, `steps_since_start`).
- **Ids** are hashes of session, slot and capture time, so a snapshot keeps its id across exports and labels made on one export carry over.
- **Known limits:** COCO describes still images, so key and look actions get a whole-frame box; at one snapshot per 2 s this suits analysis of how people play, not training an agent to imitate them (that needs an action per frame). Snapshots show only the game's canvas, not any HTML HUD drawn over it.
