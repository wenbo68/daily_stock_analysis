  Implement the Intel section redesign for the tiered (alt) analysis page,
  following docs/intel-redesign-plan.md exactly — read that file first and
  treat its "Decisions already made" section as settled; don't redesign.

  First create a feature branch off main (feat/intel-qualitative-collector)
  and do all work there.

  Summary: replace the 4-dimension report block with an Intel section of six
  subject cards (Econ, Technicals, Fundamentals, Behavioral, Events, Analyst).
  The three new qualitative cards are fed by ONE new agentic collector — an
  LLM tool-calling loop (search / read_source / submit_report) that replaces
  the single-shot pipeline in src/tiered_analysis/providers/sentiment.py,
  keeping that pipeline as fallback. The submit_report tool's schema comes
  from the pydantic models in the plan. Post-processing includes the 
  deterministic quote-existence check AND the batched claim-support check
  (plan §3.1 step 2.5, QUALITATIVE_CLAIM_CHECK flag). 

  Before writing code, read these to ground yourself:
  - src/tiered_analysis/providers/sentiment.py  (current pipeline, citation
    verification to preserve, test-injection pattern to copy)
  - src/tiered_analysis/providers/base.py       (DimensionResult/Citation)
  - src/agent/llm_adapter.py + src/agent/runner.py + src/agent/tools/registry.py
    (reuse LLMToolAdapter.call_with_tools and the tool-schema helpers; write a
    small dedicated loop, do not pull in the orchestrator)
  - src/tiered_analysis/earnings.py + providers/fundamentals_us.py (earnings
    date fields move to the Events card; keep plan-warning logic intact)
  - api/v1/endpoints/tiered.py (_serialize_outcome)
  - apps/dsa-web/src/components/tiered-alt/AltDimensions.tsx + AltUi.tsx
    (AltNarrative does NOT render markdown; [n] links come from the citations
    array; keep alt-src-* anchors and sentiment.citation:N chips working)

  Follow the plan's delivery order (section 7), one step at a time, running
  the scoped offline tests (pytest -m "not network") after each backend step
  and npm run lint && npm run build in apps/dsa-web after the frontend step.
  Hard constraints: backend dimension id stays "sentiment"; old run history
  must still render (legacy fallback card); Behavioral and Events cards each
  have a horizontal separator (sentiment | positioning placeholder, and
  past | forward events respectively); no new required config (all
  QUALITATIVE_* env vars optional with plan defaults, added to .env.example);
  budgets enforced in code, never by trusting the model; the model must never
  see or emit URLs. Commit per delivery step, English conventional-commit
  messages, no Co-Authored-By.
