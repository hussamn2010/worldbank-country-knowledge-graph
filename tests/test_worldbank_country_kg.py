import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF

from worldbank_country_kg import Country, WorldBankKnowledgeGraph, generate_demo, write_outputs


WBKG = Namespace("https://example.org/worldbank-country-kg/")
COUNTRY = Namespace("https://example.org/worldbank-country-kg/country/")


def make_country(
    code: str,
    name: str,
    region_id: str,
    region: str,
    income_id: str,
    income: str,
    population: float,
    gdp_per_capita: float,
    life_expectancy: float,
) -> Country:
    return Country(
        code=code,
        iso2=code[:2],
        name=name,
        region_id=region_id,
        region=region,
        income_id=income_id,
        income=income,
        lending_type="Test lending",
        capital=f"{name} City",
        longitude="1.0",
        latitude="2.0",
        indicators={
            "SP.POP.TOTL": {"value": population, "year": "2025"},
            "NY.GDP.PCAP.CD": {"value": gdp_per_capita, "year": "2025"},
            "SP.DYN.LE00.IN": {"value": life_expectancy, "year": "2024"},
        },
    )


def build_graph() -> WorldBankKnowledgeGraph:
    return WorldBankKnowledgeGraph(
        [
            make_country("AAA", "Alpha", "R1", "Region One", "I1", "Income One", 100, 1000, 70),
            make_country("BBB", "Beta", "R1", "Region One", "I1", "Income One", 110, 1050, 80),
            make_country("DDD", "Delta", "R1", "Region One", "I1", "Income One", 95, 980, 72),
            make_country("CCC", "Gamma", "R2", "Region Two", "I2", "Income Two", 100, 1000, 70),
        ]
    )


class RealRdfTests(unittest.TestCase):
    def test_rdflib_graph_contains_typed_country_and_literal_fact(self) -> None:
        graph = build_graph()

        self.assertTrue(hasattr(graph, "to_rdflib_graph"), "The graph needs a real RDFLib export")
        rdf_graph = graph.to_rdflib_graph()

        self.assertIn((COUNTRY.AAA, RDF.type, WBKG.Country), rdf_graph)
        self.assertIn((COUNTRY.AAA, WBKG.hasCapital, Literal("Alpha City")), rdf_graph)

    def test_execute_sparql_returns_normalized_rows(self) -> None:
        graph = build_graph()

        self.assertTrue(hasattr(graph, "execute_sparql"), "The graph needs real SPARQL querying")
        rows = graph.execute_sparql(
            """
            PREFIX wbkg: <https://example.org/worldbank-country-kg/>
            SELECT ?name WHERE {
                ?country wbkg:hasCapital "Alpha City" ;
                         wbkg:name ?name .
            }
            """
        )

        self.assertEqual(rows, [{"name": "Alpha"}])

    def test_saved_turtle_preserves_source_numeric_precision(self) -> None:
        country = make_country(
            "AAA",
            "Alpha",
            "R1",
            "Region One",
            "I1",
            "Income One",
            123456.0,
            3129.47662331063,
            72.123456789,
        )
        graph = WorldBankKnowledgeGraph([country])

        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            write_outputs(graph, output_dir)
            parsed = Graph().parse(output_dir / "worldbank_country_graph.ttl", format="turtle")

        gdp = next(parsed.objects(COUNTRY.AAA, WBKG.gdpPerCapitaCurrentUsd)).toPython()
        life = next(parsed.objects(COUNTRY.AAA, WBKG.lifeExpectancyYears)).toPython()
        self.assertEqual(Decimal(str(gdp)), Decimal("3129.47662331063"))
        self.assertEqual(Decimal(str(life)), Decimal("72.123456789"))


class ExplainableReasoningTests(unittest.TestCase):
    def test_similarity_ranking_exposes_score_and_reasons(self) -> None:
        graph = build_graph()

        self.assertTrue(hasattr(graph, "explain_similarity"), "Explainable similarity is not implemented")
        base, results = graph.explain_similarity("Alpha", limit=3)

        self.assertEqual(base.code, "AAA")
        self.assertEqual(results[0].country.code, "DDD")
        self.assertGreater(results[0].score, 0.9)
        self.assertIn("Same World Bank region", results[0].reasons)
        self.assertIn("Same World Bank income level", results[0].reasons)
        self.assertGreater(results[0].contributions["gdp_per_capita"], 0)

    def test_similarity_reports_coverage_when_an_indicator_is_missing(self) -> None:
        base = make_country("AAA", "Alpha", "R1", "Region One", "I1", "Income One", 100, 1000, 70)
        candidate = make_country("BBB", "Beta", "R1", "Region One", "I1", "Income One", 100, 1000, 70)
        del candidate.indicators["NY.GDP.PCAP.CD"]
        graph = WorldBankKnowledgeGraph([base, candidate])

        _, results = graph.explain_similarity("Alpha", limit=1)

        self.assertAlmostEqual(results[0].similarity_on_available, 1.0)
        self.assertAlmostEqual(results[0].coverage, 0.8)
        self.assertAlmostEqual(results[0].score, 0.8)
        self.assertAlmostEqual(
            sum(value for value in results[0].contributions.values() if value is not None),
            results[0].score,
        )
        self.assertIsNone(results[0].contributions["gdp_per_capita"])
        self.assertEqual(results[0].missing_factors, ("gdp_per_capita",))
        self.assertIn("80% evidence coverage", results[0].explanation)

    def test_saved_country_snapshot_contains_all_hashable_source_fields(self) -> None:
        graph = build_graph()
        with self.subTest("full country dataclass is serialized"):
            import json
            import tempfile
            from dataclasses import asdict
            from pathlib import Path

            with tempfile.TemporaryDirectory() as directory:
                output_dir = Path(directory)
                write_outputs(graph, output_dir)
                saved = json.loads((output_dir / "worldbank_countries.json").read_text(encoding="utf-8"))

            self.assertEqual(saved, [asdict(country) for country in graph.countries])

    def test_health_outlier_rule_returns_traceable_inferences(self) -> None:
        graph = build_graph()

        self.assertTrue(hasattr(graph, "infer_health_outliers"), "Health-outlier inference is not implemented")
        outliers = graph.infer_health_outliers(threshold_years=3.0)
        by_code = {outlier.country.code: outlier for outlier in outliers}

        self.assertEqual(by_code["BBB"].direction, "above")
        self.assertAlmostEqual(by_code["BBB"].income_average, 74.0)
        self.assertAlmostEqual(by_code["BBB"].difference_years, 6.0)
        self.assertIn("Income One", by_code["BBB"].explanation)
        self.assertEqual(by_code["AAA"].direction, "below")


class DemonstrationTests(unittest.TestCase):
    def test_demo_exposes_real_rdf_sparql_and_explainable_inference(self) -> None:
        output = generate_demo(build_graph())

        self.assertIn("Real RDF triples generated", output)
        self.assertIn("SPARQL query", output)
        self.assertIn("Explainable multi-factor similarity", output)
        self.assertIn("Health-outlier inference", output)

    def test_demo_shows_missing_similarity_factors_as_not_available(self) -> None:
        base = make_country("AAA", "Alpha", "R1", "Region One", "I1", "Income One", 100, 1000, 70)
        candidate = make_country("BBB", "Beta", "R1", "Region One", "I1", "Income One", 100, 1000, 70)
        del candidate.indicators["NY.GDP.PCAP.CD"]

        output = generate_demo(WorldBankKnowledgeGraph([base, candidate]))

        self.assertIn("gdp_per_capita=N/A", output)


if __name__ == "__main__":
    unittest.main()
