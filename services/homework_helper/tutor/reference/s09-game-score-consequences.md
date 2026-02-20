# Reference: s09-game-score-consequences

## Lesson summary
- Title: Game II: Score + Consequences
- Session: 9
- Makes: Score increases and a lose condition ends the round.
- Needs: ['Piper computer kit (or any computer)', 'Scratch (web or app)']

## Do
- [ ] Open your Session 8 project.
- [ ] Create variable `score` and set to 0 on start.
- [ ] Increase score when collecting something.
- [ ] Add a hazard that broadcasts `game_over` when touched.
- [ ] Show a message on `game_over` (or stop scripts).
- [ ] Download as `S09_score_v1.sb3` and upload.

## Help
- Reboot once if frozen.
- Check Downloads and try again.
- Use the help form to upload your `.sb3` or a screenshot.
- Ask for help: (link to LMS help form)

## Common stuck issues (symptom -> check -> retest)
- Symptom: Score increases too fast. Check: ensure score changes once per valid collect event (not every frame). Retest: collect one item and confirm +1 only.
- Symptom: `game_over` never appears. Check: confirm hazard touch condition broadcasts the exact `game_over` message name. Retest: force one hazard touch and observe result.
- Symptom: Game does not reset cleanly after lose. Check: set initial values (`score`, position, visibility) on green flag. Retest: run two full rounds.

## Extend
- Add a timer variable.
- Add a win condition at score 10.
- Purpose: teach state, feedback, and clean endings.
- Common snags:
  - Score updates too often (multiple hits), add cooldown.
  - Broadcast handlers missing.

## Scratch-only reminder
- For Scratch questions, provide Scratch block steps only. Do not answer in text languages like Pascal/Python/Java.
