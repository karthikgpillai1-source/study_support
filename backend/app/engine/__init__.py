"""Study Intelligence Engine: documents in, structured study data out."""

from app.engine.extraction.extractors import (
    SUPPORTED_EXTENSIONS,
    ExtractedDocument,
    ExtractionError,
    extract,
    store_upload,
)
from app.engine.knowledge import (
    IntelligenceRequest,
    StudyIntelligenceJSON,
    analyze,
    build_heuristic_intelligence,
    refine_with_llm,
)
from app.engine.packages import (
    MAX_PACKAGE_MINUTES,
    PackagePlan,
    build_packages,
    split_minutes,
)
from app.engine.splits import SplitResult, generate_all

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "ExtractedDocument",
    "ExtractionError",
    "IntelligenceRequest",
    "MAX_PACKAGE_MINUTES",
    "PackagePlan",
    "SplitResult",
    "StudyIntelligenceJSON",
    "analyze",
    "build_heuristic_intelligence",
    "build_packages",
    "extract",
    "generate_all",
    "refine_with_llm",
    "split_minutes",
    "store_upload",
]
