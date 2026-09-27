"""Deterministic structure detection over raw extracted text.

Everything in this module is pure Python and runs with no API key. It finds
heading boundaries, definition/procedure/formula/fact lines and keywords so the
platform is useful the moment a student uploads a file - with or without an
LLM configured. The Gemini path in :mod:`app.engine.knowledge.llm_extractor`
refines these same structures.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

# Words that signal a heading line even without markdown/numbering.
HEADING_HINT_RE = re.compile(
    r"\b(chapter|unit|module|section|topic|lecture|part|lesson|appendix|"
    r"introduction|overview|conclusion|summary|definition|theorem|lemma|"
    r"properties|types|methods|algorithm|example|review|exercise)\b",
    re.IGNORECASE,
)
NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,3})[.)]?\s+(\S.{0,90})$")
LETTERED_HEADING_RE = re.compile(r"^\s*([A-Za-z])[.)]\s+(\S.{0,90})$")
BULLET_RE = re.compile(r"^\s*(?:[-*•·‣▪]|\d+[.)])\s+")
DEFINITION_RE = re.compile(
    r"\b(is defined as|refers to|is called|is known as|means that|is the)\b", re.I
)
PROCEDURE_RE = re.compile(
    r"\b(step \d|first,? then|algorithm|procedure|"
    r"to (?:calculate|compute|find|derive|construct|solve)|"
    r"we (?:compute|calculate|apply|substitute)|begin by|finally,|next,? )",
    re.IGNORECASE,
)
FORMULA_RE = re.compile(
    r"([A-Za-z]\w{0,12}\s*=\s*[^.\n]{3,80})|(\$[^$]{4,120}\$)"
    r"|(\b\w+\s*\([^)]*\)\s*=\s*[^.\n]{2,60})"
)
FACT_CUE_RE = re.compile(
    r"\b(important|note that|remember|key point|crucial|essential|must|always|never|"
    r"in fact|significantly|approximately|typically|usually)\b",
    re.IGNORECASE,
)
OBJECTIVE_RE = re.compile(
    r"\b(understand|learn|explain|describe|define|apply|analyz|analyse|compare|"
    r"derive|calculate|identify|evaluate|distinguish|solve|prove)\w*\b",
    re.IGNORECASE,
)
QUESTION_RE = re.compile(r"\?\s*$")

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "aren't",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "cannot",
        "could",
        "couldn't",
        "did",
        "didn't",
        "do",
        "does",
        "doesn't",
        "doing",
        "don't",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "hadn't",
        "has",
        "hasn't",
        "have",
        "haven't",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "isn't",
        "it",
        "its",
        "itself",
        "let's",
        "me",
        "more",
        "most",
        "mustn't",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "ought",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "shan't",
        "she",
        "should",
        "shouldn't",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "wasn't",
        "we",
        "were",
        "weren't",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "with",
        "won't",
        "would",
        "wouldn't",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "also",
        "thus",
        "hence",
        "therefore",
        "within",
        "using",
        "used",
        "use",
        "given",
        "also",
        "may",
        "many",
        "one",
        "two",
        "three",
        "first",
        "second",
        "new",
        "etc",
        "via",
        "per",
        "among",
        "however",
    ]
)

# Words that reliably signal conceptual difficulty in academic text.
HARD_SIGNALS = frozenset(
    [
        "theorem",
        "proof",
        "derive",
        "derivation",
        "integral",
        "matrix",
        "vector",
        "gradient",
        "eigen",
        "spectral",
        "convolution",
        "tensor",
        "morphism",
        "topology",
        "topology",
        "manifold",
        "asymptotic",
        "stochastic",
        "probability",
        "distribution",
        "variance",
        "likelihood",
        "bayesian",
        "optimization",
        "eigenvalue",
        "polynomial",
        "logarithmic",
        "exponential",
        "nonlinear",
        "asymptotic",
        "recurrence",
        "invariant",
        "generalized",
        "generalized",
        "convex",
        "concave",
        "ambiguity",
        "nuance",
        "caveat",
        "constraint",
        "optimization",
        "interpolation",
        "approximation",
        "convergence",
        "stability",
        "stochastic",
        "recursive",
        "recursive",
        "topology",
        "calculus",
        "differential",
        "algebra",
        "geometry",
        "thermodynamic",
        "entropy",
        "quantum",
        "relativistic",
        "heuristic",
    ]
)
MEDIUM_SIGNALS = frozenset(
    [
        "algorithm",
        "procedure",
        "implementation",
        "framework",
        "principle",
        "rule",
        "policy",
        "process",
        "technique",
        "method",
        "formula",
        "equation",
        "calculation",
        "application",
        "example",
        "analysis",
        "comparison",
        "classification",
        "category",
        "hierarchy",
        "workflow",
        "pipeline",
        "architecture",
        "pattern",
        "model",
        "system",
        "design",
        "interface",
        "protocol",
    ]
)


@dataclass(slots=True)
class Section:
    """A contiguous block of text under one detected heading."""

    title: str
    level: int
    lines: list[str] = field(default_factory=list)
    order: int = 0
    parent: str = ""
    #: True for the implicit section created before any heading is found. It is a
    #: preamble, so it can name a module but must never become a topic itself.
    synthetic: bool = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\S+", self.text))

    @property
    def is_trivial(self) -> bool:
        return self.word_count < 8


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" \t#*-=")


# A line containing any of these reads as a sentence, not a heading, however
# suggestive its opening words are. Without this guard "Algorithm: the scheduler
# must minimise waiting time" gets treated as a heading and splits a chapter.
VERB_MARKERS = frozenset(
    [
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "has",
        "have",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "let",
        "lets",
        "get",
        "gets",
        "got",
        "make",
        "makes",
        "made",
        "take",
        "takes",
        "taken",
        "give",
        "gives",
        "given",
        "use",
        "uses",
        "used",
        "require",
        "requires",
        "required",
        "need",
        "needs",
        "allow",
        "allows",
        "allowed",
        "remain",
        "remains",
        "remain",
        "occur",
        "occurs",
        "occur",
    ]
)


def looks_like_heading(line: str) -> tuple[bool, int]:
    """Return ``(is_heading, level)`` for a single line."""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False, 0

    markdown = re.match(r"^(#{1,6})\s+(.*\S)\s*$", stripped)
    if markdown:
        return True, len(markdown.group(1))

    # ALL CAPS titles of reasonable length are headings.
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters) and len(stripped.split()) <= 12:
        return True, 1

    numbered = NUMBERED_HEADING_RE.match(stripped)
    if numbered:
        title = numbered.group(2).strip()
        depth = numbered.group(1).count(".") + 1
        # "1. First, do X" is a list item, not a heading.
        is_list_item = BULLET_RE.match(stripped) and not HEADING_HINT_RE.search(title)
        if not is_list_item and not _reads_as_sentence(stripped):
            return True, min(depth, 4)

    if BULLET_RE.match(stripped) or QUESTION_RE.search(stripped):
        return False, 0

    words = stripped.split()
    if _reads_as_sentence(stripped):
        return False, 0

    if 1 <= len(words) <= 14 and stripped.endswith(":") and HEADING_HINT_RE.search(stripped):
        return True, 1

    if (
        1 <= len(words) <= 12
        and not stripped.endswith((".", ",", ";"))
        and HEADING_HINT_RE.search(stripped)
        and stripped[0].isupper()
    ):
        return True, 1

    lettered = LETTERED_HEADING_RE.match(stripped)
    if lettered and len(stripped) < 80:
        return True, 2

    return False, 0


def _reads_as_sentence(stripped: str) -> bool:
    """True when a line looks like prose rather than a title."""
    words = stripped.split()
    if len(words) > 14:
        return True
    if len(words) > 6 and stripped.endswith((".", "!", "?")):
        return True
    tokens = {w.strip(".,:;()").lower() for w in words}
    return bool(tokens & VERB_MARKERS)


# "Unit 3", "Part B", "Module 2" - a bare container label with no title of its
# own. "Unit 3: Relational Model" is a chapter heading, not a container, and is
# kept as a topic.
CONTAINER_RE = re.compile(
    r"^(part|unit|module|section|book|block|week)\s+(\d+|[ivxlc]+|[a-z])\s*[:.\-\u2013]?\s*$",
    re.IGNORECASE,
)


def split_sections(text: str, *, min_lines: int = 2) -> list[Section]:
    """Split text into sections, starting a new one at each detected heading."""
    lines = text.split("\n")
    sections: list[Section] = []
    current: Section | None = None

    for index, line in enumerate(lines):
        raw_line = line.rstrip()
        is_heading, level = looks_like_heading(raw_line)
        # A lone title line immediately above a heading ("Operating Systems"
        # above "Chapter 1: ...") is a container, not prose. Promote it so the
        # section splitter sees a boundary there.
        if not is_heading and _is_orphan_title(raw_line, lines, index):
            is_heading, level = True, 1
        if is_heading:
            title = re.sub(r"^(#{1,6})\s+", "", line.strip())
            title = NUMBERED_HEADING_RE.sub(r"\2", title)
            title = LETTERED_HEADING_RE.sub(r"\2", title)
            title = title.strip(" :*-=#")
            if title:
                current = Section(title=title[:200], level=level, order=len(sections))
                sections.append(current)
                continue
        if current is None:
            current = Section(title=_preamble_title(text), level=1, order=0, synthetic=True)
            sections.append(current)
        current.lines.append(line)

    # Keep title-only sections for now: a bare subject or document name has no
    # body but is exactly the module label we need. Empties are dropped after
    # module attachment.
    sections = [s for s in sections if s.text.strip() or s.synthetic or s.title.strip()]
    if not sections:
        return []
    if len(sections) == 1 and sections[0].word_count > 120:
        # No detectable structure: synthesise even chunks so we never return one
        # giant pseudo-topic.
        sections = chunk_text(sections[0].text)
    return [s for s in _attach_modules(sections) if s.text.strip()] or sections


def _is_orphan_title(line: str, lines: list[str], index: int) -> bool:
    """True when a short standalone line sits directly above a heading.

    Lecture notes and concatenation boundaries look like this: a bare subject or
    document name on its own line, then a heading. Treating it as prose buries the
    boundary and collapses every topic into one module.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 80 or stripped.endswith((".", ",", ";")):
        return False
    words = stripped.split()
    if not 1 <= len(words) <= 10 or not stripped[0].isalpha():
        return False
    for following in lines[index + 1 : index + 4]:
        if not following.strip():
            continue
        is_next_heading, _ = looks_like_heading(following)
        return is_next_heading
    return False


