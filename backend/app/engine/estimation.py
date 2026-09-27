"""Difficulty analysis and workload estimation.

Pure deterministic maths - no LLM. Given a topic's text, structure and the
student's declared knowledge level, produce a 0..1 difficulty score, an
Easy/Medium/Hard class and a realistic minute estimate.

All cue signals are measured as **rates per 100 words** rather than raw counts,
so a 40-word section is not automatically easier than a 400-word one.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.core.enums import Difficulty, KnowledgeLevel

# --------------------------------------------------------------------- vocabulary
# Terms that reliably signal conceptual depth. Matched as whole words on the
# lowercased token stream, so plurals and inflections are handled.
HARD_TERMS = frozenset(
    [
        "theorem",
        "proof",
        "lemma",
        "corollary",
        "axiom",
        "invariant",
        "convergence",
        "asymptotic",
        "derivation",
        "derivative",
        "integral",
        "gradient",
        "eigen",
        "spectral",
        "convolution",
        "tensor",
        "morphism",
        "topology",
        "topological",
        "manifold",
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
        "recurrence",
        "convex",
        "concave",
        "ambiguity",
        "nuance",
        "caveat",
        "constraint",
        "amortized",
        "recursion",
        "recursion",
        "calculus",
        "differential",
        "algebra",
        "geometric",
        "entropy",
        "quantum",
        "relativistic",
        "generalized",
        "generalization",
        "abstraction",
        "rigorous",
        "paradox",
        "nontrivial",
        "hypothesis",
        "formulation",
        "representation",
        "encoding",
        "decoding",
        "induction",
        "inductive",
        "combinatorial",
        "asymptotics",
        "perturbation",
        "approximation",
        "interpolation",
        "discretization",
        "stochasticity",
        "volatility",
        "correlation",
        "regression",
        "causality",
        "inference",
        "estimation",
        "significance",
        "variance",
        "credible",
        "confidence",
        "interval",
        "quantiles",
        "permutation",
        "homology",
        "cohomology",
        "isometry",
        "isometric",
        "embedding",
        "bijection",
        "homomorphism",
        "eigenfunction",
        "eigenvalues",
        "characteristic",
        "minimality",
        "extremal",
        "compactness",
        "completeness",
        "measurability",
        "integrability",
        "differentiability",
        "continuity",
        "discontinuity",
        "singularities",
        "asymptotic",
        "analysis",
        "criterion",
        "criteria",
    ]
)

MEDIUM_TERMS = frozenset(
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
        "abstraction",
        "deployment",
        "configuration",
        "constraint",
        "threshold",
        "baseline",
        "heuristic",
        "approximation",
        "scheduling",
        "allocation",
        "virtual",
        "memory",
        "paging",
        "segmentation",
        "deadlock",
        "allocation",
        "file",
        "system",
        "kernel",
        "interrupt",
        "syscall",
        "thread",
        "process",
        "compiler",
        "parser",
        "interpreter",
        "recursion",
        "concurrency",
        "parallelism",
        "caching",
        "latency",
        "throughput",
        "bandwidth",
        "throughput",
    ]
)

PRACTICE_CUE_RE = re.compile(
    r"\b(calculate|compute|derive|prove|solve|apply|construct|evaluate|analy[sz]e|"
    r"implement|design|optimi[sz]e|determine|estimate|predict|classify|verify|"
    r"illustrate|demonstrate|compare|justify|validate)\w*\b",
    re.IGNORECASE,
)
FORMAL_CUE_RE = re.compile(
    r"\b(theorem|axiom|proof|invariant|convergen\w*|asymptotic\w*|derivation|"
    r"generaliz\w*|abstract\w*|formal\w*|axiomatic|topolog\w*|paradigm|"
    r"hypothes\w*|lemma|corollary|implication|converse\w*|therefore|"
    r"consequently|whereas|thereby|fundamentally|underlying|inevitab\w*|"
    r"necessary condition|sufficient condition|counterpart|analogue|"
    r"optimal\w*|minimi[sz]\w*|maximi[sz]\w*|guarantee\w*|trade-?off|"
    r"degenerat\w*|ambigu\w*|nuance|caveat|subtle\w*|analog\w*|equivalen\w*)\b",
    re.IGNORECASE,
)
MATH_SYMBOL_RE = re.compile(
    r"[=<>+\-*/^]|\\frac|\\sum|\\int|\\sqrt|\bderivative\b|\bintegral\b", re.IGNORECASE
)
# A single-letter variable next to an operator is maths even without digits,
# e.g. "T = q/n" or "E = mc^2".
MATH_VAR_RE = re.compile(
    r"\b[a-zA-Z]\b\s*(?:[=<>]|=>|~)\s*|\b[a-zA-Z]\^\d|\b\w+\s*=\s*\(?\s*[a-zA-Z]\b"
)
DIGIT_RE = re.compile(r"\d")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
ACRONYM_RE = re.compile(r"\b[A-Z]{2,}[a-z]?\b")
PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{3,}\b")
# "Banker's algorithm", "Coffman conditions", "Belady's anomaly" - a named
# technique or result the student must recall by name, not just understand.
NAMED_PATTERN_RE = re.compile(
    r"\b([A-Z][\w'-]*(?:'s)?)\s+"
    r"(algorithm|theorem|lemma|condition|conditions|policy|policies|method|methods|"
    r"rule|rules|principle|law|model|test|effect|anomaly|equation|function|"
    r"structure|strategy|scheduling|mechanism|property|properties|inequality)\b"
)
# Capitalised words that start sentences constantly and are not named entities.
SENTENCE_STARTERS = frozenset(
    [
        "the",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "it",
        "its",
        "they",
        "them",
        "their",
        "then",
        "than",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "while",
        "whereas",
        "because",
        "since",
        "however",
        "therefore",
        "thus",
        "hence",
        "consequently",
        "moreover",
        "furthermore",
        "additionally",
        "finally",
        "first",
        "second",
        "third",
        "next",
        "last",
        "finally",
        "step",
        "steps",
        "note",
        "notes",
        "important",
        "key",
        "crucial",
        "essential",
        "chapter",
        "section",
        "unit",
        "module",
        "topic",
        "lecture",
        "part",
        "lesson",
        "appendix",
        "introduction",
        "overview",
        "conclusion",
        "summary",
        "definition",
        "theorem",
        "example",
        "review",
        "exercise",
        "algorithm",
        "algorithms",
        "procedure",
        "procedures",
        "process",
        "processes",
        "step",
        "round",
        "robin",
        "time",
        "memory",
        "file",
        "files",
        "system",
        "systems",
        "data",
        "number",
        "numbers",
        "both",
        "each",
        "every",
        "an",
        "a",
        "and",
        "or",
        "but",
        "so",
        "if",
        "when",
        "after",
        "before",
        "during",
        "between",
        "among",
        "within",
        "without",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "to",
        "of",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "not",
        "no",
        "nor",
        "only",
        "also",
        "just",
        "very",
        "much",
        "many",
        "more",
        "most",
        "other",
        "another",
        "each",
        "such",
        "own",
        "same",
        "both",
        "few",
        "several",
        "various",
        "given",
        "using",
        "used",
        "use",
    ]
)
SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")
SUBORDINATOR_RE = re.compile(
    r"\b(which|that|whereas|although|because|since|however|therefore|thus|hence|"
    r"while|where|when|unless|whereupon|accordingly|consequently)\b",
    re.IGNORECASE,
)
DEFINITION_MARKER_RE = re.compile(
    r"\b(is defined as|refers to|is called|is known as|is a |is the )\b", re.IGNORECASE
)

# Saturation points: the rate (or ratio) at which a signal is considered "maxed".
SAT_HARD_RATE = 7.0  # hard terms per 100 words
SAT_LONG_WORD_RATIO = 0.22  # share of content words at 9+ characters
SAT_FORMAL_RATE = 3.5  # formal-language cues per 100 words
SAT_MATH_RATE = 8.0  # maths expressions per 100 words
SAT_PRACTICE_RATE = 2.5  # practice cues per 100 words
SAT_STRUCTURE = 9.0  # subtopics + formulas + procedures
SAT_SENTENCE_LENGTH = 30.0  # mean words per sentence

# Time model constants.
ORIENTATION_MINUTES = 4.0  # getting oriented in an unfamiliar section
COMPREHENSION_WPM = 30.0  # effective first-pass study rate with light note-taking
MAX_TOPIC_MINUTES = 120


def _rate(count: int, words: int) -> float:
    """Normalise a count to 'per 100 words', with a 25-word floor for stability."""
    return (count * 100.0) / max(25, words)


def _sat(value: float, point: float) -> float:
    if point <= 0:
        return 0.0
    return max(0.0, min(1.0, value / point))


@dataclass(slots=True)
class TopicMetrics:
    """Raw, model-free measurements used by both scoring and estimation."""

    word_count: int
    sentence_count: int
    content_word_count: int
    content_token_count: int
    long_word_count: int
    hard_term_count: int
    domain_term_count: int
    formal_cue_count: int
    math_symbol_count: int
    practice_cue_count: int
    definition_count: int
    proper_noun_count: int
    named_concept_count: int
    acronym_count: int
    subtopic_count: int
    formula_count: int
    procedure_count: int
    avg_sentence_length: float

    @property
    def distinct_terms(self) -> int:
        """Named things the student must hold in mind: definitions, named
        techniques, proper nouns and acronyms."""
        return self.definition_count + self.named_concept_count


def measure(
    text: str,
    *,
    keyword_count: int,
    subtopic_count: int,
    formula_count: int,
    procedure_count: int,
) -> TopicMetrics:
    words = text.split()
    word_count = len(words)
    lowered = text.lower()
    tokens = TOKEN_RE.findall(lowered)
    content = [t for t in tokens if t not in _FUNCTION_WORDS]
    sentences = [s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]

    proper_nouns = [
        m.group(0)
        for m in PROPER_NOUN_RE.finditer(text)
        if m.group(0).lower() not in SENTENCE_STARTERS
    ]
    named = {m.group(1).lower() for m in NAMED_PATTERN_RE.finditer(text)}
    named -= SENTENCE_STARTERS

    return TopicMetrics(
        word_count=word_count,
        sentence_count=len(sentences) or 1,
        content_word_count=len(content) or 1,
        content_token_count=len(set(content)),
        long_word_count=sum(1 for t in content if len(t) >= 9),
        hard_term_count=sum(1 for t in tokens if t in HARD_TERMS),
        domain_term_count=sum(1 for t in tokens if t in HARD_TERMS or t in MEDIUM_TERMS),
        formal_cue_count=len(FORMAL_CUE_RE.findall(text)),
        # Count maths operators once, not once per regex alternative.
        math_symbol_count=len(MATH_SYMBOL_RE.findall(text)) + len(MATH_VAR_RE.findall(text)),
        practice_cue_count=len(PRACTICE_CUE_RE.findall(text)),
        definition_count=len(DEFINITION_MARKER_RE.findall(text)),
        proper_noun_count=len(proper_nouns),
        named_concept_count=len(named),
        acronym_count=len(ACRONYM_RE.findall(text)),
        subtopic_count=subtopic_count,
        formula_count=formula_count,
        procedure_count=procedure_count,
        avg_sentence_length=(word_count / len(sentences)) if sentences else float(word_count),
    )


def _function_words() -> frozenset[str]:
    from app.engine.heuristics import STOPWORDS

    extra = {
        "this",
        "that",
        "these",
        "those",
        "such",
        "also",
        "then",
        "than",
        "when",
        "each",
        "both",
        "been",
        "being",
        "does",
        "doing",
        "done",
        "have",
        "having",
        "into",
        "onto",
        "upon",
        "with",
        "within",
        "without",
        "across",
        "among",
        "between",
        "during",
        "through",
        "before",
        "after",
        "above",
        "below",
        "under",
        "over",
        "again",
        "further",
        "once",
        "here",
        "there",
        "very",
        "much",
        "many",
        "some",
        "any",
        "all",
        "one",
        "two",
        "use",
        "used",
        "using",
        "make",
        "makes",
        "made",
        "get",
        "gets",
        "see",
        "seen",
        "way",
        "ways",
        "thing",
        "things",
        "part",
        "parts",
        "case",
        "cases",
        "point",
        "points",
        "time",
        "times",
        "work",
        "works",
        "give",
        "gives",
        "given",
        "call",
        "calls",
        "called",
        "take",
        "takes",
        "taken",
        "come",
        "comes",
        "went",
        "know",
        "known",
        "need",
        "needs",
        "want",
        "find",
        "found",
    }
    return frozenset(STOPWORDS | extra)


_FUNCTION_WORDS = _function_words()


# Component weights sum to 1.0 so the score reads directly as "how much of the
# maximum possible difficulty is present here". Ordered by how reliably each
# signal separates easy material from hard material in real lecture notes.
WEIGHTS = {
    "volume": 0.16,
    "formal": 0.20,
    "math": 0.14,
    "practice": 0.12,
    "structure": 0.14,
    "syntax": 0.12,
    "vocabulary": 0.12,
}


def difficulty_score(metrics: TopicMetrics, level: KnowledgeLevel) -> float:
    """Return 0..1 intrinsic difficulty, adjusted for the student's declared level.

    A higher declared level shrinks the gap the student must close, so the score
    is scaled rather than subtracted - that keeps genuinely hard material hard
    no matter who is studying it.
    """
    long_word_share = metrics.long_word_count / max(1, metrics.content_word_count)
    components = {
        "volume": 1.0 - math.exp(-metrics.word_count / 450.0),
        "formal": _sat(_rate(metrics.formal_cue_count, metrics.word_count), SAT_FORMAL_RATE),
        "math": _sat(_rate(metrics.math_symbol_count, metrics.word_count), SAT_MATH_RATE),
        "practice": _sat(_rate(metrics.practice_cue_count, metrics.word_count), SAT_PRACTICE_RATE),
        "structure": _sat(
            metrics.subtopic_count + metrics.formula_count + metrics.procedure_count, SAT_STRUCTURE
        ),
        # Longer sentences mean denser prose, which is cognitively harder.
        "syntax": _sat(metrics.avg_sentence_length, SAT_SENTENCE_LENGTH),
        # Two independent vocabulary signals: curated hard terms, plus a generic
        # long-word share that catches technical prose the lists miss.
        "vocabulary": 0.6 * _sat(_rate(metrics.hard_term_count, metrics.word_count), SAT_HARD_RATE)
        + 0.4 * _sat(long_word_share, SAT_LONG_WORD_RATIO),
    }

    score = sum(WEIGHTS[key] * value for key, value in components.items())

    # Knowledge-level adjustment: a novice faces ~22% more load, an expert ~22% less.
    adjustment = 1.0 + (3 - level.rank) * 0.11
    return round(max(0.0, min(1.0, score * adjustment)), 4)


def classify(score: float) -> Difficulty:
    if score < 0.30:
        return Difficulty.EASY
    if score < 0.48:
        return Difficulty.MEDIUM
    return Difficulty.HARD


def estimate_minutes(metrics: TopicMetrics, difficulty: Difficulty, level: KnowledgeLevel) -> int:
    """Minutes for a first-pass learning session on this topic.

    Driven by *comprehension* cost rather than reading speed: skimming 1000 words
    takes six minutes, but understanding and noting them takes half an hour.
    """
    orient = ORIENTATION_MINUTES
    comprehend = metrics.word_count / COMPREHENSION_WPM
    concepts = 0.5 * metrics.definition_count + 0.4 * metrics.named_concept_count
    structure = 1.2 * metrics.formula_count + 1.8 * metrics.procedure_count
    practice = 2.0 * min(8, metrics.practice_cue_count)

    raw = orient + comprehend + concepts + structure + practice
    multiplier = {Difficulty.EASY: 0.9, Difficulty.MEDIUM: 1.0, Difficulty.HARD: 1.25}[difficulty]
    # Experts skim rather than read; novices re-read. Clamped to a humane range.
    level_multiplier = 1.0 + (3 - level.rank) * 0.09

    minutes = raw * multiplier * level_multiplier
    # Snap to 5-minute increments for humane scheduling.
    minutes = max(10.0, min(float(MAX_TOPIC_MINUTES), round(minutes / 5.0) * 5.0))
    return int(minutes)


def revision_minutes(learn_minutes: int, difficulty: Difficulty, importance: float) -> int:
    """Second-pass recall time, plus a bump for hard/high-yield topics."""
    base = (
        learn_minutes
        * {Difficulty.EASY: 0.25, Difficulty.MEDIUM: 0.32, Difficulty.HARD: 0.45}[difficulty]
    )
    base *= 0.85 + 0.3 * max(0.0, min(1.0, importance))
    return int(max(5, min(45, round(base / 5.0) * 5.0)))


def feasibility(total_minutes: int, daily_minutes: int, days_left: int) -> tuple[bool, float, str]:
    """Is the workload achievable in the remaining days?"""
    if days_left <= 0:
        return (total_minutes == 0, 0.0, "Exam date has passed - treating as revision only.")
    capacity = max(1, daily_minutes) * days_left
    required_daily = total_minutes / days_left
    if total_minutes <= capacity:
        return (
            True,
            capacity / max(total_minutes, 1),
            f"Fits at about {required_daily:.0f} min/day.",
        )
    over = total_minutes - capacity
    per_day_shortfall = over // max(days_left, 1)
    return (
        False,
        capacity / max(total_minutes, 1),
        (
            f"Needs about {required_daily:.0f} min/day but only {daily_minutes} min/day are "
            f"available over {days_left} days. Raise the daily budget by {per_day_shortfall} "
            "min/day, or triage the lowest-importance topics."
        ),
    )
