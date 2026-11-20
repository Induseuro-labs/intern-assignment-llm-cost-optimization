# Question 1 — Write-up

## Summary

`SupportCopilot` makes one LLM call per ticket. Two changes to `build_messages` in `question1/agent.py` cut the cost of the four public tickets from **35,271 to 4,461 points, an 87.4% reduction**. Each ticket now costs **1,056–1,200 points**, below the 3,000-point target.

Every public ticket and the holdout `T-1091` return the same `action` and `kb_article` as before:

- T-1001: `REFUND` / `returns-within-30-days`
- T-1002: `SEND_ARTICLE` / `digital-license-no-refund`
- T-1003: `ESCALATE_TIER2` / `custom-items-no-replace`
- T-1004: `REPLACE` / `damage-replacement-7-days`
- T-1091 (holdout): `SEND_ARTICLE` / `subscription-cooling-off`

Only `build_messages` (and the imports and constant it uses) in `question1/agent.py` changed. `parse_resolution` and `handle_ticket` are unchanged.

**All figures are actual tokenizer measurements**, taken with the repository's `shared/billing.py` and `shared/tokens.py` (tiktoken `cl100k_base`). Earlier drafts of this write-up used estimates from a stand-in counter; none of those estimates are used here.

## Cost formula

From the repository README:

```
points = uncached_input × 3 + cached_input × 0.3 + output × 15
```

An output token costs five times as much as an uncached input token. Cached input was 0 in every call (see the breakdown notes).

## The original cost problem

The baseline sent one call per ticket. Its system prompt held a random run ID, four few-shot examples, the full text of every help-center article, and the instruction *"Think step by step. Write full reasoning, quote any article you rely on…"*. Its user message held the ticket ID, the customer thread and the order snapshot.

The local `LlmClient` writes a reasoning reply padded to at least 480 tokens whenever the prompt contains phrases such as "step by step" or "full reasoning". Without them it returns only the JSON object, 36–46 tokens. In the baseline, about **82% of each ticket's cost was output** (for T-1001, 7,305 of 8,886 points).

## Step 1 — Remove the reasoning instruction (output tokens)

The instruction was replaced with `"Instructions: Output JSON with action, kb_article, customer_reply."`. It had contained two of the client's trigger phrases ("step by step" and "full reasoning"). "Quote any article" was removed as part of the same request. No trigger phrase remains in any prompt.

Output fell from 480–495 to 36–46 tokens per ticket. The four-ticket total fell from 35,271 to 8,370 points (−76.3%).

## Step 2 — Remove redundant prompt content (input tokens)

The decision depends only on order fields (product type, opened, license revealed, customized, damage reported, days since delivery, subscription age), and all of them are in the order snapshot. The prompt was cut to a short instruction, the allowed actions, the article IDs (read from `data/kb/` at run time, not hardcoded) and the snapshot.

| Removed (T-1001, real token counts) | Tokens | Why it is safe |
|---|---:|---|
| Random run ID | ~39 (varies with the ID) | Carries no information, and its randomness would also prevent prompt caching. |
| Few-shot examples | 111 | They only showed the output format. The output instruction and the action/article lists replace them. |
| Full help-center text (with label) | 198 | Replaced by the five article IDs. The output must be one of these IDs. |
| Customer thread (with label) | 44 | Repeats facts already in the order (for example "unopened" is `opened: false`). |
| `TICKET_ID` line | 9 | An identifier, not a decision input. |
| Separate system message | not measured separately | Merged into one user message. |

The `ORDER_SNAPSHOT … END_SNAPSHOT` block (87 tokens for T-1001) was kept byte-for-byte.

Input fell from 485–513 to 170–173 tokens per ticket. The four-ticket total fell from 8,370 to 4,461 points (−46.7%).

## Per-call breakdown — T-1001

T-1001 makes one call (`handle_ticket`) in every version.

