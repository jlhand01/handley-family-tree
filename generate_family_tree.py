"""Generate a static family tree website from a GEDCOM file.

The script parses the handley.ged GEDCOM file and produces a simple
static website that focuses on the descendants of David Handley and
Verna Mae Rucker Handley.  The root page shows the couple along with
their children, while each descendant gets their own page with links to
further generations.

Usage
-----
    python generate_family_tree.py handley.ged site

You may optionally specify alternative base individuals with
``--base-husband`` and ``--base-wife``.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set
from xml.etree import ElementTree as ET


@dataclass
class Event:
    """Simple representation of a dated/place event (birth, death, marriage)."""

    date: Optional[str] = None
    place: Optional[str] = None

    def description(self) -> Optional[str]:
        parts: List[str] = []
        if self.date:
            parts.append(self.date)
        if self.place:
            parts.append(self.place)
        if not parts:
            return None
        return ", ".join(parts)


@dataclass
class Individual:
    """Representation of an individual found in the GEDCOM file."""

    id: str
    name: str = ""
    given_name: str = ""
    surname: str = ""
    sex: str = ""
    famc: Optional[str] = None
    fams: List[str] = field(default_factory=list)
    birth: Event = field(default_factory=Event)
    death: Event = field(default_factory=Event)

    @property
    def display_name(self) -> str:
        if self.name:
            # GEDCOM names wrap the surname in slashes.
            cleaned = self.name.replace("/", "").strip()
            return re.sub(r"\s+", " ", cleaned)
        pieces: List[str] = []
        if self.given_name:
            pieces.append(self.given_name)
        if self.surname:
            pieces.append(self.surname)
        return " ".join(pieces) if pieces else self.id


@dataclass
class Family:
    """Representation of a family (husband, wife, children)."""

    id: str
    husband: Optional[str] = None
    wife: Optional[str] = None
    children: List[str] = field(default_factory=list)
    marriage: Event = field(default_factory=Event)


class GedcomParser:
    """Very small GEDCOM parser for the fields used by the site generator."""

    def __init__(self, path: Path):
        self.path = path

    def parse(self) -> tuple[Dict[str, Individual], Dict[str, Family]]:
        individuals: Dict[str, Individual] = {}
        families: Dict[str, Family] = {}

        current_individual: Optional[Individual] = None
        current_family: Optional[Family] = None
        current_section: Optional[str] = None

        with self.path.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n\r")
                if not line:
                    continue
                parts = line.split(" ", 2)
                if len(parts) == 2:
                    level_str, tag = parts
                    value = ""
                elif len(parts) == 3:
                    level_str, tag, value = parts
                else:
                    continue
                try:
                    level = int(level_str)
                except ValueError:
                    continue

                pointer = None
                if tag.startswith("@") and tag.endswith("@"):
                    pointer = tag
                    tag = value
                    value = ""

                if level == 0:
                    current_section = None
                    current_individual = None
                    current_family = None
                    if tag == "INDI" and pointer:
                        current_individual = Individual(id=pointer)
                        individuals[pointer] = current_individual
                    elif tag == "FAM" and pointer:
                        current_family = Family(id=pointer)
                        families[pointer] = current_family
                    else:
                        # We only care about INDI and FAM records.
                        continue
                elif level == 1:
                    current_section = tag
                    if current_individual is not None:
                        if tag == "NAME":
                            current_individual.name = value
                        elif tag == "GIVN":
                            current_individual.given_name = value
                        elif tag == "SURN":
                            current_individual.surname = value
                        elif tag == "SEX":
                            current_individual.sex = value
                        elif tag == "FAMC":
                            current_individual.famc = value
                        elif tag == "FAMS":
                            current_individual.fams.append(value)
                        elif tag in {"BIRT", "DEAT"}:
                            # Sub-sections captured at level 2.
                            pass
                    elif current_family is not None:
                        if tag == "HUSB":
                            current_family.husband = value
                        elif tag == "WIFE":
                            current_family.wife = value
                        elif tag == "CHIL":
                            current_family.children.append(value)
                        elif tag == "MARR":
                            # sub-sections handled at level 2.
                            pass
                elif level == 2:
                    if current_individual is not None:
                        if current_section == "BIRT":
                            if tag == "DATE":
                                current_individual.birth.date = value
                            elif tag == "PLAC":
                                current_individual.birth.place = value
                        elif current_section == "DEAT":
                            if tag == "DATE":
                                current_individual.death.date = value
                            elif tag == "PLAC":
                                current_individual.death.place = value
                    elif current_family is not None and current_section == "MARR":
                        if tag == "DATE":
                            current_family.marriage.date = value
                        elif tag == "PLAC":
                            current_family.marriage.place = value
                # We can safely ignore deeper levels for this project.

        return individuals, families


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
)


NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def parse_date_string(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if re.search(r"[A-Za-z]", cleaned):
        cleaned = cleaned.title()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    if re.fullmatch(r"\d{4}", cleaned):
        return datetime(int(cleaned), 1, 1)
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", cleaned)
    if match:
        month, day, year = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


def birth_sort_key(individual: Individual) -> tuple:
    birth_date = parse_date_string(individual.birth.date)
    if birth_date:
        return (0, birth_date.year, birth_date.month, birth_date.day, normalise(individual.display_name))
    return (1, normalise(individual.display_name))


def extract_name_key(name: str) -> Optional[str]:
    tokens = [token for token in re.split(r"[^A-Za-z]+", name) if token]
    if len(tokens) < 2:
        return None
    first = tokens[0].lower()
    last: Optional[str] = None
    for token in reversed(tokens[1:]):
        lower = token.lower()
        if lower in NAME_SUFFIXES:
            continue
        last = lower
        break
    if not last:
        last = tokens[-1].lower()
    return f"{first} {last}"


def extract_docx_paragraphs(path: Path) -> List[str]:
    try:
        with zipfile.ZipFile(path) as docx:
            data = docx.read("word/document.xml")
    except (FileNotFoundError, KeyError, zipfile.BadZipFile):
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: List[str] = []
    for para in root.findall(".//w:body/w:p", namespace):
        texts: List[str] = []
        for node in para.findall(".//w:t", namespace):
            if node.text:
                texts.append(node.text)
        paragraph = "".join(texts).strip()
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def load_biographies(doc_dir: Path, children: Sequence[Individual]) -> Dict[str, str]:
    available_docs: Dict[str, Path] = {}
    for docx_path in doc_dir.glob("*.docx"):
        key = extract_name_key(docx_path.stem)
        if key:
            available_docs[key] = docx_path
    biographies: Dict[str, str] = {}
    for child in children:
        key = extract_name_key(child.display_name)
        if not key:
            continue
        doc_path = available_docs.get(key)
        if not doc_path:
            continue
        paragraphs = extract_docx_paragraphs(doc_path)
        if not paragraphs:
            continue
        content = "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
        biographies[child.id] = content
    return biographies


def find_individual(individuals: Dict[str, Individual], query: str) -> Individual:
    """Best-effort search for an individual whose name matches *query*."""

    normalized_query = normalise(query)
    if not normalized_query:
        raise ValueError("Empty name provided")

    def score(individual: Individual) -> tuple[int, int]:
        display = normalise(individual.display_name)
        if display == normalized_query:
            return (0, len(display))
        if display.startswith(normalized_query):
            return (1, len(display))
        if normalized_query in display:
            return (2, len(display))
        return (3, len(display))

    matches = sorted(
        (ind for ind in individuals.values() if normalized_query in normalise(ind.display_name)),
        key=score,
    )

    if not matches:
        raise ValueError(f"Could not find an individual matching '{query}'.")
    best = matches[0]
    if len(matches) > 1 and score(matches[1])[0] == score(best)[0]:
        # Ambiguous match, ask for something more precise.
        raise ValueError(
            f"Multiple individuals match '{query}'. Please be more specific or use an ID."
        )
    return best


def find_family_by_spouses(
    families: Dict[str, Family], husband_id: str, wife_id: str
) -> Optional[Family]:
    for fam in families.values():
        if fam.husband == husband_id and fam.wife == wife_id:
            return fam
        if fam.husband == wife_id and fam.wife == husband_id:
            # Handle reversed specification to be friendly.
            return fam
    return None


def collect_descendants(
    individuals: Dict[str, Individual], families: Dict[str, Family], root_family: Family
) -> Set[str]:
    descendants: Set[str] = set()
    to_process: List[str] = list(root_family.children)

    while to_process:
        current = to_process.pop()
        if current in descendants:
            continue
        descendants.add(current)
        person = individuals.get(current)
        if not person:
            continue
        for fam_id in person.fams:
            fam = families.get(fam_id)
            if not fam:
                continue
            for child in fam.children:
                if child not in descendants:
                    to_process.append(child)
    return descendants


def slugify(name: str, identifier: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not base:
        base = identifier.strip("@")
    return f"{base}-{identifier.strip('@')}"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_file(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def render_person_summary(person: Individual) -> str:
    lines: List[str] = []
    birth = person.birth.description()
    death = person.death.description()
    if birth:
        lines.append(f"<p><strong>Born:</strong> {html.escape(birth)}</p>")
    if death:
        lines.append(f"<p><strong>Died:</strong> {html.escape(death)}</p>")
    return "".join(lines)


def person_card(
    person: Individual,
    link: Optional[str] = None,
    extra: Optional[str] = None,
    heading_level: int = 3,
) -> str:
    name_html = html.escape(person.display_name)
    if link:
        name_html = f"<a href=\"{html.escape(link)}\">{name_html}</a>"
    summary = render_person_summary(person)
    extra_html = extra or ""
    return (
        f"<div class='person-card'>"
        f"<h{heading_level}>{name_html}</h{heading_level}>"
        f"{summary}"
        f"{extra_html}"
        "</div>"
    )


def build_children_list(
    children: Sequence[Individual],
    page_lookup: Dict[str, str],
    relative_root: str,
) -> str:
    if not children:
        return "<p class='empty'>No recorded children.</p>"
    items: List[str] = []
    for child in children:
        href = page_lookup.get(child.id)
        if href:
            href = os.path.relpath(href, relative_root)
        items.append(person_card(child, link=href, heading_level=4))
    return "<div class='children-grid'>" + "".join(items) + "</div>"


def build_spouse_text(
    person: Individual,
    individuals: Dict[str, Individual],
    families: Dict[str, Family],
    page_lookup: Dict[str, str],
    relative_root: str,
) -> str:
    spouses: List[str] = []
    for fam_id in person.fams:
        family = families.get(fam_id)
        if not family:
            continue
        spouse_id: Optional[str] = None
        if family.husband == person.id:
            spouse_id = family.wife
        elif family.wife == person.id:
            spouse_id = family.husband
        if not spouse_id:
            continue
        spouse = individuals.get(spouse_id)
        if not spouse:
            continue
        href = None
        if spouse_id in page_lookup:
            href = os.path.relpath(page_lookup[spouse_id], relative_root)
        display = html.escape(spouse.display_name)
        if href:
            display = f"<a href=\"{html.escape(href)}\">{display}</a>"
        marriage = family.marriage.description()
        if marriage:
            display += f" <span class='meta'>(m. {html.escape(marriage)})</span>"
        spouses.append(display)
    if not spouses:
        return "<p><strong>Spouse(s):</strong> None recorded.</p>"
    return "<p><strong>Spouse(s):</strong> " + ", ".join(spouses) + "</p>"


def build_parents_text(
    person: Individual,
    individuals: Dict[str, Individual],
    families: Dict[str, Family],
    page_lookup: Dict[str, str],
    relative_root: str,
    base_family: Family,
    index_relpath: str,
) -> str:
    if not person.famc:
        return ""
    family = families.get(person.famc)
    if not family:
        return ""
    parents: List[str] = []
    for role_id in [family.husband, family.wife]:
        if not role_id:
            continue
        parent = individuals.get(role_id)
        if not parent:
            continue
        href: Optional[str] = None
        if role_id in page_lookup:
            href = os.path.relpath(page_lookup[role_id], relative_root)
        elif family == base_family:
            href = os.path.relpath(index_relpath, relative_root)
        display = html.escape(parent.display_name)
        if href:
            display = f"<a href=\"{html.escape(href)}\">{display}</a>"
        parents.append(display)
    if not parents:
        return ""
    return "<p><strong>Parent(s):</strong> " + ", ".join(parents) + "</p>"


def render_index(
    output_dir: Path,
    base_husband: Individual,
    base_wife: Individual,
    base_family: Family,
    individuals: Dict[str, Individual],
    families: Dict[str, Family],
    page_lookup: Dict[str, str],
) -> None:
    children = [individuals[child_id] for child_id in base_family.children if child_id in individuals]
    children.sort(key=birth_sort_key)

    child_cards: List[str] = []
    for child in children:
        href = page_lookup.get(child.id)
        if href:
            href = os.path.relpath(href, output_dir)
        child_cards.append(
            person_card(
                child,
                link=href,
                heading_level=3,
                extra=build_spouse_text(
                    child,
                    individuals,
                    families,
                    page_lookup,
                    relative_root=str(output_dir),
                ),
            )
        )

    page = f"""<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='utf-8'>
    <title>David and Verna Rucker Family Tree</title>
    <link rel='stylesheet' href='assets/styles.css'>
