from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class WorkflowStatus(StrEnum):
    IMPORTED = "imported"
    RESEARCHING = "researching"
    AWAITING_RESEARCH_APPROVAL = "awaiting_research_approval"
    RESEARCH_APPROVED = "research_approved"
    AWAITING_GENERATION_APPROVAL = "awaiting_generation_approval"
    GENERATION_APPROVED = "generation_approved"
    GENERATING = "generating"
    AWAITING_FINAL_APPROVAL = "awaiting_final_approval"
    APPROVED = "approved"
    REUSE_REVIEW = "reuse_review"
    MANUAL = "manual"
    FAILED = "failed"


class DeviceRecord(BaseModel):
    id: str
    source_row: int
    source_kind: str = "workbook"
    source_path: str = ""
    source_key: str = ""
    record_type: str
    device_group: str = ""
    device_type: str = ""
    manufacturer_model: str
    preparation_status: str
    model_status: str = ""
    parameters: str = ""
    model_availability: str = ""
    model_evidence: str = ""
    repository_link: str = ""
    official_links: list[str] = Field(default_factory=list)
    adaptation_advice: str = ""
    structured_dimensions: str = ""
    route: str


class Dimensions(BaseModel):
    width_mm: float | None = None
    depth_mm: float | None = None
    height_mm: float | None = None
    weight_kg: float | None = None
    source_url: str | None = None
    notes: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def complete(self) -> bool:
        return all(
            value and value > 0
            for value in (self.width_mm, self.depth_mm, self.height_mm)
        )


class CandidateImage(BaseModel):
    id: str
    source_url: str
    page_url: str = ""
    title: str = ""
    source_name: str = ""
    search_provider: str = ""
    local_path: str | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reconstruction_score: float = Field(default=0.0, ge=0.0, le=1.0)
    selected: bool = False
    rejection_reason: str = ""
    view_label: str = ""


class ResearchBundle(BaseModel):
    device_id: str
    query_terms: list[str] = Field(default_factory=list)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    images: list[CandidateImage] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)
    agent_summary: str = ""
    identity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=utc_now)

    def selected_images(self) -> list[CandidateImage]:
        return [image for image in self.images if image.selected and image.local_path]


class MeshyTask(BaseModel):
    device_id: str
    task_id: str
    api_endpoint: str = "multi-image-to-3d"
    status: str
    consumed_credits: int = 0
    model_url: str | None = None
    thumbnail_url: str | None = None
    error: str = ""
    raw: dict = Field(default_factory=dict)
    updated_at: str = Field(default_factory=utc_now)


class QCReport(BaseModel):
    device_id: str
    source_glb: str
    final_glb: str | None = None
    loadable: bool = False
    has_materials: bool = False
    has_textures: bool = False
    vertices: int = 0
    faces: int = 0
    source_extents: list[float] = Field(default_factory=list)
    axis_mapping: str = "xyz"
    final_extents_m: list[float] = Field(default_factory=list)
    target_extents_m: list[float] = Field(default_factory=list)
    proportion_error: float | None = None
    geometry_pass: bool = False
    visual_required: bool = True
    visual_similarity_score: float | None = None
    visual_pass: bool | None = None
    visual_provider: str = ""
    visual_model: str = ""
    visual_prompt_version: str = ""
    visual_reviewed_at: str | None = None
    visual_evidence_paths: list[str] = Field(default_factory=list)
    visual_notes: str = ""
    visual_issues: list[str] = Field(default_factory=list)
    visual_error: str = ""
    passed: bool = False
    warnings: list[str] = Field(default_factory=list)
    checked_at: str = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_geometry_result(cls, value):
        if isinstance(value, dict) and "geometry_pass" not in value:
            value = dict(value)
            value["geometry_pass"] = bool(value.get("passed", False))
        return value


class Approval(BaseModel):
    device_id: str
    gate: str
    decision: str
    note: str = ""
    reviewer: str = ""
    override_qc: bool = False
    decided_at: str = Field(default_factory=utc_now)


class ArtifactManifest(BaseModel):
    device: DeviceRecord
    research: ResearchBundle | None = None
    meshy_task: MeshyTask | None = None
    qc: QCReport | None = None
    approvals: list[Approval] = Field(default_factory=list)
    final_glb: Path | None = None
    updated_at: str = Field(default_factory=utc_now)
