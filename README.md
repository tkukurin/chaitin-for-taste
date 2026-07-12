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
<summary>Example response from Gemini 3.1</summary>

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

[^1]: recursive self improvement comes separate

[iclearn]: https://arxiv.org/abs/2212.07677 "Transformers learn in context"
[chaitin]: https://en.wikipedia.org/wiki/Gregory_Chaitin
