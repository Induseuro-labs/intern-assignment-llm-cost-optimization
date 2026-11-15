# ShopAssist cost optimisation: write-up

## Result

| | Baseline (points per ticket) | Now (points per ticket) | Target | Reduction |
|---|---:|---:|---:|---:|
| Question 1 | 8,721 – 8,937 | **1,227 – 1,434** | ≤ 3,000 | ~85% |
| Question 2 | 73,224 – 73,512 | **1,227 – 1,434** | ≤ 2,500 | ~98% |

Graded fields (`action`, `kb_article`) are unchanged on all four public tickets
and on the hold-out `T-1091`. All 37 tests pass.

Reproduce every number in this document with:

```bash
python scripts/cost_report.py
```

## Where the baseline spent its points

Billing is `uncached_input × 3 + cached_input × 0.3 + output × 15`, so one
output token costs as much as five input tokens.

**Question 1, T-1001: 8,865 points**

| call | input tokens | output tokens | points |
|---|---:|---:|---:|
| handle_ticket | 530 | 485 | 8,865 |

82% of the bill is output. The prompt asked the model to "think step by step",
"write full reasoning" and "quote any article", and none of that text is used by
the product.

**Question 2, T-1001: 73,509 points**

| call | input tokens | output tokens | points |
|---|---:|---:|---:|
| triage | 8,453 | 489 | 32,694 |
| retrieve | 597 | 46 | 2,481 |
| compose | 1,195 | 486 | 10,875 |
| audit | 6,718 | 487 | 27,459 |

Triage and audit each paste a slice of the 210k-token help center into the
prompt, three of the four calls ask for long reasoning, every call re-sends the
previous calls' output (triage is sent to compose twice), and a random trace id
at the top of the prompt makes prefix caching impossible.

## What changed

### 1. Ask for the answer only (largest saving)

The prompt now asks for a bare JSON object and nothing else. Output drops from
~485 tokens to ~40, which removes about 6,700 points per call.

### 2. Retrieve in code, not in the prompt

`shopassist/knowledge.py` builds a small lexical index over the help center
(stemming, stopwords, IDF weighting). The query is the customer thread plus the
order facts that are true. Only the top 2 articles are put in the prompt.

This is why Question 2's cost no longer depends on the size of the help center:
the 210k tokens are searched for free in Python and never billed.
`KnowledgeBase.from_blob` indexes the expanded help-center dump directly and
discards sections that have no article id (they cannot be cited); a test checks
it yields exactly the same citeable articles as the default index.

The governing article is in the top 2 for all five tickets (tested).

### 3. One model call instead of four (Question 2)

The four stages are kept, but only the one that needs language understanding
calls the model:

| stage | baseline | now |
|---|---|---|
| triage | model call, 32,694 pts | code: load ticket + order, build search query |
| retrieve | model call, 2,481 pts | code: lexical search, top 2 articles |
| compose | model call, 10,875 pts | **model call, ~1,300 pts** |
| audit | model call, 27,459 pts | code: schema and citation checks |

The audit stage checks that the action is one of the four allowed values and
that the cited article exists. Anything unparseable or invalid is downgraded to
`ESCALATE_TIER2` rather than raising, because a wrong automated refund costs
more than a manual review. These checks are deterministic, so code does them
more reliably than a second model call, at zero points.

### 4. Smaller input

- Order snapshot is compact single-line JSON instead of `indent=2`.
- `order_id` and `sku` are dropped: identifiers carry no policy signal. Every
  other field is passed through, including fields added in future.
- Few-shot examples removed; two one-line policies replace the full article dump.
- Markdown decoration stripped from article text.
- The random run id / trace id is gone.

### 5. Cache-friendly prompt layout

The system message is byte-identical for every ticket and all per-ticket
content comes after it. `nodes.compose` passes it as `cached_prefix`
automatically once it reaches the 1,024-token minimum. At ~80 tokens it does
not qualify today, and padding it to qualify would cost more than it saves
(1,024 cached tokens = 307 points, versus ~240 points for the whole uncached
system message now). The layout means caching switches on by itself if the
static instructions ever grow.

## Points breakdown

### Question 1: T-1001 (REFUND / returns-within-30-days)

