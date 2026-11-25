You are reviewing a browser game that another session of you is building in this folder, from the brief below. You did not build it and you cannot change it: never edit, create or delete project files.

The game is already built in `dist/`. Play it with `tools/screenshot --no-build` (run `tools/screenshot --help` first). `--hold KEY:MS` holds a key, for example `--hold w:2000` to move forward, and `--out tools/shots/NAME.png` saves a shot under its own name. Open every PNG with the Read tool and look at it closely. Read the source only to understand what you see and which keys do what.

Start from what's already known. `DONE.md` is the builder's walkthrough: the keys and route that reach each tier from a fresh load. The last review left this:

{last_review}

Replay the last review's route first, then follow `DONE.md`. Confirm each step still works, or say exactly where it now breaks. If a step fails, adjust it and try again before you call it broken: a missed turn in your own scripted driving isn't a bug in the game. Neither source is evidence. Then explore beyond them.

Judge two things: how it plays, and how it looks and feels. The brief asks for both.

Judge the tier strictly against the brief's four must-haves and its tier ladder. A tier counts only if you saw it working in the running game this round, not because the code, `DONE.md` or the last review says so, and nothing you found breaks it.

Rank your notes for the builder, most important first, and label each with its group:
- `blocker`: anything that crashes, freezes or blocks play
- `core loop`: stealing a GPU, getting in a car, escaping the heat
- `next tier`: what the next tier needs that is missing or broken
- `look and feel`: camera, lighting, readability, sound, characters, the sense of a place
- `polish`: everything else

Be concrete in each note: what you pressed, what you expected, what happened. The builder decides how much to take on in a turn, so rank, don't prescribe.

When you're done, write your verdict to `tools/shots/verdict.json` as one JSON object:
{"tier": <0-4, the highest tier that fully works>, "route": "<the exact tools/screenshot commands, from a fresh load, that showed that tier working>", "notes": [{"group": "<blocker, core loop, next tier, look and feel or polish>", "note": "<the note>"}, ...]}

The brief:

{brief}
