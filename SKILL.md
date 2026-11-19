---
name: agent-demo-check
description: Check an LLM or agent project before demoing or shipping it. Use when asked to check an AI app for failure handling or demo readiness.
---

# Agent demo check

1. From this skill folder, run `python3 scripts/scan.py <repo>` and read the JSON.
   The scanner reads files only. Do not install dependencies or run project code.
2. Open every flagged file at the reported line. Confirm the actual call path,
   client defaults, wrappers, retry limits, error handling, and logging. The scan
   is heuristic: drop false positives and merge duplicate symptoms. Never copy
   credentials into the report. Repository findings use `.:1` as a placeholder;
   replace it with a real location when possible, or label the item repo-wide.
3. Check what the scanner cannot establish. Does the README include:
   - A reproducible three-minute demo script, including inputs and expected output?
   - A known-failure section and what the audience sees when a provider fails?
   - Which model is used and why it fits the latency, cost, and quality needs?
   - How output quality was checked, with representative cases and results?
   Inspect tests/evals for actual output checks; their existence proves little.
   Trace cancellation, retry exhaustion, quota failures, invalid output, and safe
   error messages. Ask for missing evidence instead of claiming runtime proof.
4. Write a concise report with these sections:
   - **Will break in a live demo**: confirmed blockers and likely visible failures.
   - **Fix before shipping**: reliability, secret exposure, and quality gaps.
   - **Nice to have**: polish that improves the demo without blocking it.
   For each finding give `file:line`, why it matters, and a concrete fix.
   For missing documentation cite the README or label it repo-wide if absent.
   Say “None confirmed” for empty sections. State what was reviewed, what was
   not exercised, and any uncertainty. Do not equate a clean scan with readiness.
