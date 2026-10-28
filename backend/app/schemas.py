from typing import Any
from pydantic import BaseModel, Field


class Link(BaseModel):
    text: str = ""
    url: str = ""


class Chunk(BaseModel):
    id: int = 0
    heading: str = ""
    text: str = ""
    source: str = ""
    title: str = ""
    wordCount: int = 0
    charCount: int = 0


class PageDocument(BaseModel):
    page_id: str = ""
    title: str = ""
    url: str = ""
    hostname: str = ""
    description: str = ""
    headings: list[str] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    content: str = ""
    wordCount: int = 0


class AssistantQueryRequest(BaseModel):
    query: str = Field(default="", max_length=2000)
    page_id: str = Field(default="", max_length=256)
    selection_text: str = Field(default="", max_length=15000)
    mode: str = Field(default="auto", max_length=50)
    privacy_mode: str = Field(default="hybrid", max_length=20)


class SecurityTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=15000)
    context: str = Field(default="selection", max_length=50)
    disabled_checks: list[str] = Field(default_factory=list)


class PageSummaryRequest(BaseModel):
    page_id: str = Field(min_length=1, max_length=256)
    disabled_checks: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    heading: str = ""
    quote: str = ""
    relevance_score: float = 0.0


class RiskAssessment(BaseModel):
    risk_level: str = "Low Risk"
    risk_score: int = 0
    findings: list[str] = Field(default_factory=list)
    disclaimer: str = ""


class CommandExecutionRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    intent: str = Field(default="auto", max_length=50)
    page_id: str = Field(default="", max_length=256)
    selection_text: str = Field(default="", max_length=15000)
    page_url: str = Field(default="", max_length=2048)
    page_title: str = Field(default="", max_length=512)
    privacy_mode: str = Field(default="hybrid", max_length=20)


class CommandExecutionResponse(BaseModel):
    success: bool = True
    intent: str = ""
    tool_name: str = ""
    action_summary: str = ""
    answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    risk_assessment: RiskAssessment | None = None
    limitations: str = ""
    provider: str = ""
    privacy_mode_applied: str = "hybrid"
    page_state: str = "ready"
    error: str | None = None


# ============================================================
# PHASE 3: RESEARCH WORKSPACE SCHEMAS
# ============================================================

class WorkspaceSourceItem(BaseModel):
    id: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=512)
    url: str = Field(default="", max_length=2048)
    hostname: str = Field(default="", max_length=256)
    collected_at: str = Field(default="", max_length=64)
    text: str = Field(default="", max_length=30000)
    excerpt: str = Field(default="", max_length=1000)
    headings: list[str] = Field(default_factory=list)


class WorkspaceCitation(BaseModel):
    source_id: str = ""
    source_title: str = ""
    url: str = ""
    quote: str = ""
    relevance_score: float = 0.0


class WorkspaceQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    workspace_name: str = Field(default="Default Workspace", max_length=256)
    sources: list[WorkspaceSourceItem] = Field(default_factory=list)
    top_k: int = Field(default=6, ge=1, le=20)
    privacy_mode: str = Field(default="hybrid", max_length=20)


class WorkspaceQueryResponse(BaseModel):
    success: bool = True
    workspace_name: str = ""
    query: str = ""
    answer: str = ""
    key_findings: list[str] = Field(default_factory=list)
    citations: list[WorkspaceCitation] = Field(default_factory=list)
    insufficient_evidence: bool = False
    limitations: str = ""
    provider: str = ""
    privacy_mode_applied: str = "hybrid"
    error: str | None = None


class WorkspaceCompareRequest(BaseModel):
    workspace_name: str = Field(default="Default Workspace", max_length=256)
    focus_topic: str = Field(default="", max_length=1000)
    sources: list[WorkspaceSourceItem] = Field(default_factory=list)
    privacy_mode: str = Field(default="hybrid", max_length=20)


class WorkspaceCompareResponse(BaseModel):
    success: bool = True
    workspace_name: str = ""
    focus_topic: str = ""
    comparison_summary: str = ""
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)
    citations: list[WorkspaceCitation] = Field(default_factory=list)
    limitations: str = ""
    provider: str = ""
    privacy_mode_applied: str = "hybrid"
    error: str | None = None


# ============================================================
# PHASE 4: HYBRID AI ENGINE & PRIVACY ROUTING SCHEMAS
# ============================================================

