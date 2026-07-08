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



[^1]: recursive self improvement comes separate

[iclearn]: https://arxiv.org/abs/2212.07677 "Transformers learn in context"
[chaitin]: https://en.wikipedia.org/wiki/Gregory_Chaitin
