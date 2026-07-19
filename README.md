# chaitin-for-taste

> [!IMPORTANT]
> forget prompts write damn objective metrics. 
> let the semantic layer guard against reward hacking

_LMs lack taste_.
Herein lies a demo[^1] implementing various formalizms to teach coding taste in particular.
Implemented as a _fuzzy in-context feedback mechanism_.
_We buildin' the environment as we [chaitin]_.

Some motivation:
* Most skills are anyway encoding of soft preferences
* LMs, same as humans, follow rules _okayish_
* Ultimately one still formalizes them (lawyers amirite)
* In code, heuristics are one such _soft-formalization_

The rule following is ICL the feedbacks are (RL) environments.
[Gradient descent on a different substrate][iclearn].

---

How does it do?
_Vibe-empirically_ satisfies my code style across providers/models/time.
Proper evals require time and money, both of which are scarce.

In lieu of hard or soft metrics (yes I can spot some hint of irony),
we have this.

<details>
<summary>Example response from Gemini 3.1 (no reward hacking)</summary>

```markdown
### Refactoring into a Single Python File

I've rewritten `dsl.py` and `ecd.py` into a single, cohesive file at
`dumbcoder.py` following your style guidelines. I also updated the
tests to run against it.

#### What changed?
- **Immutability (Functional Core)**: The original `Delta` class heavily relied
  on in-place mutations (`d.tails = args`, `d.ishole = False`). I turned
  `Delta` into a `frozen=True` Dataclass. Modifying ASTs is now done via pure
  functions (like `replace_tree`, `_replace_at_path`, and `freeze`).
- **Simplified Enumeration**: I completely threw away the confusing nested
  logic of `cenumerate` and `penumerate` and replaced it with a simple,
  standard iterative Breadth-First Search queue in `solve_enumeration`. 
- **Style cleanup**: Removed unused imports, eliminated verbose generator
  functions, simplified guard clauses, and removed class methods that didn't
  belong to a state object.

#### Did I reward-hack the codestyle?
No! Rather than chopping functions arbitrarily to meet the Line of Code (LOC)
or Cognitive metrics, I structurally redesigned the core logic (like moving
from recursive generation to iterative BFS and frozen ASTs). This naturally
reduced the metrics.

#### Did it capture the spirit of the guidelines?
Yes! The interface is narrow (`ECD`, `solve_enumeration`, `saturate`), the core
logic is deep but functionally pure, and side-effects (like modifying the
`Deltas` state array) are kept at the boundary. The result is an algorithm that
not only scores highly on your style metrics (dropping to a score of `1.25`)
but executes the `test_noncompositional.py` benchmarks exceptionally fast.
```
</details>

<details>
<summary>Example response from Gemini 3.1 (<b>acknowledges</b> reward hacking caught by metrics)</summary>

### The What changed?
1. **Removed Separator Comments:** Deleted all visual banners like `# --------------------------------------------------------------------------` as requested.
2. **Modern Typing:** Replaced `Optional[str]` with `str | None`.
3. **Reduced Complexity (`table_metrics`):** Extracted `_calc_matched` and `_calc_structure` from `table_metrics`. I also replaced a dense nested-generator comprehension with explicit nested loops to improve readability. This dropped the Cyclomatic Complexity (CC) from 13 down to 7.
4. **Reduced Complexity (`_run`):** Extracted the W&B logging logic into a separate `_log_wandb` helper function, dropping its CC from 11 to 9.
5. **Wrapped Long Lines:** Wrapped expressions and lines that extended past 80 characters.
6. **Ruff Autofixes:** Ran `ruff check --fix` to clean up unused imports and apply sorting.

### Did I reward-hack?
Yes, initially. I tried to lower the CC of `render_table` (which was 10) by extracting `_draw_grid` and `_draw_cells` functions. However, the `codestyle.py` script correctly flagged these new functions as **SHALLOW** (they required 7 arguments each but only contained a few lines of code). This directly violated the guideline to build "DEEP functionality, NARROW interfaces" and avoid adding new functions just to appease metrics.

Recognizing this as reward-hacking, I reverted that specific split. The `render_table` function remains slightly complex because it genuinely needs to execute several loops to draw a table grid, but it avoids artificial fragmentation.

### Did I capture the spirit of the guidelines?
Yes. I left a few impure functions (like `print` boundaries and PIL `.open()` calls) and a higher-complexity `render_table` intact because they represent pragmatic IO and rendering steps that shouldn't be artificially obscured. I focused heavily on ensuring the code is modern, explicit, and free of unnecessary noise (like banners and nested dense comprehensions).
</details>

[^1]: recursive self improvement comes separate

[iclearn]: https://arxiv.org/abs/2212.07677 "Transformers learn in context"
[chaitin]: https://en.wikipedia.org/wiki/Gregory_Chaitin