def _preamble_title(text: str) -> str:
    """Name the implicit pre-heading section after its first short line.

    Lecture notes usually open with the subject or unit name on its own line.
    Reusing it as the title means that name becomes the module for everything
    that follows, instead of a literal "Introduction".
    """
    for line in text.split("\n"):
        candidate = line.strip().strip("*#= ").rstrip(":.")
        if not candidate or len(candidate.split()) > 12 or len(candidate) > 90:
            continue
        if QUESTION_RE.search(candidate):
            continue
        return candidate
    return "General"


def _attach_modules(sections: list[Section]) -> list[Section]:
    """Group sections under container headings so modules come out meaningful.

    A heading is a *container* when it is an explicit "Unit 3"/"Part B" label, or
    when it is a bare title immediately followed by further sections. Containers
    do not become topics themselves - they name the module for what follows.
    """
    if len(sections) < 2:
        return sections

    containers = {
        i
        for i, section in enumerate(sections)
        if i + 1 < len(sections)
        and (
            CONTAINER_RE.match(section.title) or (section.word_count < 25 and not section.synthetic)
        )
    }
    preamble = next((s for s in sections if s.synthetic), None)
    if not containers and preamble is None:
        return sections

    def _owner(index: int) -> str:
        """The nearest container at or before ``index``, else the preamble."""
        for candidate in range(index - 1, -1, -1):
            if candidate in containers:
                return sections[candidate].title
        return preamble.title if preamble is not None else ""

    out: list[Section] = []
    for position, section in enumerate(sections):
        if position in containers:
            continue  # containers name modules, they are not topics
        section.parent = _owner(position)
        section.order = len(out)
        out.append(section)

    return out or sections