| Version | Input tokens | Cached input tokens | Output tokens | Input cost | Output cost | **Total** |
|---|---:|---:|---:|---:|---:|---:|
| Original | 527 | 0 | 487 | 1,581 | 7,305 | **8,886** |
| Step 1 | 509 | 0 | 46 | 1,527 | 690 | **2,217** |
| Step 2 (final) | 170 | 0 | 46 | 510 | 690 | **1,200** |

Input cost = uncached input × 3. Output cost = output × 15. Cached input cost is 0 in every row.

- **Cached input is a recorded value, not an assumption.** The billing record (`LlmCall.cached_prefix_tokens`) is 0 for every call because no version passes `cached_prefix` to the client. Caching would not apply anyway: it needs an identical prefix of at least 1,024 tokens, and these prompts are 170–529 tokens.
- **Original and Step 1 vary slightly between runs.** Both prompts start with a random run ID, and the long reply contains a random trace ID. Over five further runs, T-1001 cost 8,814–8,907 points for the original and 2,211–2,229 for Step 1. Step 2 has no random content and was 1,200 on every run.

## All public tickets

| Ticket | Original | Step 1 | Step 2 (final) | Final input / output tokens |
|---|---:|---:|---:|---|
| T-1001 | 8,886 | 2,217 | **1,200** | 170 / 46 |
| T-1002 | 8,748 | 2,082 | **1,104** | 173 / 39 |
| T-1003 | 8,721 | 2,052 | **1,101** | 172 / 39 |
| T-1004 | 8,916 | 2,019 | **1,056** | 172 / 36 |
| **Total** | **35,271** | **8,370** | **4,461** | |
| Holdout T-1091 | 8,754 | 2,064 | 1,113 | 181 / 38 |

**Overall reduction across the four public tickets: (35,271 − 4,461) / 35,271 = 87.4%.**

The original and Step 1 columns come from one recorded run. Five further runs gave four-ticket totals of 35,334–35,661 for the original and 8,358–8,394 for Step 1, so the reduction ranges from 87.4% to 87.5%. The final total of 4,461 matches `python run.py` and was identical on every run.

## Why the ORDER_SNAPSHOT block must remain

`LlmClient.chat` looks for `ORDER_SNAPSHOT: … END_SNAPSHOT` in every prompt and raises an error if it is missing. The order facts inside it are also the only input the decision depends on. The block is kept byte-for-byte as in the baseline (`json.dumps(order, indent=2)`).

## How correctness was preserved

- Only prompt content was changed. The output still has `action`, `kb_article` and `customer_reply`, and `parse_resolution` is unchanged.
- The agent does not import `eval/reference.py`, and no ticket-specific answers were added.
- Each prompt was checked to contain the snapshot markers, and the snapshot in it was checked to parse and match the ticket's order file.

## Test results

`python -m pytest -q tests/test_question1.py`, with the real tokenizer:

| Test | Result |
|---|---|
| `test_baseline_resolves_public_tickets` | Pass (correctness) |
| `test_holdout_subscription` (T-1091) | Pass (correctness) |
| `test_baseline_cost_is_high` | **Fail, expected** (baseline-cost guard) |

`test_baseline_cost_is_high` asserts that the four public tickets cost more than 15,000 points. That records how expensive the baseline was. They now total 4,461, so the assertion no longer holds. This is the intended effect of the optimization, not a correctness failure.

`python run.py` returns the expected action and article for all four public tickets and reports `total_points: 4461`.

## Limitation: removing the help-center text with a real LLM

This works here because the local client derives its answer from the order snapshot alone, so the article text never affects the result. A real LLM decides from the prompt. Without the article text it would lose the exact policy rules, such as the 7-day damage window, the 30-day return window and the subscription cooling-off period, and could make wrong decisions on edge cases (for example damage reported on day 8). With a real model, the safer choice is a one-line summary of each policy, or retrieving only the relevant article. Either would still be far cheaper than the original prompt.
