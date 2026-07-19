from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF


BASE_URL = "https://api.worldbank.org/v2"
COUNTRY_API_DOC = "https://datahelpdesk.worldbank.org/knowledgebase/articles/898590-country-api-queries"
INDICATOR_API_DOC = "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation"

INDICATORS = {
    "SP.POP.TOTL": {
        "predicate": "wbkg:populationTotal",
        "year_predicate": "wbkg:populationTotalYear",
        "label": "Population, total",
    },
    "NY.GDP.PCAP.CD": {
        "predicate": "wbkg:gdpPerCapitaCurrentUsd",
        "year_predicate": "wbkg:gdpPerCapitaCurrentUsdYear",
        "label": "GDP per capita (current US$)",
    },
    "SP.DYN.LE00.IN": {
        "predicate": "wbkg:lifeExpectancyYears",
        "year_predicate": "wbkg:lifeExpectancyYearsYear",
        "label": "Life expectancy at birth, total (years)",
    },
}

WBKG = Namespace("https://example.org/worldbank-country-kg/")
COUNTRY = Namespace("https://example.org/worldbank-country-kg/country/")
REGION = Namespace("https://example.org/worldbank-country-kg/region/")
INCOME = Namespace("https://example.org/worldbank-country-kg/income/")


@dataclass
class Country:
    code: str
    iso2: str
    name: str
    region_id: str
    region: str
    income_id: str
    income: str
    lending_type: str
    capital: str
    longitude: str
    latitude: str
    indicators: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SimilarityResult:
    country: Country
    score: float
    similarity_on_available: float
    coverage: float
    contributions: dict[str, float | None]
    available_factors: tuple[str, ...]
    missing_factors: tuple[str, ...]
    reasons: tuple[str, ...]
    explanation: str


@dataclass
class HealthOutlier:
    country: Country
    direction: str
    income_average: float
    difference_years: float
    explanation: str


