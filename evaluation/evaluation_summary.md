# Evaluation Summary

- Benchmark ID: `637821768a0243714d893cacad966e5f336c1867d0f0dfaa7af17fc86cf3b79c`
- Snapshot SHA-256: `1c31d29dd6718646a9676be3fc6eaa92c4910858afa6f9dd3297b4500f3d47e2`
- Generated: 2026-07-19

## Knowledge-graph evaluation

| Metric | Result |
|---|---:|
| Countries represented | 217 |
| RDF triples | 3197 |
| RDF transformations checked | 1699 |
| RDF transformation fidelity | 100.0% |
| SPARQL/Python equivalence | 100.0% |
| SPARQL/Python values checked | 1482 |
| Consistency violations | 0 |
| SPARQL query latency | 409.28 ms |

## Indicator coverage

| Indicator | Coverage |
|---|---:|
| Population | 100.0% |
| Gdp Per Capita | 85.7% |
| Life Expectancy | 100.0% |

## Closed-book AI answer agreement

| Model | Status | Answered | Pending | Overall | Retrieval | Project-rule |
|---|---|---:|---:|---:|---:|---:|
| GPT-5.6 Sol | Recorded | 11 | 0 | 42.6% | 58.5% | 0.0% |
| GPT-5.6 Terra | Recorded | 11 | 0 | 39.8% | 54.7% | 0.0% |
| GPT-5.6 Luna | Recorded | 11 | 0 | 36.9% | 50.8% | 0.0% |
| GPT-5.5 (older baseline) | Recorded | 11 | 0 | 49.0% | 66.9% | 1.3% |
| Gemini Flash (web) | Recorded | 11 | 0 | 54.8% | 75.3% | 0.0% |
| Claude (web) | Recorded | 11 | 0 | 45.9% | 63.0% | 0.4% |
| DeepSeek (web) | Recorded | 11 | 0 | 38.0% | 52.3% | 0.0% |

This is a closed-book answer-agreement baseline, not a fair test of reasoning on project-rule cases, because models did not receive the frozen triples. All listed model rows contain recorded answers.
