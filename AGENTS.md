# Pull request descriptions

Start every pull request description from
[`.github/pull_request_template.md`](.github/pull_request_template.md). If the
template is missing, create it before opening the pull request.

Use the template to write a human-facing pitch for the feature:

- Open with the premise: what changes for the player, why it is appealing, and how it fits the game. Lead with the experience rather than implementation details.
- Explain how the feature works in clear, concrete language. Include the rules, important probabilities or limits, and any deliberate exclusions or safeguards a reviewer should understand.
- Show the actual content affected. When a feature adds or redistributes game content, include readable tables or lists covering what is available, where, and at what odds or conditions.
- Explain meaningful design decisions and tradeoffs, especially choices made for balance, theme, progression, or compatibility with existing mechanics.
- End with verification: summarize the relevant automated checks, tests, and CI status without letting the testing section overshadow the feature.

Make the description sound like a person who is enthusiastic about the feature and understands it deeply. Prefer specific, natural prose over generic marketing language, ticket-style summaries, exhaustive commit logs, or boilerplate. The pitch must remain accurate: do not oversell behavior, hide limitations, or claim checks that have not run.

Adapt the template to the change. Use headings and tables when they genuinely
improve readability, and remove sections that truly do not apply. Small
maintenance changes may use a proportionally shorter description, but should
still begin with the template.
