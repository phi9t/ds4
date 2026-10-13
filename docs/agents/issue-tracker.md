# Issue Tracker: Local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`.
- The spec is `.scratch/<feature-slug>/spec.md`.
- Implementation issues are one file per ticket at
  `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Triage state is recorded as a `Status:` line near the top of each issue file.
- Comments and conversation history append to the bottom of the file under a
  `## Comments` heading.

## Skill Operations

When a skill says "publish to the issue tracker", create a new file under
`.scratch/<feature-slug>/`, creating the directory if needed.

When a skill says "fetch the relevant ticket", read the file at the referenced
path. The user will normally pass the path or the issue number directly.

## Wayfinding

Used by `wayfinder`. The map is a file with one child file per ticket.

- Map: `.scratch/<effort>/map.md` with notes, decisions so far, and open fog.
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`, with a `Type:` line
  (`research`, `prototype`, `grilling`, or `task`) and a `Status:` line.
- Blocking: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when
  every listed ticket is `resolved`.
- Frontier: scan `.scratch/<effort>/issues/` for files that are open,
  unblocked, and unclaimed; first by number wins.
- Create: set `Status: open` before the ticket is claimed.
- Claim: set `Status: claimed` and save before any work.
- Resolve: append the answer under an `## Answer` heading, set
  `Status: resolved`, then append a context pointer to the map.
