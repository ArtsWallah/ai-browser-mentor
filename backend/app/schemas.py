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


class SecurityTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=15000)
    context: str = Field(default="selection", max_length=50)


class PageSummaryRequest(BaseModel):
    page_id: str = Field(min_length=1, max_length=256)


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
    error: str | None = None


class WorkspaceCompareRequest(BaseModel):
    workspace_name: str = Field(default="Default Workspace", max_length=256)
    focus_topic: str = Field(default="", max_length=1000)
    sources: list[WorkspaceSourceItem] = Field(default_factory=list)


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
    error: str | None = None