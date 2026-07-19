"""Reproducible evaluation utilities for the World Bank knowledge graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal
from rdflib.namespace import RDF

from worldbank_country_kg import (
    COUNTRY,
    INCOME,
    REGION,
    WBKG,
    WorldBankKnowledgeGraph,
    fetch_world_bank_data,
    indicator_value,
    safe_curie,
)


DEFAULT_MODEL_PROVENANCE = {
    "GPT-5.5 (older baseline)": {
        "provider_family": "OpenAI GPT-5.5",
        "comparison_role": "Older GPT baseline",
        "collection_method": "Fresh closed-book isolated run",
    },
    "GPT-5.6 Sol": {
        "provider_family": "OpenAI GPT-5.6",
        "comparison_role": "Current GPT variant",
        "collection_method": "Fresh closed-book isolated run",
    },
    "GPT-5.6 Terra": {
        "provider_family": "OpenAI GPT-5.6",
        "comparison_role": "Current GPT variant",
        "collection_method": "Fresh closed-book isolated run",
    },
    "GPT-5.6 Luna": {
        "provider_family": "OpenAI GPT-5.6",
        "comparison_role": "Current GPT variant",
        "collection_method": "Fresh closed-book isolated run",
    },
    "Gemini Flash (web)": {
        "provider_family": "Google Gemini",
        "comparison_role": "Cross-vendor web baseline",
        "collection_method": "Fresh web chat",
    },
    "Claude (web)": {
        "provider_family": "Anthropic Claude",
        "comparison_role": "Cross-vendor web baseline",
        "collection_method": "Fresh web chat",
    },
    "DeepSeek (web)": {
        "provider_family": "DeepSeek",
        "comparison_role": "Cross-vendor web baseline",
        "collection_method": "Fresh web chat",
    },
}


@dataclass
class BenchmarkCase:
    id: str
    question: str
    answer_type: str
    expected: Any
    tolerance: float = 0.0
    category: str = "retrieval"


@dataclass
class AnswerScore:
    score: float
    correct: bool
    precision: float = 0.0
    recall: float = 0.0
    detail: str = ""


@dataclass
class ProjectEvaluation:
    country_count: int
    rdf_triples: int
    facts_checked: int
    rdf_transformation_fidelity: float
    sparql_equivalence: float
    sparql_values_checked: int
    consistency_violations: list[str]
    indicator_coverage: dict[str, float]
    query_latency_ms: float


@dataclass
class ModelEvaluation:
    model: str
    collection_status: str
    answered: int
    pending: int
    mean_score: float
    case_scores: dict[str, AnswerScore]
    category_scores: dict[str, float]


def normalize_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())


def parse_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:[,.]\d+)*", str(value))
    if not match:
        return None
    candidate = match.group(0).replace(",", "")
    try:
        return float(candidate)
    except ValueError:
        return None


def parse_collection(value: Any) -> list[Any]:
    if not isinstance(value, str):
        return list(value)
    stripped = value.strip()
    try:
        decoded = json.loads(stripped)
        if isinstance(decoded, list):
            return decoded
    except json.JSONDecodeError:
        pass
    separated = [item.strip() for item in re.split(r"[;\n]+", stripped) if item.strip()]
    if len(separated) > 1:
        return separated
    return [item.strip() for item in stripped.split(",") if item.strip()]


def score_external_answer(case: BenchmarkCase, answer: Any) -> AnswerScore:
    if answer is None:
        return AnswerScore(score=0.0, correct=False, detail="No answer supplied")

    if case.answer_type == "text":
        correct = normalize_text(answer) == normalize_text(case.expected)
        return AnswerScore(
            score=1.0 if correct else 0.0,
            correct=correct,
            precision=1.0 if correct else 0.0,
            recall=1.0 if correct else 0.0,
            detail="Exact normalized text match" if correct else "Text does not match the ground truth",
        )

    if case.answer_type in {"set", "ranked"}:
        supplied_items = parse_collection(answer)
        expected = {normalize_text(item) for item in case.expected}
        supplied = {normalize_text(item) for item in supplied_items}
        true_positives = len(expected & supplied)
        precision = true_positives / len(supplied) if supplied else 0.0
        recall = true_positives / len(expected) if expected else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if case.answer_type == "ranked":
            expected_order = [normalize_text(item) for item in case.expected]
            supplied_order = [normalize_text(item) for item in supplied_items]
            expected_positions = {item: index for index, item in enumerate(expected_order)}
            supplied_positions = {item: index for index, item in enumerate(supplied_order)}
            position_credit = sum(
                1.0 / (1.0 + abs(expected_positions[item] - supplied_positions[item]))
                for item in expected & supplied
            )
            order_score = position_credit / len(expected_order) if expected_order else 1.0
            score = f1 * order_score
            correct = expected_order == supplied_order
            detail = f"Set F1 {f1:.3f}; positional agreement {order_score:.3f}"
        else:
            score = f1
            correct = expected == supplied
            detail = f"Matched {true_positives} of {len(expected)} expected items"
        return AnswerScore(
            score=score,
            correct=correct,
            precision=precision,
            recall=recall,
            detail=detail,
        )

    if case.answer_type == "number":
        supplied = parse_number(answer)
        if supplied is None:
            return AnswerScore(score=0.0, correct=False, detail="No numeric value found")
        expected = float(case.expected)
        relative_error = abs(supplied - expected) / max(abs(expected), 1.0)
        if case.tolerance == 0:
            score = 1.0 if relative_error == 0 else 0.0
        else:
            score = max(0.0, 1.0 - relative_error / case.tolerance)
        return AnswerScore(
            score=score,
            correct=relative_error <= case.tolerance,
            precision=score,
            recall=score,
            detail=f"Relative error: {relative_error:.4f}",
        )

    raise ValueError(f"Unsupported answer type: {case.answer_type}")


def compare_external_models(
    cases: list[BenchmarkCase],
    model_answers: dict[str, dict[str, Any]],
) -> dict[str, ModelEvaluation]:
    comparison: dict[str, ModelEvaluation] = {}
    for model, answers in model_answers.items():
        case_scores: dict[str, AnswerScore] = {}
        for case in cases:
            if answers.get(case.id) is not None:
                case_scores[case.id] = score_external_answer(case, answers[case.id])
        answered = len(case_scores)
        collection_status = "Recorded" if answered == len(cases) else "Partial" if answered else "Pending"
        mean_score = sum(score.score for score in case_scores.values()) / answered if answered else 0.0
        category_scores: dict[str, float] = {}
        for category in sorted({case.category for case in cases}):
            scores = [
                case_scores[case.id].score
                for case in cases
                if case.category == category and case.id in case_scores
            ]
            category_scores[category] = sum(scores) / len(scores) if scores else 0.0
        comparison[model] = ModelEvaluation(
            model=model,
            collection_status=collection_status,
            answered=answered,
            pending=len(cases) - answered,
            mean_score=mean_score,
            case_scores=case_scores,
            category_scores=category_scores,
        )
    return comparison


def evaluate_project(graph: WorldBankKnowledgeGraph) -> ProjectEvaluation:
    rdf_graph = Graph().parse(data=graph.to_turtle(), format="turtle")
    checked = 0
    correct = 0
    predicate_by_indicator = {
        "SP.POP.TOTL": WBKG.populationTotal,
        "NY.GDP.PCAP.CD": WBKG.gdpPerCapitaCurrentUsd,
        "SP.DYN.LE00.IN": WBKG.lifeExpectancyYears,
    }

    for country in graph.countries:
        country_uri = COUNTRY[country.code]
        expected_triples = [
            (country_uri, RDF.type, WBKG.Country),
            (country_uri, WBKG.name, Literal(country.name)),
            (country_uri, WBKG.hasRegion, REGION[safe_curie(country.region_id)]),
            (country_uri, WBKG.hasIncomeLevel, INCOME[safe_curie(country.income_id)]),
        ]
        if country.capital:
            expected_triples.append((country_uri, WBKG.hasCapital, Literal(country.capital)))
        for triple in expected_triples:
            checked += 1
            if triple in rdf_graph:
                correct += 1
        for indicator_code, predicate in predicate_by_indicator.items():
            expected_value = indicator_value(country, indicator_code)
            if expected_value is None:
                continue
            checked += 1
            actual_values = [Decimal(str(value.toPython())) for value in rdf_graph.objects(country_uri, predicate)]
            if Decimal(str(expected_value)) in actual_values:
                correct += 1

    query_started = time.perf_counter()
    rows = graph.execute_sparql(
        """
        PREFIX wbkg: <https://example.org/worldbank-country-kg/>
        SELECT ?country ?name ?region ?income ?capital ?population ?gdp ?life WHERE {
            ?country a wbkg:Country ;
                     wbkg:name ?name ;
                     wbkg:hasRegion ?region ;
                     wbkg:hasIncomeLevel ?income .
            OPTIONAL { ?country wbkg:hasCapital ?capital . }
            OPTIONAL { ?country wbkg:populationTotal ?population . }
            OPTIONAL { ?country wbkg:gdpPerCapitaCurrentUsd ?gdp . }
            OPTIONAL { ?country wbkg:lifeExpectancyYears ?life . }
        }
        """
    )
    query_latency_ms = (time.perf_counter() - query_started) * 1000
    rows_by_code = {row["country"].rsplit("/", 1)[-1]: row for row in rows}
    sparql_values_checked = 0
    equivalent = 0
    for country in graph.countries:
        expected: dict[str, Any] = {
            "name": country.name,
            "region": str(REGION[safe_curie(country.region_id)]),
            "income": str(INCOME[safe_curie(country.income_id)]),
        }
        if country.capital:
            expected["capital"] = country.capital
        for key, indicator_code in (
            ("population", "SP.POP.TOTL"),
            ("gdp", "NY.GDP.PCAP.CD"),
            ("life", "SP.DYN.LE00.IN"),
        ):
            value = indicator_value(country, indicator_code)
            if value is not None:
                expected[key] = value

        row = rows_by_code.get(country.code, {})
        for key, expected_value in expected.items():
            sparql_values_checked += 1
            actual_value = row.get(key)
            if isinstance(expected_value, float):
                try:
                    matches = Decimal(str(actual_value)) == Decimal(str(expected_value))
                except Exception:
                    matches = False
            else:
                matches = actual_value == expected_value
            equivalent += int(matches)

    violations: list[str] = []
    codes = [country.code for country in graph.countries]
    if len(codes) != len(set(codes)):
        violations.append("Duplicate ISO3 country codes")
    for country in graph.countries:
        if not country.region_id or not country.region:
            violations.append(f"{country.code}: missing region")
        if not country.income_id or not country.income:
            violations.append(f"{country.code}: missing income level")
        population = indicator_value(country, "SP.POP.TOTL")
        gdp = indicator_value(country, "NY.GDP.PCAP.CD")
        life = indicator_value(country, "SP.DYN.LE00.IN")
        if population is not None and population < 0:
            violations.append(f"{country.code}: negative population")
        if gdp is not None and gdp < 0:
            violations.append(f"{country.code}: negative GDP per capita")
        if life is not None and not 0 <= life <= 120:
            violations.append(f"{country.code}: invalid life expectancy")

    total = len(graph.countries) or 1
    coverage = {
        "population": sum(indicator_value(country, "SP.POP.TOTL") is not None for country in graph.countries) / total,
        "gdp_per_capita": sum(
            indicator_value(country, "NY.GDP.PCAP.CD") is not None for country in graph.countries
        )
        / total,
        "life_expectancy": sum(
            indicator_value(country, "SP.DYN.LE00.IN") is not None for country in graph.countries
        )
        / total,
    }

    return ProjectEvaluation(
        country_count=len(graph.countries),
        rdf_triples=len(rdf_graph),
        facts_checked=checked,
        rdf_transformation_fidelity=correct / checked if checked else 1.0,
        sparql_equivalence=equivalent / sparql_values_checked if sparql_values_checked else 1.0,
        sparql_values_checked=sparql_values_checked,
        consistency_violations=violations,
        indicator_coverage=coverage,
        query_latency_ms=query_latency_ms,
    )


def build_ai_benchmark(graph: WorldBankKnowledgeGraph) -> list[BenchmarkCase]:
    if not graph.countries:
        return []
    target = graph.find_country("Pakistan") or graph.countries[0]
    population = indicator_value(target, "SP.POP.TOTL")
    gdp = indicator_value(target, "NY.GDP.PCAP.CD")
    life = indicator_value(target, "SP.DYN.LE00.IN")
    target_region = graph.countries_by_region("South Asia") or graph.countries_by_region(target.region_id)
    _, rule_similar = graph.similar_countries(target.code, limit=len(graph.countries))
    _, explainable = graph.explain_similarity(target.code, limit=3)
    high_population = graph.high_population(100_000_000, limit=len(graph.countries))
    above_health_outliers = [
        outlier.country.name
        for outlier in graph.infer_health_outliers(threshold_years=3.0)
        if outlier.direction == "above"
    ][:5]

    cases = [
        BenchmarkCase(
            id="capital_target",
            question=f"What is the capital city of {target.name}? Return one short text value.",
            answer_type="text",
            expected=target.capital,
        ),
        BenchmarkCase(
            id="region_target",
            question=f"Which World Bank region contains {target.name}? Return the official World Bank label.",
            answer_type="text",
            expected=target.region,
        ),
        BenchmarkCase(
            id="income_target",
            question=f"What is the World Bank income level of {target.name}? Return the official label.",
            answer_type="text",
            expected=target.income,
        ),
        BenchmarkCase(
            id="region_members",
            question=(
                f"List every country in the World Bank region '{target_region[0].region}'. "
                "Return a JSON list of country names with no explanation."
            ),
            answer_type="set",
            expected=[country.name for country in target_region],
        ),
        BenchmarkCase(
            id="rule_similar",
            question=(
                f"Using the rule 'same World Bank region and same income level', list every country similar to "
                f"{target.name}. Return a JSON list of country names with no explanation."
            ),
            answer_type="set",
            expected=[country.name for country in rule_similar],
            category="project_rule",
        ),
        BenchmarkCase(
            id="explainable_top_three",
            question=(
                "Using weights region=0.30, income=0.25, GDP-per-capita=0.20, life-expectancy=0.15, "
                f"population=0.10, list the top three countries most similar to {target.name}. "
                "Return a JSON list of country names with no explanation."
            ),
            answer_type="ranked",
            expected=[result.country.name for result in explainable],
            category="project_rule",
        ),
        BenchmarkCase(
            id="population_over_100m",
            question=(
                "List every represented country with population at least 100000000. "
                "Return a JSON list of country names with no explanation."
            ),
            answer_type="set",
            expected=[country.name for country in high_population],
        ),
        BenchmarkCase(
            id="health_outliers_above",
            question=(
                "For each income group, compute average life expectancy and select countries at least 3.0 years "
                "above their group average. Return the first five country names ranked by absolute difference."
            ),
            answer_type="ranked",
            expected=above_health_outliers,
            category="project_rule",
        ),
    ]
    if population is not None:
        cases.append(
            BenchmarkCase(
                id="population_target",
                question=f"What is the latest population value for {target.name}? Return only a number.",
                answer_type="number",
                expected=population,
                tolerance=0.01,
            )
        )
    if gdp is not None:
        cases.append(
            BenchmarkCase(
                id="gdp_target",
                question=f"What is the latest GDP per capita in current US dollars for {target.name}? Return only a number.",
                answer_type="number",
                expected=gdp,
                tolerance=0.05,
            )
        )
    if life is not None:
        cases.append(
            BenchmarkCase(
                id="life_expectancy_target",
                question=f"What is the latest life expectancy value for {target.name}? Return only a number.",
                answer_type="number",
                expected=life,
                tolerance=0.02,
            )
        )
    return cases


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, indent=2, ensure_ascii=True))


def _write_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_benchmark_metadata(
    graph: WorldBankKnowledgeGraph,
    cases: list[BenchmarkCase],
) -> dict[str, Any]:
    questions = [
        {
            "id": case.id,
            "question": case.question,
            "answer_type": case.answer_type,
            "category": case.category,
        }
        for case in cases
    ]
    ground_truth = [asdict(case) for case in cases]
    snapshot = [asdict(country) for country in sorted(graph.countries, key=lambda country: country.code)]
    question_hash = _sha256_json(questions)
    ground_truth_hash = _sha256_json(ground_truth)
    snapshot_hash = _sha256_json(snapshot)
    benchmark_id = _sha256_json(
        {
            "question_hash": question_hash,
            "ground_truth_hash": ground_truth_hash,
            "snapshot_hash": snapshot_hash,
        }
    )
    return {
        "schema_version": 2,
        "benchmark_id": benchmark_id,
        "question_hash": question_hash,
        "ground_truth_hash": ground_truth_hash,
        "snapshot_hash": snapshot_hash,
        "generated_date": date.today().isoformat(),
        "source": "World Bank Countries API and Indicators API",
        "protocol": "closed-book answer agreement",
    }


def _contains_recorded_answers(models: dict[str, dict[str, Any]]) -> bool:
    return any(answer is not None for answers in models.values() for answer in answers.values())


def _empty_answers(cases: list[BenchmarkCase]) -> dict[str, None]:
    return {case.id: None for case in cases}


def _ensure_model_roster(model_answers: dict[str, Any], cases: list[BenchmarkCase]) -> None:
    models = model_answers.setdefault("models", {})
    provenance = model_answers.setdefault("model_provenance", {})
    for model, details in DEFAULT_MODEL_PROVENANCE.items():
        models.setdefault(model, _empty_answers(cases))
        provenance.setdefault(model, dict(details))
    for answers in models.values():
        for case in cases:
            answers.setdefault(case.id, None)


def _validate_answer_provenance(model_answers: dict[str, Any], benchmark: dict[str, Any]) -> None:
    recorded = model_answers.get("benchmark", {})
    keys = ("benchmark_id", "question_hash", "snapshot_hash")
    if any(recorded.get(key) != benchmark.get(key) for key in keys):
        raise ValueError(
            "model_answers.json belongs to a different benchmark or data snapshot; "
            "archive it and collect new answers before scoring"
        )


def _evaluation_markdown(
    report: ProjectEvaluation,
    comparison: dict[str, ModelEvaluation],
    benchmark: dict[str, Any],
) -> str:
    lines = [
        "# Evaluation Summary",
        "",
        f"- Benchmark ID: `{benchmark['benchmark_id']}`",
        f"- Snapshot SHA-256: `{benchmark['snapshot_hash']}`",
        f"- Generated: {benchmark['generated_date']}",
        "",
        "## Knowledge-graph evaluation",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Countries represented | {report.country_count} |",
        f"| RDF triples | {report.rdf_triples} |",
        f"| RDF transformations checked | {report.facts_checked} |",
        f"| RDF transformation fidelity | {report.rdf_transformation_fidelity:.1%} |",
        f"| SPARQL/Python equivalence | {report.sparql_equivalence:.1%} |",
        f"| SPARQL/Python values checked | {report.sparql_values_checked} |",
        f"| Consistency violations | {len(report.consistency_violations)} |",
        f"| SPARQL query latency | {report.query_latency_ms:.2f} ms |",
        "",
        "## Indicator coverage",
        "",
        "| Indicator | Coverage |",
        "|---|---:|",
    ]
    lines.extend(f"| {name.replace('_', ' ').title()} | {value:.1%} |" for name, value in report.indicator_coverage.items())
    lines.extend(
        [
            "",
            "## Closed-book AI answer agreement",
            "",
        "| Model | Status | Answered | Pending | Overall | Retrieval | Project-rule |",
        "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for model in comparison.values():
        if model.collection_status == "Pending":
            lines.append(f"| {model.model} | Pending | 0 | {model.pending} | N/A | N/A | N/A |")
        else:
            lines.append(
                f"| {model.model} | {model.collection_status} | {model.answered} | {model.pending} | "
                f"{model.mean_score:.1%} | {model.category_scores.get('retrieval', 0.0):.1%} | "
                f"{model.category_scores.get('project_rule', 0.0):.1%} |"
            )
    has_unanswered_slots = any(model.pending for model in comparison.values())
    collection_note = (
        "This is a closed-book answer-agreement baseline, not a fair test of reasoning on project-rule cases, because models did not receive the frozen triples. Pending means no genuine answer has been recorded and is never scored as zero."
        if has_unanswered_slots
        else "This is a closed-book answer-agreement baseline, not a fair test of reasoning on project-rule cases, because models did not receive the frozen triples. All listed model rows contain recorded answers."
    )
    lines.extend(
        [
            "",
            collection_note,
            "",
        ]
    )
    return "\n".join(lines)


def write_evaluation_artifacts(graph: WorldBankKnowledgeGraph, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = evaluate_project(graph)
    cases = build_ai_benchmark(graph)
    benchmark = build_benchmark_metadata(graph, cases)

    questions_path = output_dir / "ai_benchmark_questions.json"
    ground_truth_path = output_dir / "ai_benchmark_ground_truth.json"
    model_answers_path = output_dir / "model_answers.json"
    project_results_path = output_dir / "project_evaluation.json"
    model_results_path = output_dir / "model_comparison.json"
    summary_path = output_dir / "evaluation_summary.md"

    if model_answers_path.exists():
        model_answers = json.loads(model_answers_path.read_text(encoding="utf-8"))
        if "benchmark" not in model_answers and not _contains_recorded_answers(model_answers.get("models", {})):
            model_answers["benchmark"] = benchmark
        _validate_answer_provenance(model_answers, benchmark)
    else:
        model_answers = {
            "benchmark": benchmark,
            "instructions": "Replace null with each model's genuine answer. Keep lists as JSON arrays and numbers numeric.",
            "models": {},
            "model_provenance": {},
        }

    _ensure_model_roster(model_answers, cases)

    _write_json(
        questions_path,
        {
            "benchmark": benchmark,
            "instructions": "Ask every model the same questions in a fresh closed-book chat and record only the requested answer format.",
            "limitation": "Project-rule cases measure answer agreement only; a fair reasoning experiment must provide every system the same frozen triples and complete rules.",
            "questions": [
                {
                    "id": case.id,
                    "question": case.question,
                    "answer_type": case.answer_type,
                    "category": case.category,
                }
                for case in cases
            ],
        },
    )
    _write_json(ground_truth_path, {"benchmark": benchmark, "cases": [asdict(case) for case in cases]})
    _write_json(model_answers_path, model_answers)
    comparison = compare_external_models(cases, model_answers.get("models", {}))
    _write_json(project_results_path, {"benchmark": benchmark, **asdict(report)})
    _write_json(
        model_results_path,
        {
            "benchmark": benchmark,
            "models": {model: asdict(result) for model, result in comparison.items()},
        },
    )
    _write_text(summary_path, _evaluation_markdown(report, comparison, benchmark))
    return {
        "questions": questions_path,
        "ground_truth": ground_truth_path,
        "model_answers": model_answers_path,
        "project_results": project_results_path,
        "model_results": model_results_path,
        "summary": summary_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the World Bank country knowledge graph.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "evaluation",
        help="Directory for benchmark questions, ground truth, model answers, and results.",
    )
    args = parser.parse_args()
    try:
        graph = WorldBankKnowledgeGraph(fetch_world_bank_data())
    except Exception as exc:
        print(f"Could not download World Bank data: {exc}")
        return 1
    paths = write_evaluation_artifacts(graph, args.output_dir)
    report = json.loads(paths["project_results"].read_text(encoding="utf-8"))
    print("WORLD BANK KNOWLEDGE GRAPH EVALUATION")
    print("=" * 44)
    print(f"Countries: {report['country_count']}")
    print(f"RDF triples: {report['rdf_triples']}")
    print(f"Facts checked: {report['facts_checked']}")
    print(f"RDF transformation fidelity: {report['rdf_transformation_fidelity']:.1%}")
    print(f"SPARQL/Python equivalence: {report['sparql_equivalence']:.1%}")
    print(f"SPARQL/Python values checked: {report['sparql_values_checked']}")
    print(f"Consistency violations: {len(report['consistency_violations'])}")
    print(f"Results: {paths['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
