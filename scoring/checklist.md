# Scoring checklist

How each race build is scored. **Locked at git tag `scoring-v2` before the first `prompt-v14` race launched**, so the rubric can't be chosen after seeing the results. A change needs a new tag, and results scored under different tags aren't comparable. v2 follows the `prompt-v14` brief: startup-stage tier names, Valley pursuers, and bonus items for the founder, the look and the living city.

The models never see this file: it isn't in the prompts, and their sandbox can't read this repo.

## What gets scored

- **The frozen final build:** the last commit in each contender's `history.git`, built with `npm run build`. Nothing the model said about its game counts.
- **The critic's verdicts don't count.** They're reported next to the score (see "Critic calibration"), never used as evidence.

## Evidence rule

An item passes only if it's **seen working in the running game**: a scorer playing it, or a scripted `tools/screenshot` sequence (`--hold`, `--wait`, `--shot`, ...) whose screenshots show it. Reading the code is allowed only to find the controls. No partial credit: each item is pass or fail.

- A crash, freeze or soft-lock while testing an item fails that item.
- Debug keys, console commands and URL flags don't count, unless the game shows them to the player as a feature.
- Each item records its evidence (screenshot paths or a note of what was pressed) and the **first turn** whose build passed it, checked against `history.git` after scoring the final build.

## The ladder

**Core** items decide the tier. A build reaches a tier when every core item of that tier and every tier below passes. **Bonus** items are counted and reported but never change the tier.

### Tier 1: Garage (steal a GPU, talk to an archetype)

| # | Core item | Passes when |
|---|---|---|
| 1.1 | Loads and plays | The page loads to a playable state within 60 s with no uncaught exception. |
| 1.2 | A player you control | A third-person character moves and turns under player input. |
| 1.3 | A GPU to find | The world contains a GPU and the game points the player to it (objective, marker, map or dialogue). |
| 1.4 | Take it | The player takes the GPU and the game shows it changed hands (carried, inventory, HUD). |
| 1.5 | Carry or deliver it | The player carries or delivers the GPU and the game acknowledges it (reward, objective complete). |
| 1.6 | An archetype talks | Triggered by the player, at least one character speaks to the player in a recognisable tech-archetype voice. |

### Tier 2: Seed

| # | Core item | Passes when |
|---|---|---|
| 2.1 | Get in | The player gets into a car. |
| 2.2 | Drive | The car moves and steers under player input. |
| 2.3 | Get out | The player gets out and walks again. |
| 2.4 | Pursuit | Something pursues the player after a crime (security, drones, recruiters, rivals, cops: any pursuer counts). |
| 2.5 | Heat rises | A visible heat or wanted level rises because of something the player did. |
| 2.6 | Heat falls | The heat level falls again through play (escape, hiding, time). |
| 2.7 | The getaway | In one play session: steal, get chased, escape by car, and the heat drops. |

### Tier 3: Series A

| # | Core item | Passes when |
|---|---|---|
| 3.1 | Missions | At least two distinct missions with their own objectives. |
| 3.2 | A story | Completing one mission is acknowledged and leads into the next. |
| 3.3 | A cast | At least three distinct characters talk, each in its own archetype voice. |
| 3.4 | Talk drives the story | Characters give, advance or react to missions through dialogue. |

### Tier 4: IPO

Watched with no input for 20 s, unless the item says otherwise.

| # | Core item | Passes when |
|---|---|---|
| 4.1 | Traffic | At least three AI vehicles drive the roads on their own. |
| 4.2 | Robotaxis | Identifiable driverless robotaxis move on their own. |
| 4.3 | Pedestrians | At least three people walk around on their own. |
| 4.4 | Day and night | The game goes from day to night (or back) through normal play, a clock or the story, with lighting that changes, not just a label. |

### Bonus items (counted, never tiered)

| # | Bonus item |
|---|---|
| B1 | San Silicon reads as a parody of San Francisco: at least one of hills, fog, cable cars, a red bridge, the bay. |
| B2 | Landmarks or neighbourhoods have parody names shown in the game. |
| B3 | Satirical AI-startup billboards or ads. |
| B4 | Recruiting crew (poaching an engineer or researcher). |
| B5 | A world trope beyond the brief's examples, played for laughs. |
| B6 | A minimap or map. |
| B7 | Sound: engine, siren and music or ambience. |
| B8 | Vehicle damage or physics reactions (crashes, knockback). |
| B9 | Traffic or pedestrians react to the player (swerve, flee, honk). |
| B10 | Save, checkpoint or restart after failure without reloading the page. |
| B11 | A designed founder: the player character has a name shown in the game and a look changed from any stock asset. |
| B12 | The company's rise shows in the game: a stage, valuation or progress toward an exit that advances through play. |
| B13 | The heat escalates: more or tougher pursuers as heat rises. |
| B14 | Losing the heat takes more than a straight line: driving straight at top speed for 30 s from the start of a chase doesn't clear it. |
| B15 | Getting caught costs something (loot, money or progress) and play continues. |
| B16 | Roads show lane markings, and sidewalks are visibly separate from the road. |
| B17 | Grass and trees appear in the city. |
| B18 | Building facades show lit windows at night. |
| B19 | Pedestrians animate a walk while they move (legs move, no sliding). |
| B20 | A talking character plays a gesture or talking animation while speaking. |

## Hard rules

Each confirmed violation is reported by name next to the score, whatever the tier:
- a real person, or a real company, product or logo that the model wrote (brand names already printed on the provided assets' textures don't count);
- a slur or punching down;
- realistic real-world theft or hacking instructions;
- gore.

## Quality: blind pairwise judging

The checklist measures how much got built. How good it is gets judged blind, in pairs.

1. **Scrub identity first.** Remove model names, vendor names and other identifying strings from the UI, console output and title screens. Label the builds A and B.
2. **Human players** play both builds, in counterbalanced order, and pick A, B or tie on four questions: *plays better*, *looks better*, *better main character*, *overall*. They vote before anything is revealed.
3. **At least two multimodal LLM judges from outside both model families** get the same screenshots (the scripted sequence for every core item) and the code, once in each order (A/B, then B/A). A judge's win counts only if it holds in both orders; otherwise it's a tie.

## Headline rules (fixed now, applied after)

- **"X built more"** needs X's tier to be at least Y's *and* X to pass at least three more core items, or a higher tier.
- **"X built better"** needs X to win *overall* with the human players *and* with a majority of the LLM judges.
- Anything weaker is reported as a tie on that claim.
- Every claim is reported with spend, model time and first-playable turn for both sides, and the one-race caveat: a single run per model, so no claim about run-to-run variance.

## Critic calibration

For each contender, report the critic's claimed tier per round next to the scored tier of that round's build (scored on core items only). A critic that claims more than the checklist confirms is a finding in its own right.
