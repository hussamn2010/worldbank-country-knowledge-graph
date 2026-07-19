from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1800
HEIGHT = 1200
BACKGROUND = "#F7F8FA"
TEXT = "#17212B"
MUTED = "#4B5A68"
ARROW = "#526273"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "seguisb.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / filename), size)


TITLE_FONT = load_font(44, bold=True)
BOX_TITLE_FONT = load_font(26, bold=True)
BOX_BODY_FONT = load_font(20)
LABEL_FONT = load_font(18, bold=True)


def draw_box(draw: ImageDraw.ImageDraw, bounds: tuple[int, int, int, int], title: str, body: str, color: str) -> None:
    x1, y1, x2, y2 = bounds
    draw.rounded_rectangle(bounds, radius=14, fill="white", outline=color, width=5)
    draw.rectangle((x1, y1, x2, y1 + 48), fill=color)
    draw.text((x1 + 18, y1 + 9), title, font=BOX_TITLE_FONT, fill="white")
    lines = body.split("\n")
    for index, line in enumerate(lines):
        draw.text((x1 + 20, y1 + 68 + index * 29), line, font=BOX_BODY_FONT, fill=TEXT)


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    label: str | None = None,
) -> None:
    draw.line((start, end), fill=ARROW, width=6)
    x2, y2 = end
    x1, y1 = start
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        head = [(x2, y2), (x2 - direction * 22, y2 - 13), (x2 - direction * 22, y2 + 13)]
    else:
        direction = 1 if y2 > y1 else -1
        head = [(x2, y2), (x2 - 13, y2 - direction * 22), (x2 + 13, y2 - direction * 22)]
    draw.polygon(head, fill=ARROW)
    if label:
        midpoint = ((x1 + x2) // 2, (y1 + y2) // 2)
        box = draw.textbbox((0, 0), label, font=LABEL_FONT)
        label_width = box[2] - box[0]
        label_height = box[3] - box[1]
        draw.rectangle(
            (
                midpoint[0] - label_width // 2 - 8,
                midpoint[1] - label_height // 2 - 5,
                midpoint[0] + label_width // 2 + 8,
                midpoint[1] + label_height // 2 + 5,
            ),
            fill=BACKGROUND,
        )
        draw.text(
            (midpoint[0] - label_width // 2, midpoint[1] - label_height // 2),
            label,
            font=LABEL_FONT,
            fill=MUTED,
        )


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((70, 35), "Explainable Country Development Knowledge Graph", font=TITLE_FONT, fill=TEXT)
    draw.text(
        (72, 92),
        "Acquisition, representation, reasoning, interaction, and reproducible evaluation",
        font=BOX_BODY_FONT,
        fill=MUTED,
    )

    world_bank = (70, 170, 440, 330)
    acquisition = (620, 170, 1030, 330)
    objects = (1210, 170, 1730, 330)
    rdf_graph = (585, 430, 1135, 610)
    sparql = (70, 730, 470, 910)
    rules = (560, 730, 960, 910)
    similarity = (1050, 730, 1450, 910)
    interface = (1480, 730, 1730, 910)
    evaluation = (560, 1010, 1240, 1160)

    draw_box(draw, world_bank, "World Bank APIs", "Country metadata\nPopulation, GDP, life expectancy", "#2563A6")
    draw_box(draw, acquisition, "Knowledge acquisition", "Download, filter aggregates\nValidate and normalize values", "#19705B")
    draw_box(draw, objects, "Country objects", "ISO codes, regions, income levels\nIndicators with value and year", "#8A5A16")
    draw_box(draw, rdf_graph, "Typed RDF knowledge graph", "Country / Region / IncomeLevel classes\nObject and datatype properties; Turtle export", "#53459A")
    draw_box(draw, sparql, "SPARQL query engine", "Real RDFLib queries\nNormalized result rows", "#2563A6")
    draw_box(draw, rules, "Symbolic rule engine", "Same-region + same-income rule\nTraceable health-outlier inference", "#A33C3C")
    draw_box(draw, similarity, "Explainable ranking", "Five explicit weighted factors\nScore contributions and reasons", "#8A5A16")
    draw_box(draw, interface, "CLI / IntelliJ", "Live menu\nDemo and tests", "#19705B")
    draw_box(draw, evaluation, "Evaluation harness", "Round-trip fact checks; multi-field SPARQL equivalence\nConsistency, coverage, and closed-book answer agreement", "#394B5A")

    draw_arrow(draw, (440, 250), (620, 250), "JSON")
    draw_arrow(draw, (1030, 250), (1210, 250), "normalized facts")
    draw_arrow(draw, (1470, 330), (1040, 430), "triples")
    draw_arrow(draw, (720, 610), (270, 730))
    draw_arrow(draw, (820, 610), (760, 730))
    draw_arrow(draw, (930, 610), (1250, 730))
    draw_arrow(draw, (1450, 820), (1480, 820))
    draw_arrow(draw, (270, 910), (680, 1010))
    draw_arrow(draw, (760, 910), (800, 1010))
    draw_arrow(draw, (1250, 910), (1110, 1010))

    output = Path(__file__).with_name("architecture_diagram.png")
    image.save(output, quality=95)
    print(output)


if __name__ == "__main__":
    main()
