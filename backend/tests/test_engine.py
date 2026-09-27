"""Study Intelligence Engine: extraction, structuring, scoring, packaging."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.enums import Difficulty, KnowledgeLevel, StudyMode
from app.engine import packages as pkg
from app.engine.extraction.extractors import (
    ExtractionError,
    extract,
    normalize_text,
)
from app.engine.knowledge import IntelligenceRequest, build_heuristic_intelligence
from tests.conftest import SAMPLE_NOTES


# ------------------------------------------------------------------------ extraction
def test_txt_extraction_roundtrip() -> None:
    doc = extract("notes.txt", SAMPLE_NOTES.encode("utf-8"))
    assert doc.extractor == "native"
    assert "Operating Systems" in doc.text
    assert doc.word_count > 200
    assert doc.page_count >= 1


def test_docx_extraction(tmp_path) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Photosynthesis", level=1)
    document.add_paragraph("Photosynthesis is defined as the process plants use light.")
    document.add_paragraph("Step 1: absorb light energy.")
    document.save(tmp_path / "bio.docx")

    doc = extract("bio.docx", (tmp_path / "bio.docx").read_bytes())
    assert doc.extractor == "python-docx"
    assert "Photosynthesis" in doc.text
    assert "absorb light energy" in doc.text


def test_pdf_extraction() -> None:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Thermodynamics: the first law of thermodynamics")
    page.insert_text((72, 100), "Energy is defined as the capacity to do work.")
    data = doc.tobytes()
    doc.close()

    extracted = extract("thermo.pdf", data)
    assert extracted.extractor == "pymupdf"
    assert "Thermodynamics" in extracted.text
    assert extracted.page_count == 1


def test_unsupported_and_empty_uploads() -> None:
    with pytest.raises(ExtractionError, match="Unsupported file type"):
        extract("notes.pptx", b"junk")
    with pytest.raises(ExtractionError, match="empty"):
        extract("notes.txt", b"")
    with pytest.raises(ExtractionError, match="not supported"):
        extract("old.doc", b"junk")


def test_normalize_text_fixes_typographic_noise() -> None:
    raw = "Caf\u00e9\u00a0cost\u2009is \ufb00ast.\r\n\r\n\r\n\u2022 Next item"
    cleaned = normalize_text(raw)
    assert "\ufb00" not in cleaned
    assert "\u00a0" not in cleaned
    assert cleaned.count("\n\n") == 1
    assert "* Next item" in cleaned


# ------------------------------------------------------------------ knowledge stage
def _request(level: KnowledgeLevel = KnowledgeLevel.BEGINNER) -> IntelligenceRequest:
    return IntelligenceRequest(
        subject_name="Operating Systems",
        knowledge_level=level,
        study_mode=StudyMode.FAST_EXAM,
        exam_date=date.today() + timedelta(days=14),
        use_llm=False,
    )


def test_heuristic_intelligence_produces_structured_topics() -> None:
    document = extract("notes.txt", SAMPLE_NOTES.encode("utf-8"))
    result = build_heuristic_intelligence(document, _request())

    assert result.topics, "expected at least one topic"
    assert result.total_minutes == sum(t.estimated_minutes for t in result.topics)
    assert result.keywords, "expected keywords"
    assert 0.0 < result.confidence <= 0.95
    assert result.source == "heuristic"

    for topic in result.topics:
        assert topic.title.strip()
        assert topic.difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD)
        assert 5 <= topic.estimated_minutes <= 180
        assert 5 <= topic.revision_minutes <= 60
        assert 0.05 <= topic.importance <= 1.0


def test_definitions_and_procedures_are_mined() -> None:
    document = extract("notes.txt", SAMPLE_NOTES.encode("utf-8"))
    result = build_heuristic_intelligence(document, _request())
    all_definitions = " ".join(d for t in result.topics for d in t.definitions).lower()
    assert "defined as" in all_definitions
    assert any(t.procedures for t in result.topics)
    assert result.formulas, "expected at least one formula"


def test_harder_content_scores_harder_than_glossaries() -> None:
    glossary = (
        "A CPU is the central processing unit. "
        "The ALU performs arithmetic. "
        "The register holds a value. "
        "The cache stores data close to the processor. "
        "The bus connects components. "
    ) * 6
    technical = (
        "The theorem states that every convergent metric space is complete. "
        "Proof: take a Cauchy sequence and show it converges to a point in the set. "
        "This derivation requires the generalized spectral decomposition of the "
        "operator, and convergence is asymptotic. "
    ) * 6

    easy = build_heuristic_intelligence(extract("g.txt", glossary.encode()), _request())
    hard = build_heuristic_intelligence(extract("t.txt", technical.encode()), _request())

    easy_score = max(t.difficulty_score for t in easy.topics)
    hard_score = max(t.difficulty_score for t in hard.topics)
    assert hard_score > easy_score
    assert Difficulty.HARD in {t.difficulty for t in hard.topics}


def test_knowledge_level_shifts_estimates() -> None:
    document = extract("notes.txt", SAMPLE_NOTES.encode("utf-8"))
    novice = build_heuristic_intelligence(document, _request(KnowledgeLevel.NOVICE))
    expert = build_heuristic_intelligence(document, _request(KnowledgeLevel.EXPERT))
    assert novice.total_minutes > expert.total_minutes


def test_analysis_is_deterministic() -> None:
    document = extract("notes.txt", SAMPLE_NOTES.encode("utf-8"))
    first = build_heuristic_intelligence(document, _request())
    second = build_heuristic_intelligence(extract("notes.txt", SAMPLE_NOTES.encode()), _request())
    assert [t.title for t in first.topics] == [t.title for t in second.topics]
    assert [t.estimated_minutes for t in first.topics] == [
        t.estimated_minutes for t in second.topics
    ]
    assert first.total_minutes == second.total_minutes


# ------------------------------------------------------------------------ packaging
def _package_topic(index: int, minutes: int) -> pkg.PackageTopic:
    return pkg.PackageTopic(
        id=index,
        title=f"Topic {index}",
        module_title=f"Module {index // 3}",
        difficulty=Difficulty.MEDIUM,
        minutes=minutes,
        revision_minutes=10,
        importance=0.5,
    )


def test_no_package_exceeds_ninety_minutes() -> None:
    topics = [_package_topic(i, 40) for i in range(12)]
    plans = pkg.build_packages(topics)
    assert plans
    for plan in plans:
        assert plan.minutes <= pkg.MAX_PACKAGE_MINUTES, f"{plan.title} is {plan.minutes} min"


def test_every_study_unit_is_ten_to_thirty_minutes() -> None:
    topics = [_package_topic(i, 45) for i in range(10)]
    for plan in pkg.build_packages(topics):
        for unit in plan.units:
            assert pkg.MIN_UNIT_MINUTES <= unit.minutes <= pkg.MAX_UNIT_MINUTES


def test_packages_stay_within_a_module_when_possible() -> None:
    topics = [_package_topic(i, 20) for i in range(9)]
    for bucket in pkg.group_topics(topics, max_minutes=90):
        modules = {t.module_title for t in bucket}
        assert len(modules) == 1


def test_revision_packages_mirror_study_packages() -> None:
    topics = [_package_topic(i, 35) for i in range(6)]
    plans = pkg.build_packages(topics, include_revision=True)
    study = [p for p in plans if p.type.value == "study"]
    revision = [p for p in plans if p.type.value == "revision"]
    assert len(study) == len(revision)
    for plan in revision:
        assert plan.title.startswith("Revise:")


def test_split_minutes_respects_block_bounds_and_total() -> None:
    for total in (10, 25, 30, 47, 90, 130, 240):
        blocks = pkg.split_minutes(total)
        assert sum(blocks) == total or (total > 0 and abs(sum(blocks) - total) <= 10)
        for value in blocks:
            assert pkg.MIN_UNIT_MINUTES <= value <= pkg.MAX_UNIT_MINUTES


def test_split_minutes_edge_cases() -> None:
    assert pkg.split_minutes(0) == []
    assert pkg.split_minutes(5) == [10]  # never schedule an invalid short block
    assert pkg.split_minutes(1000) == [] or sum(pkg.split_minutes(1000)) == 1000
