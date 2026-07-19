# Explainable Country Development Knowledge Graph

This project transforms official World Bank data into a typed RDF knowledge graph. It supports real SPARQL queries, transparent symbolic rules, explainable country-similarity ranking, and a reproducible evaluation of RDF transformation fidelity plus closed-book AI answer agreement.

## Trusted Knowledge Sources

- World Bank Country API: https://datahelpdesk.worldbank.org/knowledgebase/articles/898590-country-api-queries
- World Bank Indicators API: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392

The graph represents country metadata plus population, GDP per capita, and life expectancy. Aggregate records such as `World` are filtered out.

## Professional Features

- Typed RDF classes: `Country`, `Region`, and `IncomeLevel`
- RDF object and datatype properties exported as valid Turtle
- Real RDFLib SPARQL execution
- Symbolic rule: same World Bank region and income level
- Five-factor explainable similarity score
- Life-expectancy outlier inference relative to income-group averages
- Live CLI queries with score contributions and reasoning traces
- Automated unit tests and quantitative evaluation
- Hashed data snapshots, separate ground truth, and objective scoring for AI baselines

## Quick Start

This working copy has its own Python environment, so a global `python` command is not required here. Virtual environments are intentionally omitted from the submission ZIP; on another machine, create `.venv` with Python 3.12 and install `requirements.txt` first.

```powershell
py -3.12 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

```powershell
& ".\.venv\Scripts\python.exe" ".\worldbank_country_kg.py" --demo
```

Start the live interactive menu:

```powershell
& ".\.venv\Scripts\python.exe" ".\worldbank_country_kg.py"
```

Regenerate the RDF graph and data snapshot:

```powershell
& ".\.venv\Scripts\python.exe" ".\worldbank_country_kg.py" --write-outputs --output-dir ".\data" --demo
```

Run all automated tests:

```powershell
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v
```

Run the evaluation and rescore recorded model answers:

```powershell
& ".\.venv\Scripts\python.exe" ".\evaluate_project.py" --output-dir ".\evaluation"
```

## IntelliJ IDEA

Open this folder as a project and choose one of the included run configurations:

- `Run Enhanced World Bank KG Demo`
- `Run Live Interactive Queries`
- `Run Evaluation Benchmark`
- `Run Automated Tests`

Select `.venv\Scripts\python.exe` as the project interpreter if IntelliJ asks.

## Explainable Similarity

The ranking uses explicit weights rather than a hidden model:

```text
score = 0.30 * same_region
      + 0.25 * same_income_level
      + 0.20 * gdp_per_capita_closeness
      + 0.15 * life_expectancy_closeness
      + 0.10 * population_closeness
```

Every result includes its score, factor contributions, evidence coverage, and plain-language reasons. When either country lacks a numeric indicator, that factor is marked unavailable, the available weights are normalized, and the final score is multiplied by evidence coverage so missing data cannot improve a country's rank.

## Evaluation

The evaluation covers four dimensions:

1. Unit tests on synthetic countries with known expected inferences.
2. RDF transformation checks against normalized World Bank objects. This measures encoding fidelity, not independent source accuracy.
3. Multi-field SPARQL/Python equivalence across country metadata and indicators, plus consistency constraints, coverage, and latency.
4. An exploratory 11-question closed-book answer-agreement baseline with recorded GPT-5.5, GPT-5.6, Google Gemini Flash, Anthropic Claude Sonnet 4.5, and DeepSeek web-chat answer sets.

The prompt, ground-truth, and model-answer files carry matching question, ground-truth, and snapshot hashes. The evaluator refuses to score recorded answers after the data or questions change. Text uses normalized exact match, unordered lists use set F1, ranked lists add positional agreement, and numbers use relative error. Project-rule scores in the closed-book run are answer agreement only because the models did not receive the frozen triples; use `evaluation/fair_reasoning_protocol.md` for a controlled reasoning comparison.

To collect an additional model fairly, use the exact batch prompt in `evaluation/external_model_collection_guide.md`, paste the returned JSON into that model's entry in `evaluation/model_answers.json`, and rerun the evaluation command. `DeepSeek` is the correct spelling of the tool sometimes called `OpenSeek`.

## Project Structure

```text
worldbank_country_kg.py       Main graph, SPARQL, reasoning, and CLI
evaluate_project.py          Quantitative and AI-comparison evaluation
requirements.txt             Pinned RDFLib dependency
tests/                       Automated reasoning and evaluation tests
data/                        Generated JSON, Turtle, and demo output
evaluation/                  Questions, ground truth, raw model answers, results
report/                      Official-template report draft and architecture figure
```