class WorldBankKnowledgeGraph:
    def __init__(self, countries: list[Country]) -> None:
        self.countries = countries
        self.by_code = {country.code.upper(): country for country in countries}
        self.by_name = {country.name.lower(): country for country in countries}
        self.triples: list[tuple[str, str, Any, bool]] = []
        self._build_triples()

    def _add(self, subject: str, predicate: str, obj: Any, literal: bool = False) -> None:
        if obj is None or obj == "":
            return
        self.triples.append((subject, predicate, obj, literal))

    def _build_triples(self) -> None:
        seen_regions: set[str] = set()
        seen_income_levels: set[str] = set()

        for country in self.countries:
            country_node = f"country:{country.code}"
            region_node = f"region:{safe_curie(country.region_id)}"
            income_node = f"income:{safe_curie(country.income_id)}"

            self._add(country_node, "wbkg:name", country.name, literal=True)
            self._add(country_node, "wbkg:iso2Code", country.iso2, literal=True)
            self._add(country_node, "wbkg:hasRegion", region_node)
            self._add(country_node, "wbkg:hasIncomeLevel", income_node)
            self._add(country_node, "wbkg:hasLendingType", country.lending_type, literal=True)
            self._add(country_node, "wbkg:hasCapital", country.capital, literal=True)
            self._add(country_node, "wbkg:longitude", country.longitude, literal=True)
            self._add(country_node, "wbkg:latitude", country.latitude, literal=True)

            if region_node not in seen_regions:
                self._add(region_node, "wbkg:label", country.region, literal=True)
                seen_regions.add(region_node)

            if income_node not in seen_income_levels:
                self._add(income_node, "wbkg:label", country.income, literal=True)
                seen_income_levels.add(income_node)

            for indicator_code, value_info in country.indicators.items():
                indicator = INDICATORS[indicator_code]
                self._add(country_node, indicator["predicate"], value_info["value"], literal=True)
                self._add(country_node, indicator["year_predicate"], int(value_info["year"]), literal=True)

    def find_country(self, query: str) -> Country | None:
        normalized = query.strip().lower()
        if not normalized:
            return None
        by_code = self.by_code.get(normalized.upper())
        if by_code:
            return by_code
        by_name = self.by_name.get(normalized)
        if by_name:
            return by_name
        matches = [country for country in self.countries if normalized in country.name.lower()]
        return matches[0] if matches else None

    def countries_by_region(self, region_query: str) -> list[Country]:
        normalized = region_query.strip().lower()
        return sorted(
            [
                country
                for country in self.countries
                if normalized in country.region.lower() or normalized == country.region_id.lower()
            ],
            key=lambda country: country.name,
        )

    def countries_by_income(self, income_query: str) -> list[Country]:
        normalized = income_query.strip().lower()
        return sorted(
            [
                country
                for country in self.countries
                if normalized in country.income.lower() or normalized == country.income_id.lower()
            ],
            key=lambda country: country.name,
        )

    def similar_countries(self, query: str, limit: int = 10) -> tuple[Country | None, list[Country]]:
        base = self.find_country(query)
        if not base:
            return None, []

        candidates = [
            country
            for country in self.countries
            if country.code != base.code
            and country.region_id == base.region_id
            and country.income_id == base.income_id
        ]

        base_gdp = indicator_value(base, "NY.GDP.PCAP.CD")

        def sort_key(country: Country) -> tuple[float, str]:
            country_gdp = indicator_value(country, "NY.GDP.PCAP.CD")
            if base_gdp is None or country_gdp is None:
                return (float("inf"), country.name)
            return (abs(base_gdp - country_gdp), country.name)

        return base, sorted(candidates, key=sort_key)[:limit]

    def high_population(self, minimum: int, limit: int = 15) -> list[Country]:
        countries = [
            country
            for country in self.countries
            if (indicator_value(country, "SP.POP.TOTL") or 0) >= minimum
        ]
        return sorted(countries, key=lambda country: indicator_value(country, "SP.POP.TOTL") or 0, reverse=True)[:limit]

    def explain_similarity(self, query: str, limit: int = 10) -> tuple[Country | None, list[SimilarityResult]]:
        base = self.find_country(query)
        if not base:
            return None, []

        results: list[SimilarityResult] = []
        for country in self.countries:
            if country.code == base.code:
                continue

            weights = {
                "region": 0.30,
                "income": 0.25,
                "gdp_per_capita": 0.20,
                "life_expectancy": 0.15,
                "population": 0.10,
            }
            base_values = {
                "gdp_per_capita": indicator_value(base, "NY.GDP.PCAP.CD"),
                "life_expectancy": indicator_value(base, "SP.DYN.LE00.IN"),
                "population": indicator_value(base, "SP.POP.TOTL"),
            }
            country_values = {
                "gdp_per_capita": indicator_value(country, "NY.GDP.PCAP.CD"),
                "life_expectancy": indicator_value(country, "SP.DYN.LE00.IN"),
                "population": indicator_value(country, "SP.POP.TOTL"),
            }
            factors: dict[str, float | None] = {
                "region": 1.0 if country.region_id == base.region_id else 0.0,
                "income": 1.0 if country.income_id == base.income_id else 0.0,
            }
            for name in ("gdp_per_capita", "life_expectancy", "population"):
                left = base_values[name]
                right = country_values[name]
                factors[name] = relative_closeness(left, right) if left is not None and right is not None else None

            available_weight = sum(weights[name] for name, factor in factors.items() if factor is not None)
            contributions: dict[str, float | None] = {
                name: (weights[name] * factor if factor is not None else None)
                for name, factor in factors.items()
            }
            reasons: list[str] = []
            if contributions["region"]:
                reasons.append("Same World Bank region")
            if contributions["income"]:
                reasons.append("Same World Bank income level")
            if factors["gdp_per_capita"] is not None and factors["gdp_per_capita"] >= 0.75:
                reasons.append("Similar GDP per capita")
            if factors["life_expectancy"] is not None and factors["life_expectancy"] >= 0.80:
                reasons.append("Similar life expectancy")
            if factors["population"] is not None and factors["population"] >= 0.80:
                reasons.append("Similar population scale")

            weighted_similarity = sum(value for value in contributions.values() if value is not None)
            similarity_on_available = weighted_similarity / available_weight if available_weight else 0.0
            coverage = available_weight
            score = weighted_similarity
            available_factors = tuple(name for name, factor in factors.items() if factor is not None)
            missing_factors = tuple(name for name, factor in factors.items() if factor is None)
            explanation = (
                f"{country.name} scored {score:.3f}: "
                + (", ".join(reasons) if reasons else "only weak numeric similarities")
                + f"; {coverage:.0%} evidence coverage"
                + (f"; missing {', '.join(missing_factors)}." if missing_factors else ".")
            )
            results.append(
                SimilarityResult(
                    country=country,
                    score=score,
                    similarity_on_available=similarity_on_available,
                    coverage=coverage,
                    contributions=contributions,
                    available_factors=available_factors,
                    missing_factors=missing_factors,
                    reasons=tuple(reasons),
                    explanation=explanation,
                )
            )

        return base, sorted(results, key=lambda result: (-result.score, result.country.name))[:limit]

    def infer_health_outliers(self, threshold_years: float = 3.0) -> list[HealthOutlier]:
        by_income: dict[str, list[Country]] = {}
        for country in self.countries:
            if indicator_value(country, "SP.DYN.LE00.IN") is not None:
                by_income.setdefault(country.income_id, []).append(country)

        outliers: list[HealthOutlier] = []
        for group in by_income.values():
            average = sum(indicator_value(country, "SP.DYN.LE00.IN") or 0 for country in group) / len(group)
            for country in group:
                value = indicator_value(country, "SP.DYN.LE00.IN")
                if value is None:
                    continue
                difference = value - average
                if abs(difference) < threshold_years:
                    continue
                direction = "above" if difference > 0 else "below"
                explanation = (
                    f"{country.name} is {abs(difference):.1f} years {direction} the "
                    f"{country.income} average of {average:.1f} years."
                )
                outliers.append(
                    HealthOutlier(
                        country=country,
                        direction=direction,
                        income_average=average,
                        difference_years=difference,
                        explanation=explanation,
                    )
                )

        return sorted(outliers, key=lambda outlier: (-abs(outlier.difference_years), outlier.country.name))

    def to_rdflib_graph(self) -> Graph:
        graph = Graph()
        graph.bind("wbkg", WBKG)
        graph.bind("country", COUNTRY)
        graph.bind("region", REGION)
        graph.bind("income", INCOME)

        for country in self.countries:
            graph.add((COUNTRY[country.code], RDF.type, WBKG.Country))
        for region_id in {country.region_id for country in self.countries}:
            graph.add((REGION[safe_curie(region_id)], RDF.type, WBKG.Region))
        for income_id in {country.income_id for country in self.countries}:
            graph.add((INCOME[safe_curie(income_id)], RDF.type, WBKG.IncomeLevel))

        for subject, predicate, obj, literal in self.triples:
            subject_uri = curie_to_uri(subject)
            predicate_uri = curie_to_uri(predicate)
            if literal and isinstance(obj, float):
                object_value = Literal(Decimal(str(obj)))
            else:
                object_value = Literal(obj) if literal else curie_to_uri(str(obj))
            graph.add((subject_uri, predicate_uri, object_value))
        return graph

    def execute_sparql(self, query: str) -> list[dict[str, Any]]:
        result = self.to_rdflib_graph().query(query)
        rows: list[dict[str, Any]] = []
        for row in result:
            normalized: dict[str, Any] = {}
            for variable, value in zip(result.vars, row):
                if isinstance(value, Literal):
                    normalized[str(variable)] = value.toPython()
                elif value is not None:
                    normalized[str(variable)] = str(value)
            rows.append(normalized)
        return rows

    def to_turtle(self) -> str:
        return self.to_rdflib_graph().serialize(format="turtle")