| call | input tokens | cached input tokens | output tokens | points |
|---|---:|---:|---:|---:|
| handle_ticket | 248 | 0 | 46 | 248 × 3 + 46 × 15 = **1,434** |

### Question 2: physical fulfilment path, T-1004 (REPLACE / damage-replacement-7-days)

| stage | model call | input tokens | cached input tokens | output tokens | points |
|---|---|---:|---:|---:|---:|
| triage | no | 0 | 0 | 0 | 0 |
| retrieve | no | 0 | 0 | 0 | 0 |
| compose | yes | 229 | 0 | 36 | 229 × 3 + 36 × 15 = 1,227 |
| audit | no | 0 | 0 | 0 | 0 |
| **total** | | | | | **1,227** |

### Question 2: denial path, T-1002 (SEND_ARTICLE / digital-license-no-refund)

| stage | model call | input tokens | cached input tokens | output tokens | points |
|---|---|---:|---:|---:|---:|
| triage | no | 0 | 0 | 0 | 0 |
| retrieve | no | 0 | 0 | 0 | 0 |
| compose | yes | 239 | 0 | 39 | 239 × 3 + 39 × 15 = 1,302 |
| audit | no | 0 | 0 | 0 | 0 |
| **total** | | | | | **1,302** |

### All tickets (identical for both questions, since both make the same single call)

| ticket | action | kb_article | input | output | points |
|---|---|---|---:|---:|---:|
| T-1001 | REFUND | returns-within-30-days | 248 | 46 | 1,434 |
| T-1002 | SEND_ARTICLE | digital-license-no-refund | 239 | 39 | 1,302 |
| T-1003 | ESCALATE_TIER2 | custom-items-no-replace | 219 | 39 | 1,242 |
| T-1004 | REPLACE | damage-replacement-7-days | 229 | 36 | 1,227 |
| T-1091 (hold-out) | SEND_ARTICLE | subscription-cooling-off | 231 | 38 | 1,263 |

## Code layout

```
shopassist/
  schema.py      Action enum, Resolution, Article, TriageResult
  knowledge.py   KnowledgeBase: index + lexical search
  prompts.py     the single compact prompt
  parsing.py     tolerant JSON extraction
  nodes.py       triage, retrieve, compose, audit
  reporting.py   per-call cost tables
question1/agent.py   SupportCopilot  (one call)
question2/agent.py   SupportPipeline (four stages, one call)
scripts/cost_report.py
```

Both agents are thin wrappers over the same four functions in
`shopassist/nodes.py`, so a prompt or retrieval improvement lands in both.
Neither agent imports `eval/reference.py`, and nothing is keyed on ticket ids.

## Design choices and limits

- **`customer_reply` is still requested**, limited to one short sentence. It is
  not graded, but the product needs it; dropping it would save output tokens at
  the cost of the feature.
- **Top 2 articles, not 1.** Sending one article would save ~75 points but
  leaves the model no alternative when retrieval ranks the governing policy
  second (it does for T-1003). `top_k` is a constructor argument.
- **Lexical retrieval** is enough for a help center of short, distinctly worded
  policies. For a real catalogue with paraphrased questions I would swap
  `KnowledgeBase.search` for embeddings or BM25 plus a reranker; the interface
  stays the same.
- **Output length is not enforced by the client.** `LlmClient.chat` has no
  `max_tokens` parameter. Against a hosted API I would set `max_tokens` and use
  structured output so a customer message such as "explain step by step" cannot
  inflate the reply.
- **The local simulator decides from the order snapshot, not from the prompt.**
  So passing tests proves cost and plumbing, not prompt quality. The prompt was
  written to stand on its own with a real model: it names the allowed actions,
  includes the governing policy text, and keeps every policy-relevant order fact.

## Test changes

`test_baseline_cost_is_high` asserted the baseline stays expensive (> 15,000 and
> 70,000 points), so it necessarily fails once the cost is fixed. Both were
replaced with per-ticket assertions of the assignment targets (≤ 3,000 and
≤ 2,500), covering the hold-out ticket too. `tests/test_shopassist.py` adds unit
tests for retrieval, the prompt, parsing and the audit fallback.
