# Fair Reasoning Comparison Protocol

Use this as the controlled follow-up to the closed-book answer-agreement baseline.

1. Freeze one graph snapshot and record its `snapshot_hash` and `benchmark_id`.
2. Build an evidence packet containing only the triples and indicator values required by each question.
3. Give every system the identical evidence packet, exact rule definitions, output schema, and no external tools.
4. Test at least three model families and repeat each condition three times with recorded model identifiers and parameters.
5. Score text by normalized exact match, sets by F1, ranked results by F1 plus positional agreement, and numeric results by relative error.
6. Report retrieval and project-rule questions separately, including mean, standard deviation, latency, invalid-output rate, and bootstrap confidence intervals.
7. Preserve raw prompts, raw responses, run IDs, timestamps, and hashes so another researcher can audit every score.

This design answers a different question from the current closed-book baseline: it tests whether systems can execute the same rules over the same evidence, rather than whether they already know the latest World Bank facts.