def safe_curie(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned or "unknown"


def curie_to_uri(value: str) -> URIRef:
    prefix, local = value.split(":", 1)
    namespaces = {
        "wbkg": WBKG,
        "country": COUNTRY,
        "region": REGION,
        "income": INCOME,
    }
    if prefix not in namespaces:
        raise ValueError(f"Unknown CURIE prefix: {prefix}")
    return namespaces[prefix][local]


def relative_closeness(left: float | None, right: float | None) -> float:
    if left is None or right is None:
        return 0.0
    denominator = max(abs(left), abs(right), 1.0)
    return max(0.0, 1.0 - abs(left - right) / denominator)


def format_turtle_object(value: Any, literal: bool) -> str:
    if literal and isinstance(value, (int, float)):
        return str(value)
    if literal:
        return json.dumps(str(value), ensure_ascii=True)
    return str(value)


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "worldbank-country-kg-course-project/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_world_bank_data() -> list[Country]:
    countries_url = f"{BASE_URL}/country?format=json&per_page=400"
    country_response = fetch_json(countries_url)
    raw_countries = country_response[1]

    indicator_values: dict[str, dict[str, dict[str, Any]]] = {}
    for indicator_code in INDICATORS:
        url = f"{BASE_URL}/country/all/indicator/{indicator_code}?format=json&per_page=20000&mrv=1"
        response = fetch_json(url)
        rows = response[1] or []
        indicator_values[indicator_code] = {
            row["countryiso3code"]: {"value": row["value"], "year": row["date"]}
            for row in rows
            if row.get("countryiso3code") and row.get("value") is not None
        }

    countries: list[Country] = []
    for row in raw_countries:
        region = row.get("region", {})
        income = row.get("incomeLevel", {})

        # The World Bank country endpoint includes aggregate regions such as World.
        if region.get("value") == "Aggregates" or region.get("id") in {"NA", ""}:
            continue

        country = Country(
            code=row["id"],
            iso2=row.get("iso2Code", ""),
            name=row.get("name", ""),
            region_id=region.get("id", ""),
            region=region.get("value", "").strip(),
            income_id=income.get("id", ""),
            income=income.get("value", "").strip(),
            lending_type=row.get("lendingType", {}).get("value", "").strip(),
            capital=row.get("capitalCity", "").strip(),
            longitude=row.get("longitude", "").strip(),
            latitude=row.get("latitude", "").strip(),
        )

        for indicator_code, values_by_country in indicator_values.items():
            if country.code in values_by_country:
                country.indicators[indicator_code] = values_by_country[country.code]

        countries.append(country)

    return countries


def indicator_value(country: Country, indicator_code: str) -> float | None:
    value_info = country.indicators.get(indicator_code)
    if not value_info:
        return None
    try:
        return float(value_info["value"])
    except (TypeError, ValueError):
        return None


def indicator_year(country: Country, indicator_code: str) -> str:
    value_info = country.indicators.get(indicator_code)
    return str(value_info["year"]) if value_info else "n/a"


def format_country_facts(country: Country) -> list[str]:
    population = indicator_value(country, "SP.POP.TOTL")
    gdp = indicator_value(country, "NY.GDP.PCAP.CD")
    life = indicator_value(country, "SP.DYN.LE00.IN")
    return [
        f"{country.name} ({country.code})",
        f"  Region: {country.region}",
        f"  Income level: {country.income}",
        f"  Capital: {country.capital or 'n/a'}",
        f"  Population ({indicator_year(country, 'SP.POP.TOTL')}): {population:,.0f}" if population is not None else "  Population: n/a",
        f"  GDP per capita ({indicator_year(country, 'NY.GDP.PCAP.CD')}): ${gdp:,.2f}" if gdp is not None else "  GDP per capita: n/a",
        f"  Life expectancy ({indicator_year(country, 'SP.DYN.LE00.IN')}): {life:.1f} years" if life is not None else "  Life expectancy: n/a",
    ]


def format_country_row(country: Country) -> str:
    population = indicator_value(country, "SP.POP.TOTL")
    gdp = indicator_value(country, "NY.GDP.PCAP.CD")
    population_text = f"{population:,.0f}" if population is not None else "n/a"
    gdp_text = f"${gdp:,.0f}" if gdp is not None else "n/a"
    return f"{country.name} ({country.code}) | {country.region} | {country.income} | pop. {population_text} | GDP/capita {gdp_text}"


def generate_demo(graph: WorldBankKnowledgeGraph) -> str:
    lines: list[str] = []
    lines.append("WORLD BANK COUNTRY DEVELOPMENT KNOWLEDGE GRAPH")
    lines.append("=" * 56)
    lines.append(f"Countries represented: {len(graph.countries)}")
    lines.append(f"Real RDF triples generated: {len(graph.to_rdflib_graph())}")
    lines.append(f"Source 1: {COUNTRY_API_DOC}")
    lines.append(f"Source 2: {INDICATOR_API_DOC}")
    lines.append("")

    target = graph.find_country("Pakistan") or (graph.countries[0] if graph.countries else None)
    target_name = target.name if target else "target country"
    lines.append(f"Query 1: Show facts about {target_name}")
    lines.append("-" * 56)
    lines.extend(format_country_facts(target) if target else ["No countries available"])
    lines.append("")

    region_query = "South Asia" if graph.countries_by_region("South Asia") else (target.region if target else "")
    lines.append(f"Query 2: Countries in {region_query}")
    lines.append("-" * 56)
    for country in graph.countries_by_region(region_query):
        lines.append(format_country_row(country))
    lines.append("")

    lines.append(f"Query 3: Rule-similar countries to {target_name}")
    lines.append("-" * 56)
    base, similar = graph.similar_countries(target.code if target else "", limit=8)
    if base:
        lines.append(f"Rule: same World Bank region and same income level as {base.name}.")
        for country in similar:
            lines.append(format_country_row(country))
    else:
        lines.append("Target country not found")
    lines.append("")

    lines.append("Query 4: Countries with population above 100 million")
    lines.append("-" * 56)
    for country in graph.high_population(100_000_000, limit=12):
        lines.append(format_country_row(country))
    lines.append("")

    lines.append("Query 5: Real SPARQL query")
    lines.append("-" * 56)
    if target:
        sparql = f"""PREFIX wbkg: <https://example.org/worldbank-country-kg/>
PREFIX country: <https://example.org/worldbank-country-kg/country/>
SELECT ?capital ?region WHERE {{
  country:{target.code} wbkg:hasCapital ?capital ; wbkg:hasRegion ?region .
}}"""
        lines.extend(sparql.splitlines())
        lines.append(f"Result: {graph.execute_sparql(sparql)}")
    else:
        lines.append("No countries available")
    lines.append("")

    lines.append(f"Query 6: Explainable multi-factor similarity to {target_name}")
    lines.append("-" * 56)
    explanation_base, ranked = graph.explain_similarity(target.code if target else "", limit=5)
    if explanation_base:
        lines.append("Score weights: region .30, income .25, GDP .20, life expectancy .15, population .10")
        for result in ranked:
            contributions = ", ".join(
                f"{name}={'N/A' if value is None else f'{value:.3f}'}"
                for name, value in result.contributions.items()
            )
            lines.append(
                f"{result.country.name}: {result.score:.3f} | coverage {result.coverage:.0%} | "
                f"{contributions} | {', '.join(result.reasons)}"
            )
    else:
        lines.append("Target country not found")
    lines.append("")

    lines.append("Query 7: Health-outlier inference")
    lines.append("-" * 56)
    lines.append("Rule: life expectancy differs by at least 3.0 years from the country's income-group average.")
    for outlier in graph.infer_health_outliers(threshold_years=3.0)[:5]:
        lines.append(outlier.explanation)
    lines.append("")

    lines.append("Original symbolic inference rule")
    lines.append("-" * 56)
    lines.append("similar_country(X, Y) is true when X and Y share the same World Bank region")
    lines.append("and the same World Bank income level, and X is not Y.")
    return "\n".join(lines) + "\n"


def write_outputs(graph: WorldBankKnowledgeGraph, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    countries_json = [asdict(country) for country in graph.countries]
    (output_dir / "worldbank_countries.json").write_text(json.dumps(countries_json, indent=2), encoding="utf-8")
    (output_dir / "worldbank_country_graph.ttl").write_text(graph.to_turtle(), encoding="utf-8")
    (output_dir / "sample_queries.txt").write_text(generate_demo(graph), encoding="utf-8")


def interactive_menu(graph: WorldBankKnowledgeGraph) -> None:
    print("World Bank Country Development Knowledge Graph")
    print("Type a number, or q to quit.")
    while True:
        print("\n1. Show country facts")
        print("2. Search countries by region")
        print("3. Search countries by income level")
        print("4. Find rule-similar countries")
        print("5. Show high-population countries")
        print("6. Explain multi-factor similarity")
        print("7. Infer life-expectancy outliers")
        print("8. Run a SPARQL country-facts query")
        choice = input("> ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return
        if choice == "1":
            query = input("Country name or ISO3 code: ")
            country = graph.find_country(query)
            print("\n".join(format_country_facts(country)) if country else "Country not found.")
        elif choice == "2":
            query = input("Region name or World Bank region code: ")
            for country in graph.countries_by_region(query):
                print(format_country_row(country))
        elif choice == "3":
            query = input("Income level or World Bank income code: ")
            for country in graph.countries_by_income(query):
                print(format_country_row(country))
        elif choice == "4":
            query = input("Country name or ISO3 code: ")
            base, similar = graph.similar_countries(query)
            if not base:
                print("Country not found.")
            else:
                print(f"Similar to {base.name}:")
                for country in similar:
                    print(format_country_row(country))
        elif choice == "5":
            query = input("Minimum population, e.g. 100000000: ")
            try:
                minimum = int(query)
            except ValueError:
                print("Please enter a whole number.")
                continue
            for country in graph.high_population(minimum):
                print(format_country_row(country))
        elif choice == "6":
            query = input("Country name or ISO3 code: ")
            base, results = graph.explain_similarity(query)
            if not base:
                print("Country not found.")
            else:
                print(f"Explainable similarity to {base.name}:")
                for result in results:
                    contributions = ", ".join(
                        f"{name}={'N/A' if value is None else f'{value:.3f}'}"
                        for name, value in result.contributions.items()
                    )
                    print(
                        f"{result.country.name}: {result.score:.3f} | coverage {result.coverage:.0%} | "
                        f"{contributions} | {', '.join(result.reasons)}"
                    )
        elif choice == "7":
            query = input("Minimum difference from income-group average in years, e.g. 3: ")
            try:
                threshold = float(query)
            except ValueError:
                print("Please enter a number.")
                continue
            for outlier in graph.infer_health_outliers(threshold):
                print(outlier.explanation)
        elif choice == "8":
            query = input("Country name or ISO3 code: ")
            country = graph.find_country(query)
            if not country:
                print("Country not found.")
                continue
            sparql = f"""PREFIX wbkg: <https://example.org/worldbank-country-kg/>
PREFIX country: <https://example.org/worldbank-country-kg/country/>
SELECT ?name ?capital ?region ?income WHERE {{
  country:{country.code} wbkg:name ?name ;
                         wbkg:hasCapital ?capital ;
                         wbkg:hasRegion ?region ;
                         wbkg:hasIncomeLevel ?income .
}}"""
            print(sparql)
            print(graph.execute_sparql(sparql))
        else:
            print("Unknown choice.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and query a World Bank country-development knowledge graph.")
    parser.add_argument("--demo", action="store_true", help="Print sample query outputs.")
    parser.add_argument("--write-outputs", action="store_true", help="Write JSON, Turtle, and sample query files.")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent), help="Directory for generated files.")
    args = parser.parse_args()

    try:
        countries = fetch_world_bank_data()
    except Exception as exc:
        print(f"Could not download World Bank data: {exc}", file=sys.stderr)
        return 1

    graph = WorldBankKnowledgeGraph(countries)

    if args.write_outputs:
        write_outputs(graph, Path(args.output_dir))

    if args.demo:
        print(generate_demo(graph))
    elif not args.write_outputs:
        interactive_menu(graph)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
