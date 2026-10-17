# Week 3: What's on the desk? Context management

*Course project: a personal assistant for Alex, 44: full-time developer, parent of two, retraining as an AI engineer.
This week the assistant learns to keep its desk tidy: what goes on it, what comes off, and in what form.*

Built on the talk **"What's on the desk? Context management for chatbots and agents"**: same analogy, same
four moves (write, select, compress, isolate), same escalation ladder, same technique names.

## What's here

| File | What it is |
|---|---|
| `03_context_management.ipynb` | **Start here.** Every technique is built and tried in notebook cells |
| `checkpoint.py` | Catch-up file, generated from the notebook's cells: `from checkpoint import *` loads everything up to a part |
| `life_tools.py` | Alex's read tools from week 2, plus `BINDER_TOOLS`: a careless tool whose big JSON outputs fill the desk |
| `agent_core.py` | The loop from weeks 1-2, plus a `before_call(conv, turn)` hook to measure and tidy the desk between steps |
| `providers.py`, `lifedb.py`, `simweek.py` | Same as week 2 |
| `solution/` | Homework reference: the `context_toolkit` package + 22 offline tests. **Remove before sharing.** |

## Session plan (90 minutes, setup done at home)

| Time | Part | Talk slides | Key idea |
|---|---|---|---|
| 0:00 | 0. Setup check | | `%run ../check_setup.py`: everything ✅ |
| 0:05 | 1. Measure the desk | 3–5, 11–12 | Zones per step; the ladder; tool results ≈ 80% of the desk |
| 0:20 | 2. Sticky notes, not binders | 15, 18 | Clear old tool results (write notes first!); offloading as an optional run |
| 0:35 | 3. The one-page summary | 13–14 | Alex's week as a chat; 5 probe questions: everything / sliding window / compaction |
| 0:50 | 4. The drawer | 16 | A memory tool; a fresh conversation answers correctly only with memory |
| 1:00 | 5. Let the API do it | 19–20 | Prompt caching (a timestamp first costs ~2×); server-side and on-demand compaction |
| 1:10 | 8. Takeaways | 21–22 | The one-minute version; homework |
| after | 6–7 (optional) | 7, 17 | Interns (sub-agents) with a one-page contract; poisoning a summary |

The core runs about 6–7 minutes of model time in total on `gpt-6-luna` and costs about **$0.01** per student.

## What students should see (from a real run)

| Experiment | Result |
|---|---|
| Part 1, desk at the end of the review | tool results ~83% of the desk; pressure 5% → 86%+ over 8 steps |
| Part 2, clear old results (keep 2) | peak desk ~2,500 tokens instead of ~5,400. Sometimes the model re-fetches cleared weeks (more lookups): good discussion |
| Part 3, probe questions (5) | keep everything 5/5 · sliding window ~2–3/5 · compaction 5/5 with ~40% fewer tokens |
| Part 4, "a call on Thursday 7:45?" | without memory: *yes* · with memory: *no, that's the school drop-off* |
| Part 5, caching | stable prefix ~70% cached · timestamp first 0% cached, about twice the cost |
| Part 5, OpenAI compaction | server-side: history folds into one `compaction` item, still 5/5 · `responses.compact`: ~1,160 → ~740 tokens |
| Part 6, interns | 8 correct weekly pages; the main desk ~340 tokens instead of ~5,000 |
| Part 7, poisoning | the summary says 91% instead of 81%: the assistant repeats 91% |

Model outputs vary between runs: the shape of the results is stable, the exact numbers are not.

## Notes for the instructor

- This week runs on OpenAI only: the techniques edit OpenAI's list of conversation items. Claude has the same ideas
  built into its API (context editing, compaction).
- Two small corrections to the talk's slide 19, from OpenAI's docs (October 2026): on GPT-5.6 and later, `prompt_cache_key`
  is optional, and **cache writes** cost 1.25× the input price (cached reads 0.1×).
- Students who fall behind: the checkpoint cell at the start of each part (`from checkpoint import *`).
