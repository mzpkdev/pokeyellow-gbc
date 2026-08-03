# ROMhack development workflow

This is the next-day continuation and handoff manual for the ROMhack as a
whole. Start with [Documentation index](INDEX.md), then read
[Architecture](ARCHITECTURE.md) before changing shared runtime behavior and
[Testing](TESTING.md) before treating a green check
as proof. Feature-specific guides, including the current full-color extension
recipe, are linked from [Adding content](ADDING_CONTENT.md). Historical
failures are recorded in [Bugs and glitches](BUGS_AND_GLITCHES.md).

## Start every session from facts

Read the repository instructions and inspect the checkout before assuming that
yesterday's state still applies:

```console
cat AGENTS.md
git status --short --branch
git log -5 --oneline --decorate
git diff --stat
git diff
```

Check the active pull request and hosted checks when the branch has one. Local
files do not reveal whether the last push is green, whether review changed, or
whether the target branch moved.

Treat the worktree as shared. Existing modifications and untracked files belong
to their author unless the current task explicitly owns them. Do not clean,
rewrite, stage, or reformat unrelated paths. In particular, `.preemdeck/` is
operator state, not ROMhack source. Preserve it.

Before editing, establish:

- the requested player-visible outcome and its deliberate exclusions;
- the files, products, and tests the change is allowed to affect;
- whether generated data or retained evidence has an authoritative producer;
- which stock or debug ROM supplies the comparison baseline;
- which checks actually exercise the changed runtime path.

## General build and review loop

Use the cheapest check capable of disproving the current change, then widen the
circle:

1. Run focused tests or validators for the edited subsystem.
2. Build every product whose assembly path, data, or packaging may have changed.
3. Run the subsystem's broader suite and product-identity checks.
4. Compare relevant output against an appropriate stock or previous baseline.
5. Exercise the feature through natural gameplay from a cold boot.
6. Run the retained project gates required by the feature's documentation and
   pull request.
7. Inspect the complete diff and every generated or untracked artifact before
   handoff.

The repository's ordinary products are:

```console
make yellow
make yellow_debug
make yellow_vc
```

Use `make compare` when the task is expected to preserve the pinned stock ROM
identities. A successful build proves that RGBDS accepted the source. It does
not prove that the game boots, progresses, renders correctly, or preserves
unrelated products.

Manual review must match the change. Start from a cold boot rather than a save
state produced by another revision. Test transitions into and out of the
changed behavior, repeated use, menus and interruption points, save/reset when
state persists, and both directions of movement when maps or scrolling are
involved. Watch several frames: a single screenshot misses flicker, transient
corruption, deadlocks, and delayed writes.

## Failure triage

Capture the failure before changing code. Record the exact ROM, source revision,
command or input sequence, last known-good scene, and artifact directory. Keep
the `.gbc`, `.sym`, and `.map` files from one source revision together.

Classify first; debug second:

- **Build or link failure:** reduce to the first assembler/linker error and
  confirm the expected RGBDS/tool environment. Later diagnostics are commonly
  fallout.
- **Boot or progression stop:** compare the same path in `pokeyellow_debug.gbc`.
  If both fail, suspect the scenario, toolchain, or shared ROM change before a
  feature-only runtime.
- **Visual geometry corruption:** wrong shapes, positions, repeated fragments,
  or overlays in the wrong scene indicate tile data, indices, banks, coordinates,
  ownership, or cleanup—not aesthetic tuning.
- **Correct geometry, wrong presentation:** inspect feature data and dispatch
  only after proving the underlying stock-owned scene still matches.
- **Intermittent failure:** record frame timing, transition direction, and
  concurrent redraw/animation work. Inspect sequences or frame strips instead
  of only the final frame.
- **Stale evidence:** bind every conclusion to its manifest, ROM identity,
  revision, and attempt directory. Never copy an old green summary over a new
  failure or regenerate evidence until it happens to pass.

Diagnostic output is evidence, not source. Preserve failed and successful
attempts separately. Regenerate checked-in evidence only through its documented
producer and review the semantic diff, not merely the exit code.

## Current playable full-color loop

The playable color implementation is currently the **Phase 2 audit product**,
`pokeyellow_phase2_audit.gbc`. It passively colors Pallet Town and Route 1.
Interiors, menus, battles, cutscenes, sprites, animation, and maps outside that
slice retain Pokemon Yellow's existing visual behavior.

The normal release, debug, and VC products deliberately do not expose this
audit runtime. The audit ROM is a playable canary and evidence product, not yet
the release ROM. Read [Architecture](ARCHITECTURE.md) for the ownership contract
and [Adding content](ADDING_CONTENT.md) before adding a map or palette.

Set up the pinned Python environment once per checkout, then build paired ROMs:

```console
make test-full-color-setup
make yellow_debug yellow_phase2_audit
```

