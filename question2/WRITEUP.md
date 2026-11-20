# Question 2 — Write-up

## Summary

The four-stage `SupportPipeline` cost about **73,000 points per ticket**. After optimization every public ticket costs **1,872–2,190 points**, below the 2,500 limit. That is a **97.3% reduction** across the four public tickets. Every public ticket returns the same `action` and `kb_article` as before.

The pipeline still runs TRIAGE → RETRIEVE → COMPOSE → AUDIT inside `SupportPipeline.handle_ticket(ticket_id)`. It now uses **two LLM calls (Triage, Compose) and two deterministic Python stages (Retrieve, Audit)**. Only `question2/agent.py` was changed.

**All figures are actual tokenizer measurements**, taken with the repository's `shared/billing.py` and `shared/tokens.py` (tiktoken `cl100k_base`). The vocabulary download was blocked in the environment used, so the file was rebuilt from the npm `tiktoken` package, verified against tiktoken's expected SHA-256 hash (`223921b7…65b2a7`), and loaded through `TIKTOKEN_CACHE_DIR`. No repository code was changed for this.

Cost formula (README): `points = uncached_input × 3 + cached_input × 0.3 + output × 15`

## Original pipeline and its cost problem

All four original stages were LLM calls:

| Stage | What it received | What it returned |
|---|---|---|
| Triage | Random trace ID, "restate the ticket step by step", article titles, the first 120,000 characters of the help center, thread, snapshot | ~485-token reasoning trace |
| Retrieve | "Print full text of the eight most relevant help articles", triage output, snapshot | The decision JSON only (the local client never returns article text) |
| Compose | "Full reasoning…", thread, snapshot, triage output **twice**, retrieve output | ~485-token reasoning trace |
| Audit | The first 80,000 characters of the help center, "double-check policy…", thread, snapshot, draft, triage output, retrieve output | ~485-token reasoning trace |

Main sources of waste (T-1001):

- **Help-center text sent to the model twice:** about 8,450 input tokens in Triage and about 6,700 in Audit.
- **Long-reply trigger phrases** ("step by step", "restate the ticket", "full reasoning", "double-check") in three stages. Each forced a ~485-token reply, about 7,300 points per stage.
- **Duplicated context:** the thread was sent three times, and the triage trace three times.
- **A paid model call for retrieval** that never returned any article text.

Triage (about 32,600 points) and Audit (about 27,400) were 82% of the cost.

## Why Retrieve and Audit are deterministic stages

`shared/llm.py` always replies with the decision JSON: 36–46 tokens, or 540–690 points per call. Every call must also include the `ORDER_SNAPSHOT … END_SNAPSHOT` block, or the client raises an error. A call whose prompt is nothing but a compact snapshot already costs 741–885 points, so the minimum cost per ticket is:

| LLM calls per ticket | Minimum cost | Meets ≤ 2,500 on every ticket? |
|---|---|---|
| 4 | 2,964–3,540 | No, none of them |
| 3 | 2,223–2,655 | No, T-1001 needs at least 2,655 |
| 2 | 1,482–1,770 | Yes |

The specification describes a "four-node production pipeline… triage → retrieve → compose → audit". It does not say each node must be an LLM call, and four (or three) calls cannot meet its own target with this client. Triage and Compose make judgments and use the model. Retrieve (looking up a document) and Audit (checking an answer against rules) do not need one.

## What each stage does now

| Stage | Type | Input | Output |
|---|---|---|---|
| Triage | LLM call | Allowed actions, the five article IDs from `data/kb`, order snapshot | Proposed action and article |
| Retrieve | Python | Triage's proposal | The article's actual content, or a rejection |
| Compose | LLM call | Triage proposal (one line), the retrieved policy text, order snapshot | Final JSON (`action`, `kb_article`, `customer_reply`) |
| Audit | Python | Triage proposal, retrieval result, Compose draft | The draft if every check passes, otherwise an ESCALATE_TIER2 resolution |

Both LLM prompts are 126–139 tokens, with no thread, trace IDs, trigger phrases or help-center dump. The snapshot is sent as compact JSON (same facts, about 24 fewer tokens per call).

**Retrieve** checks the proposed article ID against `shared.kb.article_ids()`, the list of articles in `data/kb`, and loads the article with `shared.kb.load_article`. It returns the full Markdown content plus the retrieved policy text that Compose receives (the article body without its heading or bold markers). An unknown or missing ID is rejected: Retrieve returns no article, and Compose is told "none found". Retrieve does not search for relevant articles by itself; it validates and loads the article Triage proposed.

**Audit** runs six checks and passes the draft through unchanged only if all of them pass:

