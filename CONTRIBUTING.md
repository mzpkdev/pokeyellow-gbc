# Contributing

Thank you for contributing to Pokémon Yellow.

## Before opening a pull request

- Follow [CODING_STYLE.md](CODING_STYLE.md).
- Run the relevant checks locally with `python tools/run_ci.py`.
- Keep each pull request focused on one change.

## Pull requests

Start every description from the
[pull request template](.github/pull_request_template.md). Use it to pitch the
change in natural, human-sounding language: lead with the player or contributor
experience, explain the behavior concretely, show affected game content when
useful, and record meaningful design decisions and verification.

Adapt the template in proportion to the change. Tables are encouraged when they
make locations, odds, or other content easier to review. Remove sections that
do not apply instead of filling them with boilerplate such as `Not applicable`.
Keep the pitch accurate and specific; do not hide limitations, oversell the
feature, or claim checks that have not run.

If you cannot run the build or tests locally, feel free to open the pull
request as a draft and use the CI results for feedback. Address any failures
before marking the pull request as ready for review.

Pull request titles must follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>[optional scope][!]: <description>
```

Accepted types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `revert`, `style`, and `test`.

Examples:

```text
feat(battle): add a critical-hit test
fix: preserve palette order for player graphics
refactor(engine)!: change the map loading interface
```