Use `pokeyellow_phase2_audit.gbc` for color review and
`pokeyellow_debug.gbc` as its Yellow reference, built from the same revision.
Run checks from fast to slow:

```console
.venv/bin/python -m pytest tools/rom_tests/tests/unit/full_color -q
make yellow_phase2_audit
make verify-full-color-phase2-audit
make test-full-color-smoke
make test-full-color-renderer-conformance
make test-full-color-renderer-runtime
make yellow_debug yellow_phase2_audit
.venv/bin/python -m pytest tools/rom_tests/tests/e2e/test_full_color_cold_boot_journey.py -q
make test-full-color-gate0
make test-full-color-all
```

`test-full-color-all` does **not** include
`verify-full-color-phase2-audit` or the cold-boot E2E file. Run them explicitly.
The conformance checker is synthetic. Gate 0 protects the retained baseline and
evidence system. Neither replaces natural gameplay or human visual review.

At minimum, play through the Game Freak logo, Oak's introduction, bedroom,
Pallet Town, Oak's interception and capture, Route 1, Viridian entry, and the
return trip. Exercise a house transition, dialogue, Start and party menus, a
wild battle, save/reset/Continue, scrolling in both directions, and ledges.
Verify stable slice color, stock-like geometry and sprites, clean fallback, clean
return, and no seams or one-frame palette swaps.

### Full-color-specific triage

- A white screen or progression stop is a control-flow failure, not a palette
  problem. Narrow the first audit-only entry reached before the stall.
- Corrupt tiles or cutscene graphics drawn over an overworld mean tile bytes,
  indices, attribute coordinates, VRAM banks, wrapping, or cleanup are wrong.
  Stop palette tuning until geometry matches the debug ROM.
- If geometry matches but a roof, ground, or object color is wrong, inspect the
  palette payload and tile-to-attribute authority. An allowlist does not make a
  map correctly colored; Viridian needs map-aware palette/roof support.
- For flicker or seams, assume scheduling until disproved. Yellow's redraw and
  animation work retains priority; passive work must defer or clear in bounded
  chunks.
- Audit-only entries in a normal product are a release-boundary regression.
  Stop feature work and run `make verify-full-color-phase2-audit`; do not weaken
  reachability, identity, or provenance checks.

Full-color artifacts currently land in:

- Gate 0: `test-results/full-color-gate0/attempt-NNNN/{run-1,run-2}`
- Smoke: `test-results/full-color-gate0/smoke/attempt-NNNN`
- Renderer conformance:
  `test-results/full-color-renderer-conformance/attempt-NNNN`
- Renderer runtime: `test-results/full-color-renderer-runtime/attempt-NNNN`
- Natural journey evidence: `test-results/full-color-cold-boot/`
- Per-test failures: `test-results/<test-derived-name>/`
- Reviewed evidence: `specs/full-colors/evidence/`

The future renderer direction is governed by the
[full-color migration plan](../specs/full-colors/docs/migration-plan.md). Do not
collapse Phases 3–9 into a vague next phase, widen an allowlist as a substitute
for map-aware content, or claim retained architecture is already active.

## Handoff, commit, and pull-request discipline

Before committing or handing work to another session:

1. Review `git status`, the full diff, every new file, and every generated file.
2. Separate task-owned paths from concurrent or unrelated work.
3. Run the focused checks, product builds, identity checks, gameplay journeys,
   manual review, and retained gates appropriate to the blast radius.
4. Record exact commands and outcomes; explicitly name checks not run.
5. Record the ROM and revision manually played, route taken, observed result,
   and useful artifact directories.
6. Obtain fresh read-only review of the task diff and verify every finding
   against source or runtime evidence.
7. Stage exact paths only. Do not use blanket staging in a dirty worktree.
8. Recheck the staged diff, commit only reviewed paths, push the feature branch,
   update the pull request with verified facts, and watch hosted CI to completion.

Pull-request descriptions start from `.github/pull_request_template.md` and
follow `AGENTS.md`: lead with the player-visible premise, explain mechanics and
limits plainly, show affected content, document meaningful tradeoffs, and end
with verified checks. Never claim a release behavior, supported map, test, or
CI result that the branch has not earned.

Implementation workers do not commit, push, or rewrite pull requests. The root
operator owns exact-path staging and external state. If the worktree is dirty,
that discipline is not bureaucracy—it is what keeps somebody else's work out
of your commit.

## A useful next-day handoff note

A continuation note should answer, without relying on chat history:

- Which branch and pull request are active, and what is their current state?
- What player-visible behavior exists now, in which ROM product?
- What changed in the last session, using exact paths?
- Which commands passed, failed, or were skipped?
- What was manually played, from which revision, and what was observed?
- Where are the useful success and failure artifacts?
- What unresolved issue or next bounded task should be taken first?
- Which invariants, exclusions, and concurrent files must remain untouched?

If those answers are missing, tomorrow starts with archaeology. Write them down.