class ModelCapabilityInfo(BaseModel):
    id: str
    name: str
    provider: str
    is_local: bool
    supported_tasks: list[str] = Field(default_factory=list)
    is_configured: bool = True
    is_available: bool = True
    status_message: str = "Ready"
    max_context_chars: int = 8000
    privacy_level: str = "local_only"


class ModelRegistryResponse(BaseModel):
    success: bool = True
    active_privacy_modes: list[str] = Field(default_factory=lambda: ["hybrid", "local_only", "cloud"])
    default_privacy_mode: str = "hybrid"
    current_privacy_mode: str = "hybrid"
    models: list[ModelCapabilityInfo] = Field(default_factory=list)
    local_llm_detected: bool = False
    local_llm_url: str = ""
    cloud_configured: bool = False


# ============================================================
# EXPLAINABLE SCAMSHIELD SCHEMAS
# ============================================================

class ScamShieldEvidenceSpan(BaseModel):
    text: str
    start: int
    end: int
    feature: str
    weight: float
    contribution: float


class ScamShieldTopFeature(BaseModel):
    feature: str
    weight: float
    contribution: float
    tfidf_value: float = 0.0


class ScamShieldTacticFinding(BaseModel):
    tactic: str
    available: bool = True
    detected: bool | None = False
    score: float | None = None
    threshold: float | None = 0.5
    evidence_spans: list[ScamShieldEvidenceSpan] = Field(default_factory=list)
    top_features: list[ScamShieldTopFeature] = Field(default_factory=list)
    explanation: str = ""
    explanation_method: str = "linear_feature_attribution"
    uncertainty_note: str = ""


class ScamShieldAnalysisResponse(BaseModel):
    success: bool = True
    model: str = "scamshield-tfidf-multilabel"
    experimental: bool = True
    detected_tactics: list[str] = Field(default_factory=list)
    results: list[ScamShieldTacticFinding] = Field(default_factory=list)
    tactic_findings: list[ScamShieldTacticFinding] = Field(default_factory=list)
    explanation_method: str = "linear_feature_attribution"
    explanation_limitations: str = ""
    calibrated_probability_note: str = ""
    disclaimer: str = ""


# ============================================================
# PHASE 5: EMERGING PATTERN DISCOVERY SCHEMAS
# ============================================================

class DiscoveryRunRequest(BaseModel):
    """
    Request to run the emerging-pattern discovery pipeline on provided text examples.
    For batch research use only — not called on every browser request.
    """
    examples: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of {id, message, source, external_label} dicts. "
                    "At minimum each must have a 'message' key.",
    )
    novelty_threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Cosine-distance threshold above which a point is flagged as "
                    "semantically distant from all known tactic prototypes.",
    )
    min_cluster_size: int = Field(
        default=3, ge=2, le=50
    )
    max_rows: int | None = Field(
        default=None,
        description="Optional row limit (for testing / sampling).",
    )


class PatternEntry(BaseModel):
    cluster_id: str
    n_examples: int
    novelty_score: float
    associated_tactics: list[str] = Field(default_factory=list)
    tactic_confidence: str = ""
    review_status: str = "pending"
    medoid_message: str = ""
    medoid_source: str = ""
    shared_ngrams: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    import_timestamp: str = ""
    source_provenance: list[str] = Field(default_factory=list)


class DiscoveryRunResponse(BaseModel):
    success: bool = True
    n_ingested: int = 0
    n_deduplicated: int = 0
    n_clusters: int = 0
    n_noise_points: int = 0
    n_high_novelty_candidates: int = 0
    embedding_model: str = ""
    embedding_available: bool = False
    algorithm_primary: str = ""
    silhouette_primary: float | None = None
    silhouette_baseline: float | None = None
    n_imported_to_registry: int = 0
    registry_total: int = 0
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "All discovered patterns are candidates for human review only. "
        "No pattern has been confirmed as a new scam type. "
        "Temporal emergence cannot be established without timestamps."
    )
    error: str | None = None


class PatternListResponse(BaseModel):
    success: bool = True
    total: int = 0
    status_filter: str | None = None
    patterns: list[PatternEntry] = Field(default_factory=list)


class PatternReviewRequest(BaseModel):
    pattern_id: str
    status: str = Field(
        description="One of: pending | known | potentially_novel | benign | inconclusive"
    )
    reviewer: str = Field(default="anonymous", max_length=128)
    rationale: str = Field(default="", max_length=2000)