</head>
<body>
    <div class='container'>
        <header>
            <h1>{html.escape(base_husband.display_name)} &amp; {html.escape(base_wife.display_name)}</h1>
            <p class='lead'>Children are displayed to the right. Click a name to explore that branch of the family.</p>
        </header>
        <section class='base-layout'>
            <div class='base-column'>
                {person_card(base_husband, heading_level=2)}
                {person_card(base_wife, heading_level=2)}
            </div>
            <div class='children-column'>
                <h2>Children</h2>
                <div class='children-grid'>
                    {''.join(child_cards)}
                </div>
            </div>
        </section>
    </div>
</body>
</html>
"""
    write_file(output_dir / "index.html", page)


def render_descendant_page(
    person: Individual,
    output_path: Path,
    individuals: Dict[str, Individual],
    families: Dict[str, Family],
    page_lookup: Dict[str, str],
    base_family: Family,
    index_path: Path,
    biographies: Dict[str, str],
) -> None:
    relative_root = str(output_path.parent)
    index_relpath = str(index_path)

    spouse_html = build_spouse_text(person, individuals, families, page_lookup, relative_root)
    parent_html = build_parents_text(
        person,
        individuals,
        families,
        page_lookup,
        relative_root,
        base_family,
        index_relpath,
    )

    children: List[Individual] = []
    for fam_id in person.fams:
        family = families.get(fam_id)
        if not family:
            continue
        for child_id in family.children:
            child = individuals.get(child_id)
            if child:
                children.append(child)
    # Keep only unique children while preserving order.
    seen: Set[str] = set()
    ordered_children: List[Individual] = []
    for child in children:
        if child.id in seen:
            continue
        seen.add(child.id)
        ordered_children.append(child)
    ordered_children.sort(key=birth_sort_key)

    biography_html = biographies.get(person.id, "")
    biography_section = ""
    if biography_html:
        biography_section = (
            "<section class='person-biography'>"
            "<h2>Biography</h2>"
            f"{biography_html}"
            "</section>\n"
        )

    children_html = build_children_list(ordered_children, page_lookup, relative_root)

    children_section = (
        "<section class='person-children'>"
        "<h2>Children</h2>"
        f"{children_html}"
        "</section>\n"
    )

    page = f"""<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='utf-8'>
    <title>{html.escape(person.display_name)} &mdash; Family Tree</title>
    <link rel='stylesheet' href='../assets/styles.css'>
