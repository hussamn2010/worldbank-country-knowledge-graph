import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import evaluate_project

from tests.test_worldbank_country_kg import build_graph, make_country


class EvaluationModuleTests(unittest.TestCase):
    def test_evaluation_module_exists(self) -> None:
        self.assertIsNotNone(
            importlib.util.find_spec("evaluate_project"),
            "A separate, reproducible evaluation runner is required",
        )


class ExternalAnswerScoringTests(unittest.TestCase):
    def test_text_answer_scoring_is_case_and_punctuation_insensitive(self) -> None:
        self.assertTrue(hasattr(evaluate_project, "BenchmarkCase"))
        self.assertTrue(hasattr(evaluate_project, "score_external_answer"))
        case = evaluate_project.BenchmarkCase(
            id="capital_alpha",
            question="What is the capital of Alpha?",
            answer_type="text",
            expected="Alpha City",
        )

        score = evaluate_project.score_external_answer(case, "alpha city.")

        self.assertEqual(score.score, 1.0)
        self.assertTrue(score.correct)

    def test_set_answer_scoring_uses_precision_recall_and_f1(self) -> None:
        self.assertTrue(hasattr(evaluate_project, "BenchmarkCase"))
        self.assertTrue(hasattr(evaluate_project, "score_external_answer"))
        case = evaluate_project.BenchmarkCase(
            id="region_members",
            question="List the countries in Region One.",
            answer_type="set",
            expected=["Alpha", "Beta"],
        )

        score = evaluate_project.score_external_answer(case, ["Alpha", "Gamma"])

        self.assertAlmostEqual(score.precision, 0.5)
        self.assertAlmostEqual(score.recall, 0.5)
        self.assertAlmostEqual(score.score, 0.5)
        self.assertFalse(score.correct)

    def test_set_answer_scoring_parses_json_names_containing_commas(self) -> None:
        case = evaluate_project.BenchmarkCase(
            id="countries",
            question="Countries?",
            answer_type="set",
            expected=["Egypt, Arab Rep.", "Korea, Rep."],
        )

        score = evaluate_project.score_external_answer(
            case,
            '["Egypt, Arab Rep.", "Korea, Rep."]',
        )

        self.assertTrue(score.correct)
        self.assertEqual(score.score, 1.0)

    def test_ranked_answer_scoring_penalizes_reversed_order(self) -> None:
        case = evaluate_project.BenchmarkCase(
            id="ranking",
            question="Rank countries.",
            answer_type="ranked",
            expected=["Alpha", "Beta", "Gamma"],
        )

        exact = evaluate_project.score_external_answer(case, ["Alpha", "Beta", "Gamma"])
        reversed_order = evaluate_project.score_external_answer(case, ["Gamma", "Beta", "Alpha"])

        self.assertTrue(exact.correct)
        self.assertEqual(exact.score, 1.0)
        self.assertFalse(reversed_order.correct)
        self.assertLess(reversed_order.score, 1.0)

    def test_numeric_answer_scoring_applies_relative_tolerance(self) -> None:
        self.assertTrue(hasattr(evaluate_project, "BenchmarkCase"))
        self.assertTrue(hasattr(evaluate_project, "score_external_answer"))
        case = evaluate_project.BenchmarkCase(
            id="population_alpha",
            question="What is Alpha's population?",
            answer_type="number",
            expected=100.0,
            tolerance=0.10,
        )

        close = evaluate_project.score_external_answer(case, "105")
        wrong = evaluate_project.score_external_answer(case, 150)

        self.assertTrue(close.correct)
        self.assertAlmostEqual(close.score, 0.5)
        self.assertFalse(wrong.correct)
        self.assertEqual(wrong.score, 0.0)


