## Rules of the run

- You are working alone in this directory. Everything you build lives here.
- This is a Vite project. After every one of your turns, the harness runs `npm install` and `npm run build`, then loads `dist/index.html` in a browser. **If the build fails, your game counts as broken for that turn.** Keep the build green.
- **You can see your game.** `tools/screenshot` builds it the same way, plays it in a headless browser and saves a PNG you can open with the Read tool. `tools/screenshot --hold w:2000` holds a key first; `tools/screenshot --help` lists the options.
- **The run continues until the game reaches Tier 4, or the budget runs out.** After each of your turns, a critic (a fresh session of you, with no memory of building the game) plays it, reviews it against this brief and writes your next instructions. The run ends when the critic judges that the game has reached Tier 4 and the harness's own checks agree: the city moves on its own, and the light changes between day and night.
- End your turn whenever you want a review. Keep a short `DONE.md` that says what the game is and how to play it, and update it as the game grows.