</head>
<body>
    <div class='container'>
        <header class='page-header'>
            <h1>{html.escape(person.display_name)}</h1>
        </header>
        <section class='person-details'>
            {render_person_summary(person)}
            {spouse_html}
            {parent_html}
            <p><a href='{os.path.relpath(index_path, relative_root)}'>&larr; Back to David and Verna</a></p>
        </section>
        {biography_section}
        {children_section}
    </div>
</body>
</html>
"""
    write_file(output_path, page)


def write_stylesheet(output_dir: Path) -> None:
    css = """
:root {
    color-scheme: light;
}
body {
    font-family: 'Segoe UI', Tahoma, sans-serif;
    margin: 0;
    background: #f3f4f6;
    color: #1f2933;
}
a {
    color: #1d4ed8;
    text-decoration: none;
}
a:hover {
    text-decoration: underline;
}
.container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 2.5rem 1.5rem 4rem;
}
header h1 {
    margin-bottom: 0.25rem;
}
.lead {
    color: #52606d;
    margin-top: 0;
}
.base-layout {
    display: flex;
    flex-wrap: wrap;
    gap: 2rem;
    align-items: flex-start;
}
.base-column {
    flex: 0 0 320px;
    display: grid;
    gap: 1.5rem;
}
.children-column {
    flex: 1 1 360px;
}
.children-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1rem;
}
.person-card {
    background: white;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
    border: 1px solid rgba(15, 23, 42, 0.08);
}
.person-card h2,
.person-card h3,
.person-card h4 {
    margin-top: 0;
    margin-bottom: 0.25rem;
}
.person-card p {
    margin: 0.15rem 0;
}
.person-card .meta {
    color: #64748b;
}
.person-details {
    margin-top: 2rem;
}
.person-details p {
    font-size: 1rem;
}
.person-biography {
    margin-top: 2rem;
}
.person-biography h2 {
    margin-bottom: 0.5rem;
}
.person-biography p {
    margin: 0.75rem 0;
    line-height: 1.6;
}
.person-children {
    margin-top: 2rem;
}
.person-children h2 {
    margin-bottom: 0.75rem;
}
.empty {
    color: #9aa5b1;
}
@media (max-width: 720px) {
    .base-layout {
        flex-direction: column;
    }
    .base-column {
        width: 100%;
    }
    .children-column {
        width: 100%;
    }
}
"""
    write_file(output_dir / "assets" / "styles.css", css)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a family tree website from a GEDCOM file.")
    parser.add_argument("gedcom", type=Path, help="Path to the GEDCOM file (handley.ged).")
    parser.add_argument("output", type=Path, help="Directory for the generated site.")
    parser.add_argument(
        "--base-husband",
        default="David Handley",
        help="Name (or partial name) of the base husband. Default: David Handley",
    )
    parser.add_argument(
        "--base-wife",
        default="Verna Mae Rucker Handley",
        help="Name (or partial name) of the base wife. Default: Verna Mae Rucker Handley",
    )
    parser.add_argument(
        "--base-family-id",
        help="Optional explicit family ID (e.g., @F2@) if you prefer to select the couple by ID.",
    )
    args = parser.parse_args(argv)

    parser_obj = GedcomParser(args.gedcom)
    individuals, families = parser_obj.parse()

    if args.base_family_id:
        base_family = families.get(args.base_family_id)
        if not base_family:
            raise SystemExit(f"Family ID {args.base_family_id} not found in GEDCOM file.")
        if not base_family.husband or not base_family.wife:
            raise SystemExit("Base family must have both husband and wife defined.")
        base_husband = individuals.get(base_family.husband)
        base_wife = individuals.get(base_family.wife)
        if not base_husband or not base_wife:
            raise SystemExit("Base family references individuals that were not found.")
    else:
        base_husband = find_individual(individuals, args.base_husband)

        candidate_pairs: List[tuple[Family, Individual]] = []
        for fam_id in base_husband.fams:
            fam = families.get(fam_id)
            if not fam:
                continue
            if fam.husband == base_husband.id:
                spouse_id = fam.wife
            else:
                spouse_id = fam.husband
            if not spouse_id:
                continue
            spouse = individuals.get(spouse_id)
            if not spouse:
                continue
            candidate_pairs.append((fam, spouse))

        base_family = None
        base_wife = None
        wife_query = normalise(args.base_wife)
        for fam, spouse in candidate_pairs:
            if wife_query and wife_query not in normalise(spouse.display_name):
                continue
            base_family = fam
            base_wife = spouse
            break

        if base_family is None and len(candidate_pairs) == 1:
            base_family, base_wife = candidate_pairs[0]

        if base_family is None or base_wife is None:
            base_wife = find_individual(individuals, args.base_wife)
            base_family = find_family_by_spouses(families, base_husband.id, base_wife.id)
            if not base_family:
                raise SystemExit(
                    "Could not locate a family where the provided individuals are spouses. "
                    "Consider using --base-family-id."
                )

    descendants = collect_descendants(individuals, families, base_family)

    output_dir: Path = args.output
    ensure_dir(output_dir)
    write_stylesheet(output_dir)

    script_dir = Path(__file__).resolve().parent
    base_children = [individuals[child_id] for child_id in base_family.children if child_id in individuals]
    biographies = load_biographies(script_dir, base_children)

    # Determine paths for descendant pages.
    page_lookup: Dict[str, str] = {}
    for descendant_id in descendants:
        person = individuals.get(descendant_id)
        if not person:
            continue
        slug = slugify(person.display_name, person.id)
        page_path = output_dir / "people" / f"{slug}.html"
        page_lookup[descendant_id] = str(page_path)

    render_index(output_dir, base_husband, base_wife, base_family, individuals, families, page_lookup)

    index_path = output_dir / "index.html"

    for descendant_id, page_path_str in page_lookup.items():
        person = individuals.get(descendant_id)
        if not person:
            continue
        render_descendant_page(
            person,
            Path(page_path_str),
            individuals,
            families,
            page_lookup,
            base_family,
            index_path,
            biographies,
        )

    print(f"Generated {len(page_lookup)} descendant pages in {output_dir}.")


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
