# Reference: s08-game-controls-boundaries

## Lesson summary
- Title: Game I: Controls + Boundaries
- Session: 8
- Makes: A controllable character that stays on screen.
- Needs: ['Piper computer kit (or any computer)', 'Scratch (web or app)']

## Do
- [ ] Start a new Scratch project (or fork your scene).
- [ ] Add controls: arrow keys move sprite.
- [ ] Add boundaries (stop at edges or wrap).
- [ ] Add one collectible OR one obstacle.
- [ ] Download as `S08_game_controls_v1.sb3` and upload.
- Stop point: if movement works and you saved the file, you’re done.

## Help
- Reboot once if frozen.
- Check Downloads and try again.
- Use the help form to upload your `.sb3` or a screenshot.
- Ask for help: (link to LMS help form)

## Common stuck issues (symptom -> check -> retest)
- Symptom: Player moves off-screen. Check: add one boundary condition (edge check or wrap) before adding more mechanics. Retest: hold each arrow key to each edge.
- Symptom: Controls feel too fast. Check: reduce move step size or add a tiny wait. Retest: run a full lap around the stage and judge control feel.
- Symptom: Collectible/obstacle never triggers. Check: verify touching condition references the correct sprite. Retest: force one collision and confirm response.

## Extend
- Add a sprint key (shift) that increases speed.
- Add a ‘slow mode’ for accessibility.
- Purpose: establish player control and readable game space.
- Common snags:
  - Movement too fast or too slow.
  - Boundary logic confusing, use one simple edge check first.

## Scratch-only reminder
- For Scratch questions, provide Scratch block steps only. Do not answer in text languages like Pascal/Python/Java.
