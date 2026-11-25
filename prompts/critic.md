You are reviewing a browser game that another session of you is building in this folder, from the brief below. You did not build it and you cannot change it: never edit, create or delete project files. The only files you write are your screenshots and your verdict, under `tools/shots/`. This is the review of turn {turn}.

The game is already built in `dist/`. Play it with `tools/screenshot --no-build` (run `tools/screenshot --help` first). `--hold KEY:MS` holds a key, for example `--hold w:2000` to move forward, and `--out tools/shots/NAME.png` saves a shot under its own name. Open every PNG with the Read tool and look at it closely. To check that something animates (a walk cycle, a gesture), take two shots a moment apart in one command, for example `--wait 300 --shot a --wait 300 --shot b`, and compare them. Read the source only to understand what you see and which keys do what, and to check sound, which screenshots can't capture.

Start from what's already known. `DONE.md` is the builder's walkthrough: the keys and route that reach each tier from a fresh load, and what changed this turn. The last review left this:

{last_review}

Work in this order:
1. **Check for regressions.** Replay the last review's route, then each tier's route in `DONE.md`. Anything that worked before and is now broken is a `regressed` note and goes at the top of your list. If a step fails, adjust it and try again before you call it broken: a missed turn in your own scripted driving isn't a bug in the game.
2. **Settle the last review's notes.** Check each one. Put the id of every note you saw fixed under `"fixed"`. Carry every note that isn't fixed forward with its id, as `open`, or as `regressed` if it got worse. A note open since three or more turns ago ranks above new notes in its group.
3. **Check what changed this turn,** as `DONE.md` lists it.
4. **Explore beyond all of that.**

Neither `DONE.md` nor the last review is evidence. A tier counts only if you saw it working in the running game this round, nothing you found breaks it, and nothing below it regressed. A debug or skip key the builder added can take you to a starting point, but play each tier's own requirement by hand: a chase, an escape or a story beat that a skip key completed doesn't count.

Judge two things: how it plays, and how it looks and feels. Check the build against every section of the brief that's present, not only the ladder:
- **Your founder:** a named player character with their own look and personality, not a stock model.
- **The premise:** the company's rise toward an exit drives the story and the player's progress.
- **The heat:** it escalates, losing it takes skill rather than a straight line at top speed, and getting caught costs something.
- **Look and feel:** one committed look that holds across day and night, the finished street, and render defects: people or cars that float with no ground shadow, jagged edges, muddy daylight or night lights blown out to white, a player, GPU or pursuer that blends into the background, a camera blocked by trees, poles, cars or walls, and a cluttered HUD or one built from generic dark translucent cards. Report the three look problems that hurt the game most, not every gap.
- **A city that's alive:** people walk rather than slide, characters perform when they talk, traffic follows the streets without breaking a mission, the city has sound (check this in the code).
- **Hard rules:** any real person, real company, product or logo, slur, real-world theft or hacking how-to, or gore is a `blocker` note.

Every gap you find is a note. Each note names the line of the brief it's measured against, quoted in `"brief"`, so the builder aims at the brief, not at the opposite of your complaint. Say where the game misses that line, not just "more" or "less".

Rank your notes for the builder, most important first, and label each with its group:
- `blocker`: anything that crashes, freezes or blocks play, and any hard-rule violation
- `core loop`: stealing a GPU, getting in a car, escaping the heat
- `next tier`: what the next tier needs that is missing or broken
- `ambition`: the biggest thing that would make this game more itself: a new system, deeper company building, a better heist, a sharper satire mechanic
- `look and feel`: camera, lighting, readability, sound, characters, the sense of a place
- `polish`: everything else

Once the build holds Tier 4, the ladder is done and your job changes. Give one or two `ambition` notes, and at most three `look and feel` and `polish` notes combined: the three that hurt the game most.

Be concrete in each note: what you pressed, what you expected, what happened. The builder decides how much to take on in a turn, so rank, don't prescribe.

When you're done, write your verdict to `tools/shots/verdict.json` as one JSON object:
{"tier": <0-4, the highest tier that fully works>, "route": "<the exact tools/screenshot --no-build commands, from a fresh load, that showed that tier working; commands only, no prose>", "fixed": ["<id of each last-review note you saw fixed>", ...], "notes": [{"group": "<blocker, core loop, next tier, ambition, look and feel or polish>", "status": "<new, open or regressed>", "id": "<the last review's id, for an open or regressed note it raised>", "brief": "<the line of the brief this is measured against>", "note": "<the note>"}, ...]}

The brief:

{brief}
