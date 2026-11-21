## Rules of the run

- You are working alone in this directory. Everything you build lives here.
- This is a Vite project. After every one of your turns, the harness runs `npm install` and `npm run build`, then loads `dist/index.html` in a browser. **If the build fails, your game counts as broken for that turn.** Keep the build green.
- **You can see your game.** `tools/screenshot` builds it the same way, plays it in a headless browser and saves a PNG you can open with the Read tool. `tools/screenshot --hold w:2000` holds a key first; `tools/screenshot --help` lists the options.
- Keep working until you consider the game finished. When you do, create `DONE.md` with a short summary of what you built and how to play it. Don't create `DONE.md` before then.
