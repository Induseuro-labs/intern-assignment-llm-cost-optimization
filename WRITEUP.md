# ShopAssist cost optimisation: write-up

## Result

| | Starter (points per ticket) | Now (points per ticket) | Target | Reduction |
|---|---:|---:|---:|---:|
| Question 1 | 8,712 – 8,970 | **1,227 – 1,434** | ≤ 3,000 | ~85% |
| Question 2 | 72,996 – 73,605 | **1,227 – 1,434** | ≤ 2,500 | ~98% |

The graded fields (`action`, `kb_article`) are untouched on the four public
tickets and on the hold-out `T-1091`. The whole suite (37 tests) passes.

Every number below is reproducible with:

```bash
python scripts/cost_report.py
```

## Where the starter spent its points

Billing is `uncached_input × 3 + cached_input × 0.3 + output × 15`, so one
output token costs as much as five input tokens.

**Question 1, T-1001: 8,853 points**

| call | input tokens | output tokens | points |
|---|---:|---:|---:|
| handle_ticket | 526 | 485 | 8,853 |

82% of the bill is output. The prompt told the model to "think step by
step", "write full reasoning" and "quote any article" — text the product
never uses.

**Question 2, T-1001: 73,341 points**

| call | input tokens | output tokens | points |
|---|---:|---:|---:|
| triage | 8,455 | 485 | 32,640 |
| retrieve | 593 | 46 | 2,469 |
| compose | 1,187 | 484 | 10,821 |
| audit | 6,712 | 485 | 27,411 |

Triage and audit each paste a slice of the 210k-token help center into the
prompt, three of the four calls ask for long reasoning, every call re-sends
the previous calls' output (triage is sent to compose twice), and a random
trace id at the top of each prompt defeats prefix caching.

## What changed

### 1. Ask for the answer only (largest saving)

The prompt now requests a bare JSON object and nothing else. Output falls
from ~485 tokens to ~40, which removes about 6,700 points per call.

### 2. Retrieve in code, not in the prompt

`copilot/search.py` builds a small lexical index over the help center
(stemming, stopwords, IDF weighting). The query is the customer thread plus
the order flags that hold. Only the top 2 policies enter the prompt.

This is why Question 2's bill no longer tracks the size of the help center:
the 210k tokens are searched for free in Python and never billed.
`PolicyIndex.from_dump` indexes the expanded help-center dump directly and
discards sections without an article id (they cannot be cited); a test
checks that it yields exactly the same citeable articles as the default
index.