def chunk_text(text: str, chunk_lines: int = 14) -> list[Section]:
    """Synthesise evenly sized sections when no heading structure was found."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    sections: list[Section] = []
    for index in range(0, len(lines), chunk_lines):
        part = lines[index : index + chunk_lines]
        if not part:
            continue
        sections.append(
            Section(
                title=f"Section {index // chunk_lines + 1}",
                level=2,
                lines=part,
                order=len(sections),
                parent="Notes",
            )
        )
    return sections


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text.lower())


def extract_keywords(text: str, limit: int = 12) -> list[str]:
    """Frequency keywords with a bonus for academically significant terms."""
    tokens = [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 2]
    if not tokens:
        return []
    counts = Counter(tokens)
    total = sum(counts.values())
    significant = {t for t in counts if t in HARD_SIGNALS or t in MEDIUM_SIGNALS}
    scored: dict[str, float] = {}
    for token, count in counts.items():
        if count < 2 and token not in significant:
            continue
        # Sub-linear frequency so one repeated word cannot dominate.
        score = 1 + math.log1p(count) + (0.6 if token in significant else 0.0)
        if len(token) > 9:
            score *= 1.1
        scored[token] = score / (1 + 0.15 * math.log1p(total / max(count, 1)))
    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    return [token for token, _ in ranked[:limit]]


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if 30 <= len(p.strip()) <= 400]


def mine_definitions(text: str, limit: int = 6) -> list[str]:
    out: list[str] = []
    for sentence in split_sentences(text):
        if DEFINITION_RE.search(sentence) and sentence[0].isupper():
            out.append(sentence)
        if len(out) >= limit:
            break
    return out


def mine_procedures(text: str, limit: int = 6) -> list[str]:
    steps: list[str] = []
    for line in text.split("\n"):
        stripped = _clean_line(line)
        if not stripped or len(stripped) < 12:
            continue
        if (
            re.match(r"^(step\s*\d|algorithm|procedure)\b", stripped, re.IGNORECASE)
            or BULLET_RE.match(line)
            and PROCEDURE_RE.search(stripped)
        ):
            steps.append(stripped[:300])
        if len(steps) >= limit:
            break
    if not steps:
        for sentence in split_sentences(text):
            if PROCEDURE_RE.search(sentence):
                steps.append(sentence)
            if len(steps) >= limit:
                break
    return steps


def mine_formulas(text: str, limit: int = 8) -> list[str]:
    out: list[str] = []
    for line in text.split("\n"):
        stripped = _clean_line(line)
        if not stripped:
            continue
        if FORMULA_RE.search(stripped) and any(ch.isdigit() for ch in stripped):
            out.append(stripped[:240])
        if len(out) >= limit:
            break
    return out


def mine_important_facts(text: str, limit: int = 6) -> list[str]:
    out: list[str] = []
    for sentence in split_sentences(text):
        if FACT_CUE_RE.search(sentence) and len(sentence) > 40:
            out.append(sentence)
        if len(out) >= limit:
            break
    return out


def mine_objectives(text: str, limit: int = 5) -> list[str]:
    """Learning objectives are often stated as imperatives; otherwise infer them."""
    out: list[str] = []
    for line in text.split("\n"):
        stripped = _clean_line(line)
        if len(stripped) < 20:
            continue
        if OBJECTIVE_RE.search(stripped) and re.match(
            r"^(to\s|understand|learn|explain|apply)\b", stripped, re.IGNORECASE
        ):
            out.append(stripped[:240])
        if len(out) >= limit:
            return out
    if not out:
        for sentence in split_sentences(text):
            if OBJECTIVE_RE.search(sentence) and len(sentence) > 40:
                out.append(
                    f"Understand {sentence[0].lower()}{sentence[1:]}"
                    if not sentence[0].islower()
                    else sentence
                )
            if len(out) >= limit:
                break
    return out


def mine_subtopics(text: str, title: str, limit: int = 6) -> list[str]:
    """Bullet lines and short fragments become subtopics."""
    out: list[str] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        stripped = _clean_line(line)
        if not stripped or len(stripped) > 110:
            continue
        is_bullet = bool(BULLET_RE.match(line))
        is_short = len(stripped.split()) <= 9
        if not (is_bullet or is_short):
            continue
        if stripped.lower() == title.lower() or stripped.lower() in seen:
            continue
        seen.add(stripped.lower())
        out.append(stripped[:110])
        if len(out) >= limit:
            break
    return out


def estimate_reading_rate(word_count: int) -> float:
    """Silent-study reading + light note capture, words per minute."""
    return 165.0
