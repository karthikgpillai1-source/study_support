"""Study intelligence pipeline: raw text -> structured JSON.

Order of operations (all deterministic except the optional LLM step):

1. split into sections
2. mine definitions / procedures / formulas / facts / keywords / objectives
3. score difficulty and estimate time per topic  (owned by :mod:`estimation`)
4. optionally refine the *structure* with the configured LLM
5. re-apply deterministic scoring so timing never depends on the model

The LLM may reorganise topics, names and content. It may never set difficulty
or time estimates - those stay reproducible with the model switched off.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.core.enums import Difficulty, KnowledgeLevel, StudyMode

from . import estimation, heuristics
from .extraction.extractors import ExtractedDocument
from .llm import LLMError, llm_client

logger = logging.getLogger(__name__)

MIN_TOPIC_WORDS = 40
MAX_TOPIC_WORDS = 2200
SUMMARY_EXCERPT_CHARS = 600


# --------------------------------------------------------------------------- models
class ExtractedTopic(BaseModel):
    module_title: str = "General"
    title: str
    position: int = 0
    difficulty: Difficulty = Difficulty.MEDIUM
    difficulty_score: float = 0.5
    estimated_minutes: int = 30
    revision_minutes: int = 10
    importance: float = 0.5
    keywords: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    important_facts: list[str] = Field(default_factory=list)
    subtopics: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    source_excerpt: str = ""

    @field_validator("estimated_minutes")
    @classmethod
    def _clamp_learn_minutes(cls, v: int) -> int:
        return max(5, min(180, v))

    @field_validator("revision_minutes")
    @classmethod
    def _clamp_revision_minutes(cls, v: int) -> int:
        return max(5, min(60, v))

    @field_validator("importance")
    @classmethod
    def _clamp_importance(cls, v: float) -> float:
        return round(max(0.05, min(1.0, float(v))), 3)


class ExtractedModule(BaseModel):
    title: str
    position: int = 0
    summary: str = ""
    topic_titles: list[str] = Field(default_factory=list)


class StudyIntelligenceJSON(BaseModel):
    """The engine's canonical output contract (the spec's "Structured JSON")."""

    subject_hint: str = ""
    summary: str = ""
    modules: list[ExtractedModule] = Field(default_factory=list)
    topics: list[ExtractedTopic] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    total_minutes: int = 0
    revision_minutes: int = 0
    confidence: float = 0.5
    source: str = "heuristic"
    warnings: list[str] = Field(default_factory=list)

    def recalculate_totals(self) -> StudyIntelligenceJSON:
        self.total_minutes = sum(t.estimated_minutes for t in self.topics)
        self.revision_minutes = sum(t.revision_minutes for t in self.topics)
        return self


class IntelligenceRequest(BaseModel):
    """Knobs the API layer passes into the engine."""

    subject_name: str
    knowledge_level: KnowledgeLevel = KnowledgeLevel.BEGINNER
    study_mode: StudyMode = StudyMode.FAST_EXAM
    exam_date: date | None = None
    use_llm: bool = True


# ------------------------------------------------------------------------ utilities
def _dedupe(items: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = re.sub(r"\s+", " ", str(item)).strip()
        if not cleaned:
            continue
        key = cleaned.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if limit is not None and len(out) >= limit:
            break
    return out


def _score_and_time(topic: ExtractedTopic, body: str, level: KnowledgeLevel) -> ExtractedTopic:
    """Attach deterministic difficulty + time to a topic. Idempotent."""
    keywords = topic.keywords or heuristics.extract_keywords(body, limit=10)
    subtopics = topic.subtopics or heuristics.mine_subtopics(body, topic.title)
    formulas = topic.formulas or heuristics.mine_formulas(body)
    procedures = topic.procedures or heuristics.mine_procedures(body)
    topic.keywords = keywords
    topic.subtopics = subtopics
    topic.concepts = topic.concepts or subtopics or keywords[:5]
    topic.procedures = procedures
    topic.formulas = formulas
    topic.important_facts = topic.important_facts or heuristics.mine_important_facts(body)
    topic.definitions = topic.definitions or heuristics.mine_definitions(body)
    topic.learning_objectives = topic.learning_objectives or heuristics.mine_objectives(body)

    metrics = estimation.measure(
        body or topic.title,
        keyword_count=len(keywords),
        subtopic_count=len(subtopics),
        formula_count=len(formulas),
        procedure_count=len(procedures),
    )
    topic.difficulty_score = estimation.difficulty_score(metrics, level)
    topic.difficulty = estimation.classify(topic.difficulty_score)
    topic.estimated_minutes = estimation.estimate_minutes(metrics, topic.difficulty, level)
    topic.revision_minutes = estimation.revision_minutes(
        topic.estimated_minutes, topic.difficulty, topic.importance
    )
    return topic


def _importance_for(section: heuristics.Section, position: int, total: int) -> float:
    """Position and title cues drive exam-relevance - not LLM opinion."""
    score = 0.45
    if re.search(
        r"\b(conclusion|summary|revision|important|key|exam|final)\b", section.title, re.I
    ):
        score += 0.25
    if re.search(
        r"\b(introduction|overview|history|background|preliminaries)\b", section.title, re.I
    ):
        score -= 0.12
    if position < 3 or position >= total - 2:
        score += 0.08
    score += 0.10 * min(1.0, section.word_count / 700.0)
    return round(max(0.05, min(1.0, score)), 3)


def _split_oversized(section: heuristics.Section, max_words: int) -> list[heuristics.Section]:
    """Split oversized sections so no single topic blows past the time cap."""
    if section.word_count <= max_words:
        return [section]

    chunks: list[list[str]] = []
    buffer: list[str] = []
    buffer_words = 0
    for line in section.lines:
        words = len(line.split())
        if buffer and buffer_words + words > max_words:
            chunks.append(buffer)
            buffer, buffer_words = [], 0
        buffer.append(line)
        buffer_words += words
    if buffer:
        chunks.append(buffer)

    out: list[heuristics.Section] = []
    for index, lines in enumerate(chunks):
        title = section.title if index == 0 else f"{section.title} ({index + 1})"
        out.append(
            heuristics.Section(
                title=title[:200],
                level=section.level,
                lines=lines,
                order=len(out),
                parent=section.parent,
            )
        )
    return out


def _build_summary(
    subject_name: str, topics: list[ExtractedTopic], document: ExtractedDocument
) -> str:
    minutes = sum(t.estimated_minutes for t in topics)
    hard = sum(1 for t in topics if t.difficulty is Difficulty.HARD)
    easy = sum(1 for t in topics if t.difficulty is Difficulty.EASY)
    medium = len(topics) - easy - hard
    top = [t.title for t in sorted(topics, key=lambda t: t.importance, reverse=True)[:3]]
    return (
        f"{subject_name}: {len(topics)} topics from {document.word_count} words "
        f"across {document.page_count} page(s), about {minutes} minutes of study "
        f"({easy} easy / {medium} medium / {hard} hard). "
        f"Highest-yield: {', '.join(top) if top else 'n/a'}."
    )


def _heuristic_confidence(sections: list[heuristics.Section]) -> float:
    if not sections:
        return 0.0
    titled = sum(1 for s in sections if not re.match(r"^Section \d+$", s.title))
    structure = titled / len(sections)
    avg_words = sum(s.word_count for s in sections) / len(sections)
    density = min(1.0, avg_words / 250.0)
    return round(min(0.95, 0.35 + 0.45 * structure + 0.20 * density), 3)


# ---------------------------------------------------------------------- heuristic
def build_heuristic_intelligence(
    document: ExtractedDocument, request: IntelligenceRequest
) -> StudyIntelligenceJSON:
    text = document.text
    if not text.strip():
        raise ValueError("Document produced no readable text")

    sections: list[heuristics.Section] = []
    for section in heuristics.split_sections(text):
        sections.extend(_split_oversized(section, MAX_TOPIC_WORDS))

    # Drop stray headings that carry almost no content (a bare title on its own
    # line), unless dropping them would leave us with nothing to study.
    substantial = [s for s in sections if s.word_count >= MIN_TOPIC_WORDS]
    if substantial:
        sections = substantial
    if not sections:
        sections = heuristics.chunk_text(text)

    total = len(sections)
    topics: list[ExtractedTopic] = []
    keyword_counts: Counter = Counter()
    objectives: list[str] = []
    formulas: list[str] = []

    for index, section in enumerate(sections):
        body = section.text
        topic = ExtractedTopic(
            module_title=section.parent or "General",
            title=section.title,
            position=index,
            importance=_importance_for(section, index, total),
            source_excerpt=body[:SUMMARY_EXCERPT_CHARS],
        )
        _score_and_time(topic, body, request.knowledge_level)
        topics.append(topic)
        keyword_counts.update(topic.keywords)
        objectives.extend(topic.learning_objectives)
        formulas.extend(topic.formulas)

    modules = _roll_up_modules(topics)
    return StudyIntelligenceJSON(
        subject_hint=request.subject_name,
        summary=_build_summary(request.subject_name, topics, document),
        modules=modules,
        topics=topics,
        keywords=[word for word, _ in keyword_counts.most_common(18)],
        learning_objectives=_dedupe(objectives, limit=12),
        formulas=_dedupe(formulas, limit=15),
        source="heuristic",
        confidence=_heuristic_confidence(sections),
        warnings=list(document.warnings),
    ).recalculate_totals()


def _roll_up_modules(topics: list[ExtractedTopic]) -> list[ExtractedModule]:
    modules: list[ExtractedModule] = []
    index: dict[str, ExtractedModule] = {}
    for topic in topics:
        module = index.get(topic.module_title)
        if module is None:
            module = ExtractedModule(title=topic.module_title, position=len(modules))
            index[topic.module_title] = module
            modules.append(module)
        module.topic_titles.append(topic.title)
    for module in modules:
        excerpts = [t.source_excerpt for t in topics if t.module_title == module.title]
        module.summary = re.sub(r"\s+", " ", " ".join(excerpts))[:280].strip()
    return modules


# ---------------------------------------------------------------------------- llm
_SYSTEM = (
    "You convert academic notes into strict JSON describing a study plan. "
    "Only use information present in the notes. Never invent facts."
)


def build_llm_prompt(document: ExtractedDocument, request: IntelligenceRequest) -> str:
    excerpt = document.text[:28_000]
    mode_hint = (
        "The student is cramming for an exam soon. Emphasise high-yield, exam-relevant "
        "and easily-forgotten content, and keep the topic count tight."
        if request.study_mode is StudyMode.FAST_EXAM
        else "The student is following college pace. Emphasise broad coverage, even "
        "progression and topics that need repeated revision."
    )
    level_hint = request.knowledge_level.description
    return f"""Subject: {request.subject_name}
