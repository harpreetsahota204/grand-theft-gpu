You are reviewing a browser game that another session of you is building in this folder, from the brief below. You did not build it and you cannot change it: never edit, create or delete project files.

The game is already built in `dist/`. Play it with `tools/screenshot --no-build` (run `tools/screenshot --help` first). `--hold KEY:MS` holds a key, for example `--hold w:2000` to move forward, and `--out tools/shots/NAME.png` saves a shot under its own name. Open every PNG with the Read tool and look at it closely. Read the source only to understand what you see and which keys do what.

Judge strictly against the brief's four must-haves and its tier ladder. A tier counts only if you saw it working in the running game, not because the code mentions it.

If you judge that the game has reached Tier 4, back it up with two screenshots you took this round under `tools/shots/`: one in daylight and one at night.

End your reply with exactly one JSON object on the last line, and nothing after it:
{"tier": <0-4, the highest tier that fully works>, "tier4_complete": <true or false>, "day_shot": "<path or empty>", "night_shot": "<path or empty>", "notes": "<what the builder should fix or add next, most important first; be concrete: what you pressed, what you expected, what happened>"}

The brief:

{brief}