| Check | What it verifies | Independent of Triage? |
|---|---|---|
| `draft_parses` | The draft is JSON with `action` and `kb_article` (via `parse_resolution`) | Yes |
| `action_allowed` | The action is one of REFUND, REPLACE, SEND_ARTICLE, ESCALATE_TIER2 | Yes |
| `article_exists` | The article is in `data/kb` | Yes |
| `action_permitted_by_policy` | The action is permitted by the cited article (table below) | **Yes** |
| `article_matches_retrieval` | The article is the one Retrieve loaded | No (Retrieve loads Triage's article) |
| `agrees_with_triage` | Action and article equal Triage's proposal | No |

`action_permitted_by_policy` is what stops a wrong answer from passing just because Triage and Compose agree. Its table comes from the wording of each article:

| Article | Policy wording | Permitted actions |
|---|---|---|
| `custom-items-no-replace` | "not eligible for automated replacement; route to Tier 2" | ESCALATE_TIER2 |
| `damage-replacement-7-days` | "qualify for a free replacement shipment" | REPLACE, ESCALATE_TIER2 |
| `digital-license-no-refund` | "not refundable after the license key… has been revealed" | SEND_ARTICLE, ESCALATE_TIER2 |
| `returns-within-30-days` | "may be refunded within 30 days of delivery" | REFUND, ESCALATE_TIER2 |
| `subscription-cooling-off` | "prorated refund if cancelled within 30 days… After day 30, no automatic refund" | REFUND, SEND_ARTICLE, ESCALATE_TIER2 |

ESCALATE_TIER2 is permitted under every article because a human review is always a safe outcome. An article missing from the table permits nothing, so Audit fails closed.

If any check fails, Audit returns ESCALATE_TIER2. It cites the article Retrieve verified, but only if that article's entry in the table explicitly permits ESCALATE_TIER2. Otherwise it cites no article (`kb_article` is empty). It never cites an article taken from the unverified Compose draft.

This is a compatibility check, not a re-implementation of the routing decision. It does not read order facts.

**Caching was not used.** It needs an identical prefix of at least 1,024 tokens, and each prompt is 126–139 tokens. The order snapshot is different for every ticket, so it cannot be part of a shared cached prefix and stays at the full input price. Padding the prompts to a 1,024-token cached prefix would therefore cost at least 496–505 input points per call (at least 307 for the cached prefix plus 189–198 for the uncached snapshot), compared with 378–417 today. The billing records show 0 cached tokens in every version.

## Cost comparison (points per ticket)

| Ticket | Path | Original | Optimized | Reduction |
|---|---|---:|---:|---:|
| T-1001 | REFUND | 73,275 | **2,190** | 97.0% |
| T-1002 | SEND_ARTICLE (denial) | 72,993 | **1,974** | 97.3% |
| T-1003 | ESCALATE_TIER2 | 72,963 | **1,977** | 97.3% |
| T-1004 | REPLACE | 73,425 | **1,872** | 97.5% |
| **Total** | | **292,656** | **8,013** | **97.3%** |

The original figures come from one recorded run. They vary by a few tokens between runs because of random trace IDs. The optimized pipeline has no random content, and adding the Audit policy check changed no token counts (the billing records are identical before and after it). Between 58% and 63% of the remaining cost (63% for T-1001) is the fixed reply size of the two LLM calls.

## Per-stage breakdowns

Points = input points + output points. Cached input was 0 in every call, so cached input points are 0 throughout. "Python stage" means the billing session has no record for that stage, because no model was called.

### T-1004 — physical fulfillment (REPLACE / damage-replacement-7-days)

| Stage | Version | Input tokens | Cached | Output tokens | Input points | Output points | **Total** |
|---|---|---:|---:|---:|---:|---:|---:|
| Triage | Original | 8,440 | 0 | 492 | 25,320 | 7,380 | 32,700 |
| | Optimized | 138 | 0 | 36 | 414 | 540 | **954** |
| Retrieve | Original | 602 | 0 | 36 | 1,806 | 540 | 2,346 |
| | Optimized | Python stage | — | — | 0 | 0 | **0** |
| Compose | Original | 1,174 | 0 | 491 | 3,522 | 7,365 | 10,887 |
| | Optimized | 126 | 0 | 36 | 378 | 540 | **918** |
| Audit | Original | 6,699 | 0 | 493 | 20,097 | 7,395 | 27,492 |
| | Optimized | Python stage | — | — | 0 | 0 | **0** |
| **Ticket** | Original | 16,915 | 0 | 1,512 | 50,745 | 22,680 | **73,425** |
| | Optimized | 264 | 0 | 72 | 792 | 1,080 | **1,872** |

### T-1003 — escalation (ESCALATE_TIER2 / custom-items-no-replace)

| Stage | Version | Input tokens | Cached | Output tokens | Input points | Output points | **Total** |
|---|---|---:|---:|---:|---:|---:|---:|
| Triage | Original | 8,438 | 0 | 481 | 25,314 | 7,215 | 32,529 |
| | Optimized | 138 | 0 | 39 | 414 | 585 | **999** |
| Retrieve | Original | 591 | 0 | 39 | 1,773 | 585 | 2,358 |
| | Optimized | Python stage | — | — | 0 | 0 | **0** |
| Compose | Original | 1,153 | 0 | 481 | 3,459 | 7,215 | 10,674 |
| | Optimized | 131 | 0 | 39 | 393 | 585 | **978** |
| Audit | Original | 6,679 | 0 | 491 | 20,037 | 7,365 | 27,402 |
| | Optimized | Python stage | — | — | 0 | 0 | **0** |
| **Ticket** | Original | 16,861 | 0 | 1,492 | 50,583 | 22,380 | **72,963** |
| | Optimized | 269 | 0 | 78 | 807 | 1,170 | **1,977** |

## Correctness and tests

**Graded fields:** all four public tickets return the expected action and article (`python run.py`, total 8,013 points). On each ticket, all six Audit checks pass, Retrieve loads the matching article from `data/kb`, and both LLM prompts contain the snapshot markers and no trigger phrases.

**`python -m pytest -q ../tests/test_question2.py`** (run from `question2/`, real tokenizer):

| Test | Original | Optimized |
|---|---|---|
| `test_help_center_exceeds_context` | Pass | Pass |
| `test_pipeline_resolves_public_tickets` | Pass | Pass |
| `test_baseline_cost_is_high` | Pass | **Fail, expected**: it asserts T-1001 costs more than 70,000 points, and it now costs 2,190 |

No test, shared module, data file or reference file was modified.

**Audit probes.** These ran in a temporary script outside the repository. Each case went through `handle_ticket` with real ticket data and scripted Triage/Compose replies.

| Case | Audit | Final result |
|---|---|---|
| REFUND + custom-items-no-replace (Triage and Compose agree) | Rejected (policy) | ESCALATE_TIER2 / custom-items-no-replace |
| REPLACE + custom-items-no-replace (agree) | Rejected (policy) | ESCALATE_TIER2 / custom-items-no-replace |
| REPLACE + digital-license-no-refund (agree) | Rejected (policy) | ESCALATE_TIER2 / digital-license-no-refund |
| REFUND + digital-license-no-refund (agree) | Rejected (policy) | ESCALATE_TIER2 / digital-license-no-refund |
| REFUND + returns-within-30-days | Passed | REFUND / returns-within-30-days |
| REPLACE + damage-replacement-7-days | Passed | REPLACE / damage-replacement-7-days |
| SEND_ARTICLE + subscription-cooling-off | Passed | SEND_ARTICLE / subscription-cooling-off |
| Unknown article ID (agree) | Rejected | ESCALATE_TIER2 / no article |
| Invalid JSON from Compose | Rejected | ESCALATE_TIER2 / damage-replacement-7-days |
| Invalid JSON from Triage | Rejected | ESCALATE_TIER2 / no article |
| Compose disagrees with Triage | Rejected | ESCALATE_TIER2 / damage-replacement-7-days |
| Compose cites a different article than retrieved | Rejected | ESCALATE_TIER2 / damage-replacement-7-days |
| Action outside the allowed set | Rejected | ESCALATE_TIER2 / returns-within-30-days |

## How the architecture was preserved

`SupportPipeline` and `handle_ticket(ticket_id)` keep their signatures. All four stages run on every ticket, in order, each in its own method. Each stage uses the previous stage's output: Triage's proposal decides what Retrieve loads, Compose uses both, and Audit checks Compose against the policy, the retrieval and Triage. `parse_resolution` still parses the final answer. The agent does not import `eval/reference.py`, and nothing depends on a ticket ID.

## Limitations and trade-offs

- **Two of the four stages are not LLM calls.** A reviewer who reads "node" as "LLM call" would see this differently. The arithmetic above shows that reading cannot meet 2,500 per ticket with this client.
- **Audit checks compatibility, not eligibility.** It confirms the action is one the cited policy can justify, but it does not check order facts such as the 7-day or 30-day windows or whether an item was opened. A refund under `returns-within-30-days` on day 40 would pass. Checking that would mean rebuilding the routing decision, which the brief excluded.
- **The compatibility table is maintained by hand.** If an article is added or its wording changes, the table must be updated. Until then, a new article permits nothing and its tickets are escalated.
- **Retrieve does not search for relevant articles.** It validates and loads the article Triage proposed. If Triage chose a valid but wrong article, Compose would see that policy, and Audit would catch the error only if the action is incompatible with it. With a larger, real help center, retrieval should search the help center for several candidate articles.
- **An escalation cites no article** (`kb_article` is empty) when Retrieve verified none, for example after an unknown article ID or an unparseable Triage reply, because no verified policy applies.
- **The local client decides from the snapshot alone.** That is why removing the customer thread is safe here. A real model might need the customer's wording.