Student: {request.knowledge_level.value} (level {request.knowledge_level.rank}/5) - {level_hint}
Study mode: {request.study_mode.value}
{mode_hint}

Return ONLY a JSON object with this exact shape:
{{
  "summary": "2-3 sentence overview of the material",
  "keywords": ["..."],
  "learning_objectives": ["After studying this the student can ..."],
  "formulas": ["E = mc^2"],
  "modules": [{{"title": "...", "summary": "..."}}],
  "topics": [
    {{
      "module_title": "must exactly match a module title",
      "title": "clear topic name",
      "learning_objectives": ["..."],
      "definitions": ["term: definition"],
      "procedures": ["step-by-step procedure"],
      "formulas": ["..."],
      "important_facts": ["..."],
      "subtopics": ["..."],
      "concepts": ["..."],
      "keywords": ["..."],
      "importance": 0.0
    }}
  ]
}}

Rules:
- Produce between 6 and 30 topics. Merge trivial sections, split anything huge.
- importance is 0.0-1.0 exam relevance.
- Do NOT output difficulty or estimated_minutes; the platform computes both itself.
- Every topic's module_title must appear in "modules".

NOTES START
{excerpt}
NOTES END
"""


def _coerce_llm_payload(payload: object) -> StudyIntelligenceJSON | None:
    if not isinstance(payload, dict):
        return None
    topics_raw = payload.get("topics")
    if not isinstance(topics_raw, list) or not topics_raw:
        return None

    modules_raw = payload.get("modules")
    modules: list[ExtractedModule] = []
    if isinstance(modules_raw, list):
        for item in modules_raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip() or "General"
            modules.append(
                ExtractedModule(
                    title=title[:200],
                    position=len(modules),
                    summary=str(item.get("summary") or "")[:500],
                )
            )

    topics: list[ExtractedTopic] = []
    for item in topics_raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        topics.append(
            ExtractedTopic(
                module_title=str(item.get("module_title") or "General").strip()[:200] or "General",
                title=title[:300],
                position=len(topics),
                importance=importance,
                learning_objectives=_str_list(item.get("learning_objectives")),
                definitions=_str_list(item.get("definitions")),
                procedures=_str_list(item.get("procedures")),
                formulas=_str_list(item.get("formulas")),
                important_facts=_str_list(item.get("important_facts")),
                subtopics=_str_list(item.get("subtopics")),
                concepts=_str_list(item.get("concepts")),
                keywords=_str_list(item.get("keywords")),
                source_excerpt=str(item.get("source_excerpt") or "")[:SUMMARY_EXCERPT_CHARS],
            )
        )
    if not topics:
        return None
    if not modules:
        modules = [ExtractedModule(title=modules_title(topics), position=0)]
    return StudyIntelligenceJSON(
        summary=str(payload.get("summary") or "")[:1200],
        modules=modules,
        topics=topics,
        keywords=_str_list(payload.get("keywords")),
        learning_objectives=_str_list(payload.get("learning_objectives")),
        formulas=_str_list(payload.get("formulas")),
        source="llm",
        confidence=0.8,
    )


def _str_list(value: object, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item.strip()[:400])
        elif isinstance(item, dict):
            for key in ("term", "name", "title", "text", "statement", "formula"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    out.append(candidate.strip()[:400])
                    break
    return _dedupe(out, limit=limit)


def modules_title(topics: list[ExtractedTopic]) -> str:
    counts = Counter(t.module_title for t in topics)
    return counts.most_common(1)[0][0] if counts else "General"


def _best_match(topic: ExtractedTopic, pool: list[ExtractedTopic]) -> ExtractedTopic | None:
    """Pick the heuristic topic whose vocabulary overlaps this LLM topic most."""
    target = {k.lower() for k in topic.keywords} | set(
        re.findall(r"[a-z]{3,}", topic.title.lower())
    )
    if not target:
        return None
    best: tuple[float, ExtractedTopic] | None = None
    for candidate in pool:
        vocab = {k.lower() for k in candidate.keywords} | set(
            re.findall(r"[a-z]{3,}", candidate.title.lower())
        )
        if not vocab:
            continue
        overlap = len(target & vocab) / len(target | vocab)
        if best is None or overlap > best[0]:
            best = (overlap, candidate)
    if best is None or best[0] < 0.10:
        return None
    return best[1]


def merge_llm_result(
    base: StudyIntelligenceJSON, parsed: StudyIntelligenceJSON, level: KnowledgeLevel
) -> StudyIntelligenceJSON:
    """Keep LLM structure, keep deterministic timing.

    ``parsed.estimated_minutes`` and any difficulty value the model produced are
    discarded. Each LLM topic is matched back to the heuristic topic covering the
    same source text so its real body drives difficulty and time.
    """
    valid_modules = {m.title for m in parsed.modules} or {"General"}
    for topic in parsed.topics:
        if topic.module_title not in valid_modules:
            topic.module_title = sorted(valid_modules)[0]
        match = _best_match(topic, base.topics)
        if match is not None and match.source_excerpt and not topic.source_excerpt:
            topic.source_excerpt = match.source_excerpt
        _score_and_time(topic, topic.source_excerpt or topic.title, level)

    parsed.summary = parsed.summary or base.summary
    parsed.subject_hint = base.subject_hint
    parsed.keywords = _dedupe(parsed.keywords or base.keywords, limit=18)
    parsed.learning_objectives = _dedupe(
        parsed.learning_objectives or base.learning_objectives, limit=12
    )
    parsed.formulas = _dedupe(parsed.formulas or base.formulas, limit=15)
    for index, module in enumerate(parsed.modules):
        module.position = index
        module.topic_titles = [t.title for t in parsed.topics if t.module_title == module.title]
    return parsed.recalculate_totals()


async def refine_with_llm(
    document: ExtractedDocument,
    request: IntelligenceRequest,
    base: StudyIntelligenceJSON,
) -> StudyIntelligenceJSON:
    """Enrich a heuristic result with LLM structure. Never raises."""
    if not request.use_llm or llm_client.active_provider == "none":
        return base
    try:
        result = await llm_client.generate_json(
            build_llm_prompt(document, request), system=_SYSTEM, temperature=0.15
        )
    except LLMError as exc:
        logger.warning("LLM refinement failed, using heuristic result: %s", exc)
        base.warnings.append(f"AI refinement unavailable ({exc}); structural analysis used.")
        return base

    parsed = _coerce_llm_payload(result.data)
    if parsed is None:
        base.warnings.append("AI returned an unusable structure; structural analysis used.")
        return base

    merged = merge_llm_result(base, parsed, request.knowledge_level)
    merged.source = result.provider
    merged.warnings.extend(base.warnings)
    return merged


async def analyze(
    document: ExtractedDocument, request: IntelligenceRequest
) -> StudyIntelligenceJSON:
    """Full pipeline: deterministic heuristics first, optional LLM refinement."""
    base = build_heuristic_intelligence(document, request)
    return await refine_with_llm(document, request, base)