class ProjectEvaluationTests(unittest.TestCase):
    def test_project_evaluation_checks_facts_queries_consistency_and_coverage(self) -> None:
        self.assertTrue(hasattr(evaluate_project, "evaluate_project"))

        report = evaluate_project.evaluate_project(build_graph())

        self.assertEqual(report.rdf_transformation_fidelity, 1.0)
        self.assertEqual(report.sparql_equivalence, 1.0)
        self.assertGreater(report.sparql_values_checked, len(build_graph().countries))
        self.assertEqual(report.consistency_violations, [])
        self.assertEqual(report.indicator_coverage["population"], 1.0)
        self.assertGreater(report.rdf_triples, 0)
        self.assertGreaterEqual(report.query_latency_ms, 0)

    def test_model_comparison_keeps_missing_answers_pending(self) -> None:
        self.assertTrue(hasattr(evaluate_project, "BenchmarkCase"))
        self.assertTrue(hasattr(evaluate_project, "compare_external_models"))
        cases = [
            evaluate_project.BenchmarkCase("capital", "Capital?", "text", "Alpha City"),
            evaluate_project.BenchmarkCase("members", "Members?", "set", ["Alpha", "Beta"]),
        ]
        answers = {
            "Model A": {"capital": "Alpha City", "members": ["Alpha", "Beta"]},
            "Model B": {"capital": "Wrong", "members": None},
        }

        comparison = evaluate_project.compare_external_models(cases, answers)

        self.assertEqual(comparison["Model A"].answered, 2)
        self.assertEqual(comparison["Model A"].mean_score, 1.0)
        self.assertEqual(comparison["Model B"].answered, 1)
        self.assertEqual(comparison["Model B"].pending, 1)
        self.assertEqual(comparison["Model B"].mean_score, 0.0)

    def test_evaluation_artifacts_separate_prompts_ground_truth_and_model_answers(self) -> None:
        self.assertTrue(hasattr(evaluate_project, "build_ai_benchmark"))
        self.assertTrue(hasattr(evaluate_project, "write_evaluation_artifacts"))
        graph = build_graph()
        graph.countries.extend(
            [
                make_country(
                    "PAK",
                    "Pakistan",
                    "MEA",
                    "Middle East, North Africa, Afghanistan & Pakistan",
                    "LMC",
                    "Lower middle income",
                    255_000_000,
                    1600,
                    67.8,
                ),
                make_country(
                    "BGD",
                    "Bangladesh",
                    "SAS",
                    "South Asia",
                    "LMC",
                    "Lower middle income",
                    175_000_000,
                    2600,
                    74.0,
                ),
            ]
        )
        graph = type(graph)(graph.countries)

        with tempfile.TemporaryDirectory() as directory:
            paths = evaluate_project.write_evaluation_artifacts(graph, Path(directory))
            questions = json.loads(paths["questions"].read_text(encoding="utf-8"))
            ground_truth = json.loads(paths["ground_truth"].read_text(encoding="utf-8"))
            model_answers = json.loads(paths["model_answers"].read_text(encoding="utf-8"))
            project_results = json.loads(paths["project_results"].read_text(encoding="utf-8"))
            model_results = json.loads(paths["model_results"].read_text(encoding="utf-8"))
            summary = paths["summary"].read_text(encoding="utf-8")

        self.assertGreaterEqual(len(questions["questions"]), 6)
        self.assertNotIn("expected", questions["questions"][0])
        self.assertIn("expected", ground_truth["cases"][0])
        expected_models = {
            "GPT-5.5 (older baseline)",
            "GPT-5.6 Sol",
            "GPT-5.6 Terra",
            "GPT-5.6 Luna",
            "Gemini Flash (web)",
            "Claude (web)",
            "DeepSeek (web)",
        }
        self.assertEqual(set(model_answers["models"]), expected_models)
        self.assertTrue(all(value is None for value in model_answers["models"]["GPT-5.5 (older baseline)"].values()))
        self.assertEqual(model_answers["model_provenance"]["DeepSeek (web)"]["provider_family"], "DeepSeek")
        self.assertEqual(model_answers["benchmark"]["benchmark_id"], questions["benchmark"]["benchmark_id"])
        self.assertEqual(model_answers["benchmark"]["snapshot_hash"], ground_truth["benchmark"]["snapshot_hash"])
        self.assertEqual(project_results["benchmark"]["benchmark_id"], questions["benchmark"]["benchmark_id"])
        self.assertEqual(model_results["benchmark"]["snapshot_hash"], questions["benchmark"]["snapshot_hash"])
        self.assertIn("SPARQL/Python values checked", summary)
        self.assertIn("| Gemini Flash (web) | Pending | 0 | 11 | N/A | N/A | N/A |", summary)

    def test_summary_omits_pending_note_when_all_models_are_recorded(self) -> None:
        report = evaluate_project.ProjectEvaluation(
            country_count=1,
            rdf_triples=10,
            facts_checked=5,
            rdf_transformation_fidelity=1.0,
            sparql_equivalence=1.0,
            sparql_values_checked=5,
            consistency_violations=[],
            indicator_coverage={"population": 1.0},
            query_latency_ms=1.25,
        )
        comparison = {
            "Model A": evaluate_project.ModelEvaluation(
                model="Model A",
                collection_status="Recorded",
                answered=1,
                pending=0,
                mean_score=1.0,
                case_scores={},
                category_scores={"retrieval": 1.0, "project_rule": 0.0},
            )
        }
        benchmark = {
            "benchmark_id": "bench",
            "snapshot_hash": "snapshot",
            "generated_date": "2026-07-19",
        }

        summary = evaluate_project._evaluation_markdown(report, comparison, benchmark)

        self.assertNotIn("Pending means", summary)
        self.assertIn("All listed model rows contain recorded answers.", summary)

    def test_evaluation_rejects_answers_from_a_different_snapshot(self) -> None:
        graph = build_graph()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            paths = evaluate_project.write_evaluation_artifacts(graph, output_dir)
            answers = json.loads(paths["model_answers"].read_text(encoding="utf-8"))
            answers["models"]["GPT-5.5 (older baseline)"]["capital_target"] = "Alpha City"
            answers["benchmark"]["snapshot_hash"] = "stale-snapshot"
            paths["model_answers"].write_text(json.dumps(answers), encoding="utf-8")
            paths["questions"].write_text("do not overwrite", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "different benchmark or data snapshot"):
                evaluate_project.write_evaluation_artifacts(graph, output_dir)

            self.assertEqual(paths["questions"].read_text(encoding="utf-8"), "do not overwrite")


if __name__ == "__main__":
    unittest.main()
