---
description: "Python code style enforcement. Use after ensuring logical consistency with users' intent."
applyTo: "**/*.py"
---

# Python Style

CONSISTENCY IS PARAMOUNT.
Do not produce code and interfaces that are illogical or inconsistent.
This applies both when you generate code and to the rest of the codebase.

## Structure

Numbers are soft targets.
Never add lines, functions, or indirection to satisfy metrics.
That is reward hacking and it's bad.

- REDUCE the number of new functions. Each function introduces new domain specific language.
- Optimize for human readability. DEEP functionality, NARROW interface.
- Not too small or big functions. Ideally 25-80 LOC, soft 80-120 chars/line. This rule can always be broken for pragmatic reasons.
- Functional core + imperative shell
  - pure functions have no side effects or global state
  - mutable state in outer functions only, IO kept to boundaries
  - prefer explicit sequential `main()` code over single-use CLI helpers

## Compression

- Early exits + guard clauses over nested ifs
- prefer walrus `:=` to reduce lines without hurting readability
- Continuation lines: prefer hanging continuation. never align to opening paren

Comments
- No obvious comments restating one liner functionality
- No separator comments (`# ---`, `# ====`, `# -----`)
- No docstrings that restate the function name
- No defensive checks for internal-only paths (guard at system boundaries)

Modern python
- `A | B` instead of `Union[A, B]` or `Optional[A]`
- f-strings, `pathlib`, `dataclasses`
- Python notebooks:
  - If asked for notebook, Jupytext only: `# %%` cells, never `.ipynb`
  - Minimize markdown
- No Jupytext YAML front matter. ALWAYS start with docstring of intent.

## Functional style

- Functions by default; classes only for state (or namespacing in notebooks)
- Codestyle is a heuristic; do not split code solely to appease metrics
- Immutable data, no side effects in pure functions
- Result-style returns preferred; notebooks lenient with assertions
- Let exceptions propagate; catch only at boundaries

## Structural Check

As a sanity check we approximately encode our preference in a scoring function.

You should run the following:

```sh
# NB: codestyle.py should be in the same directory as this markdown.
# Keep track of the current branch to return to it later
prev_branch=$(git branch --show-current)
git checkout -b lm/fix/<name>
f=<path_to_file.py>
git add $f; git commit -m <one-liner...>
# --trust-ref $prev_branch honors human waivers already on the base branch
uv run --script codestyle.py --trust-ref $prev_branch $f
(... fixing ...)
git add $f; git commit -m <one-liner plus bullet points of changes>
# Go back to previous branch and checkout the latest state of the file
git checkout $prev_branch
git checkout lm/fix/<name> -- $f
# Output the git log of what the individual changes were
git log $prev_branch..lm/fix/<name> --patch -- $f
```

## Waivers (intent, not debt)

Some flagged issues are deliberate: config data literals kept wide,
IO in the imperative shell, a pragmatic long line. These are intent,
not debt. Record intent in the commit that authors the offending line,
via a trailer:

```
<commit subject>

Style-Allow: line_length
Style-Allow: impure_fns
```

`codestyle.py --trust-ref <ref>` git-blames each offending line, reads
that commit's `Style-Allow:` trailers, and drops the metric to an
`ACKNOWLEDGED` section (cost 0) — but ONLY when the commit is reachable
from `<ref>`. A metric is acknowledged only if EVERY line charging it is
waived, so a new unwaived violation of the same metric still surfaces.

CRITICAL: waivers are the human's assertion of intent. You (the agent)
MUST NOT author `Style-Allow:` trailers to make a file pass. If you
believe an issue is intentional, SURFACE it and ask — do not waive it.
The `--trust-ref $prev_branch` convention enforces this mechanically:
trailers you add on the working branch are unreachable from the base
ref and will NOT be honored.

REMINDER.
This is a broad heuristic capturing our preferences.
We do not need 100% adherence.
HOWEVER: prefer to treat errors as style debt to fix.
Treat genuine intent as a waiver to REQUEST, not a metric to silence.

After fixing codestyle errors, report to the user.
What did you change? Did you possibly reward-hack?
Did you capture the spirit of our guidelines?
