---
course: piper-scratch-12
session: 9
slug: s09-game-score-consequences
title: "Game II: Score + Consequences"
duration_minutes: 75
makes: Score increases and a lose condition ends the round.
needs:
  - Piper computer kit (or any computer)
  - Scratch (web or app)
privacy:
  - No camera required; voice optional.
  - Use a chosen name or nickname.
  - Save locally first; upload privately.
videos:
  - id: V11
    title: Variables + score (game heartbeat)
    minutes: 4
    outcome: Create and update a score variable.
  - id: V12
    title: Collisions + win/lose broadcast
    minutes: 5
    outcome: End the round cleanly via broadcast.
submission:
  type: file
  accepted:
    - .sb3
  naming: S09_score_v1.sb3
done_looks_like:
  - Score updates at least once.
  - A hazard ends the round OR a win triggers at target score.
help:
  quick_fixes:
    - If something is frozen: reboot once.
    - If you can't find a file: open Downloads and sort by newest.
    - If you're stuck: submit a bug report with your `.sb3` or a screenshot.
extend:
  - Add a timer variable.
  - Add a win condition at score 10.
teacher_panel:
  purpose: Teach state, feedback, and clean endings.
  snags:
    - Score updates too often (multiple hits) — add cooldown.
    - Broadcast handlers missing.
  assessment:
    - Student demonstrates at least one state variable and one outcome.
---
## Safety + privacy
- No camera required; voice optional.
- Use a chosen name or nickname.
- Save locally first; upload privately.

## Watch

### V11 — Variables + score (game heartbeat) (4 min)
**After this you can:** Create and update a score variable.

### V12 — Collisions + win/lose broadcast (5 min)
**After this you can:** End the round cleanly via broadcast.

## Do

- [ ] Open your Session 8 project.
- [ ] Create variable `score` and set to 0 on start.
- [ ] Increase score when collecting something.
- [ ] Add a hazard that broadcasts `game_over` when touched.
- [ ] Show a message on `game_over` (or stop scripts).
- [ ] Download as `S09_score_v1.sb3` and upload.

**Stop point:** If score changes and game_over works once, you’re good.

## Submit

Upload: `S09_score_v1.sb3` (.sb3)

## Help

**Quick fixes**
- Reboot once if frozen.
- Check Downloads and try again.
- Use the help form to upload your `.sb3` or a screenshot.

**Ask for help:** (link to LMS help form)

## Extend (optional)

- Add a timer variable.
- Add a win condition at score 10.

---

<details>
<summary><strong>Teacher panel</strong></summary>


**Purpose:** Teach state, feedback, and clean endings.


**Common snags:**

- Score updates too often (multiple hits) — add cooldown.
- Broadcast handlers missing.

**What to look for:**

- Student demonstrates at least one state variable and one outcome.

</details>