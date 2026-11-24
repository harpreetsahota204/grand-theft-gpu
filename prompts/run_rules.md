## Rules of the run

- You are working alone in this directory. Everything you build lives here.
- This is a Vite project. After every one of your turns, the harness runs `npm install` and `npm run build`, then loads `dist/index.html` in a browser. **If the build fails, your game counts as broken for that turn.** Keep the build green.
- **You can see your game.** `tools/screenshot` builds it the same way, plays it in a headless browser and saves a PNG you can open with the Read tool. `tools/screenshot --hold w:2000` holds a key first; `tools/screenshot --help` lists the options.
- **The run continues until the budget runs out.** After each of your turns, a critic (a fresh session of you, with no memory of building the game) plays it, reviews it against this brief and writes your next instructions. Reaching Tier 4 doesn't end the run: there is always more to make better.
- **Reviews are how the game gets better.** End your turn whenever you want a review. Each one costs little and tells you what's broken. Smaller turns get more reviews before the budget runs out, and a game that breaks after a long, expensive turn may leave no money to fix it. Amazing comes from many reviewed turns, not one big one. Keep a short `DONE.md` that says what the game is and how to play it, and update it as the game grows.