The governing article sits in the top 2 for all five tickets (tested; it
ranks #2 for T-1003, which is why the limit is 2 and not 1).

### 3. One model call instead of four (Question 2)

The four steps are kept, but only the one that needs language understanding
talks to the model:

| step | starter | now |
|---|---|---|
| gather(triage) | model call, 32,640 pts | code: load ticket + order, build lookup query |
| lookup(retrieve)  | model call, 2,469 pts | code: lexical ranking, top 2 policies |
| decide(compose)  | model call, 10,821 pts | **model call, ~1,300 pts** |
| verify(audit)  | model call, 27,411 pts | code: schema and citation checks |

The verify step checks that the action is one of the four allowed values and
that the cited policy exists. Anything unparseable or invalid is downgraded
to `ESCALATE_TIER2` rather than raising, because a wrong automated refund
costs more than a manual review. These checks are deterministic, so code
does them more reliably than a second model call, at zero points.

### 4. Smaller input

- Order snapshot is compact single-line JSON instead of `indent=2`.
- `order_id` and `sku` are dropped: identifiers carry no policy signal. Every
  other field passes through, including fields added in the future.
- Few-shot examples removed; two one-line policies replace the full article dump.
- Markdown decoration stripped from policy text.
- The random run id / trace id is gone.

### 5. Cache-friendly prompt layout

The system message is byte-identical for every ticket and all per-ticket
content comes after it. `stages.decide` passes it as `cached_prefix`
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

| step | model call | input tokens | cached input tokens | output tokens | points |
|---|---|---:|---:|---:|---:|
| gather | no | 0 | 0 | 0 | 0 |
| lookup | no | 0 | 0 | 0 | 0 |
| decide | yes | 229 | 0 | 36 | 229 × 3 + 36 × 15 = 1,227 |
| verify | no | 0 | 0 | 0 | 0 |
| **total** | | | | | **1,227** |

### Question 2: denial path, T-1002 (SEND_ARTICLE / digital-license-no-refund)

| step | model call | input tokens | cached input tokens | output tokens | points |
|---|---|---:|---:|---:|---:|
| gather | no | 0 | 0 | 0 | 0 |
| lookup | no | 0 | 0 | 0 | 0 |
| decide | yes | 239 | 0 | 39 | 239 × 3 + 39 × 15 = 1,302 |
| verify | no | 0 | 0 | 0 | 0 |
| **total** | | | | | **1,302** |

### All tickets (identical for both tracks — both make the same single call)

| ticket | action | kb_article | input | output | points |
|---|---|---|---:|---:|---:|
| T-1001 | REFUND | returns-within-30-days | 248 | 46 | 1,434 |
| T-1002 | SEND_ARTICLE | digital-license-no-refund | 239 | 39 | 1,302 |
| T-1003 | ESCALATE_TIER2 | custom-items-no-replace | 219 | 39 | 1,242 |
| T-1004 | REPLACE | damage-replacement-7-days | 229 | 36 | 1,227 |
| T-1091 (hold-out) | SEND_ARTICLE | subscription-cooling-off | 231 | 38 | 1,263 |

## Code layout

```
copilot/
  model.py      Outcome enum, Decision, Policy, TicketContext
  search.py     PolicyIndex: lexical ranking over the help center
  prompting.py  the single compact prompt
  extract.py    tolerant JSON extraction
  stages.py     build_context, lookup, decide, verify
  costs.py      per-call cost tables
question1/agent.py   SupportCopilot  (one call)
question2/agent.py   SupportPipeline (four steps, one call)
scripts/cost_report.py
```

Both agents are thin wrappers over the same four functions in
`copilot/stages.py`, so a prompt or retrieval improvement lands in both.
Neither agent imports `eval/reference.py`, and nothing is keyed on ticket ids.

## Design choices and limits

- **`customer_reply` is still requested**, limited to one short sentence. It
  is not graded, but the product needs it; dropping it would save output
  tokens at the cost of the feature.
- **Top 2 policies, not 1.** Sending one policy would save ~75 points but
  leaves the model no alternative when retrieval ranks the governing article
  second (it does for T-1003). `article_limit` is a constructor argument.
- **Lexical retrieval** is enough for a help center of short, distinctly
  worded policies. For a real catalogue I would swap `PolicyIndex.rank`
  for embeddings or BM25 plus a reranker; the interface stays the same.
- **Output length is not enforced by the client.** `LlmClient.chat` has no
  `max_tokens` parameter. Against a hosted API I would set `max_tokens` and
  use structured output so a customer message such as "explain step by step"
  cannot inflate the reply.
- **The local simulator decides from the order snapshot, not from the
  prompt.** So passing tests proves cost and plumbing, not prompt quality.
  The prompt was written to stand on its own with a real model: it names the
  allowed actions, includes the governing policy text, and keeps every
  policy-relevant order fact.

## Test changes

`test_baseline_cost_is_high` asserted the starter stays expensive (> 15,000
and > 70,000 points), so it necessarily fails once the cost is fixed. Both
were replaced with per-ticket assertions of the assignment targets (≤ 3,000
and ≤ 2,500), covering the hold-out ticket too. `tests/test_copilot.py` adds
unit tests for retrieval, the prompt, parsing and the verify fallback.
