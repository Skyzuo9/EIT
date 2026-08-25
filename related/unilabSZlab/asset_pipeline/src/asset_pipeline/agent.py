from __future__ import annotations

import base64
import io
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from .config import Settings
from .models import DeviceRecord, Dimensions, ResearchBundle, utc_now


VISUAL_QC_PROMPT_VERSION = "2026-07-16-layout-v2"


class AgentReview(BaseModel):
    selected_image_ids: list[str] = Field(default_factory=list, max_length=4)
    view_labels: dict[str, str] = Field(default_factory=dict)
    rejected: dict[str, str] = Field(default_factory=dict)
    reconstruction_scores: dict[str, float] = Field(default_factory=dict)
    identity_confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    dimensions: Dimensions | None = None


class GeneratedVisualReview(BaseModel):
    passed: bool
    similarity_score: float = Field(ge=0.0, le=1.0)
    summary: str
    issues: list[str] = Field(default_factory=list)
    provider: str
    model: str = ""
    prompt_version: str = VISUAL_QC_PROMPT_VERSION
    reviewed_at: str = Field(default_factory=utc_now)
    evidence_paths: list[str] = Field(default_factory=list)


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    raise ValueError("Agent response did not contain a JSON object")


def _fallback_review(bundle: ResearchBundle) -> AgentReview:
    selected = sorted(bundle.images, key=lambda image: image.score, reverse=True)[:4]
    return AgentReview(
        selected_image_ids=[image.id for image in selected],
        view_labels={
            image.id: f"candidate-{index + 1}" for index, image in enumerate(selected)
        },
        identity_confidence=max((image.score for image in selected), default=0.0),
        summary="Deterministic fallback ranking; Cursor Agent review was unavailable.",
        dimensions=bundle.dimensions,
    )


def _gemini_image(path: Path) -> str:
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _gemini_post(settings: Settings, payload: dict, purpose: str) -> dict:
    response: httpx.Response | None = None
    last_network_error: Exception | None = None
    for delay in (0, 10, 30, 60):
        if delay:
            time.sleep(delay)
        try:
            response = httpx.post(
                (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{settings.gemini_model}:generateContent"
                ),
                headers={"x-goog-api-key": settings.gemini_api_key},
                json=payload,
                timeout=180,
            )
        except httpx.HTTPError as error:
            last_network_error = error
            continue
        if response.status_code not in {429, 500, 502, 503, 504}:
            break
    if response is None:
        raise RuntimeError(f"Gemini {purpose} network failure: {last_network_error}")
    if response is None or response.is_error:
        status = response.status_code if response else "network"
        body = response.text[:1000] if response else "No response"
        raise RuntimeError(f"Gemini {purpose} {status}: {body}")
    return response.json()


def _review_with_gemini(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
) -> AgentReview:
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini is not configured")
    prompt = f"""
Act as a strict product-photogrammetry input reviewer.
Target instrument: {device.manufacturer_model}
Device type: {device.device_type}
Known dimensions: {bundle.dimensions.model_dump_json()}

Each following image is preceded by its candidate ID. Evaluate the actual pixels, not
the filename or search ranking. Reject wrong models, nearby variants, logos, brochures,
accessories, hands, tables, monitors, cables, close-ups, severe perspective, cropped
objects, and views that hide the overall silhouette.

For a single-image reconstruction, strongly prefer a clean full-object FRONT or mild
THREE-QUARTER product photo on a simple background. A side profile is not acceptable
when a clean front image exists. Select exactly one image by default. Select 2-4 only
when they clearly show the same physical configuration from complementary angles.
Assign reconstruction_scores based on expected 3D reconstruction fidelity, not image
resolution. All scores and identity_confidence must be numbers from 0 to 1.
Return JSON only.
"""
    parts: list[dict] = [{"text": prompt}]
    included: set[str] = set()
    for image in bundle.images:
        if not image.local_path or not Path(image.local_path).exists():
            continue
        included.add(image.id)
        parts.extend(
            [
                {
                    "text": (
                        f"Candidate ID: {image.id}\n"
                        f"Search title: {image.title}\n"
                        f"Source: {image.page_url or image.source_url}"
                    )
                },
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": _gemini_image(Path(image.local_path)),
                    }
                },
            ]
        )
    if not included:
        raise RuntimeError("No local candidate images are available")
    schema = {
        "type": "OBJECT",
        "properties": {
            "selected_image_ids": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "maxItems": 4,
            },
            "view_labels": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "id": {"type": "STRING"},
                        "label": {"type": "STRING"},
                    },
                    "required": ["id", "label"],
                },
            },
            "rejected": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "id": {"type": "STRING"},
                        "reason": {"type": "STRING"},
                    },
                    "required": ["id", "reason"],
                },
            },
            "reconstruction_scores": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "id": {"type": "STRING"},
                        "score": {
                            "type": "NUMBER",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": ["id", "score"],
                },
            },
            "identity_confidence": {
                "type": "NUMBER",
                "minimum": 0,
                "maximum": 1,
            },
            "summary": {"type": "STRING"},
        },
        "required": [
            "selected_image_ids",
            "view_labels",
            "rejected",
            "reconstruction_scores",
            "identity_confidence",
            "summary",
        ],
    }
    response_data = _gemini_post(
        settings,
        {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        },
        "candidate review",
    )
    candidates = response_data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    text = candidates[0]["content"]["parts"][0]["text"]
    raw = json.loads(text)
    review = AgentReview(
        selected_image_ids=raw.get("selected_image_ids", []),
        view_labels={item["id"]: item["label"] for item in raw.get("view_labels", [])},
        rejected={item["id"]: item["reason"] for item in raw.get("rejected", [])},
        reconstruction_scores={
            item["id"]: item["score"] for item in raw.get("reconstruction_scores", [])
        },
        identity_confidence=raw.get("identity_confidence", 0.0),
        summary=raw.get("summary", ""),
    )
    if not review.selected_image_ids or any(
        image_id not in included for image_id in review.selected_image_ids
    ):
        raise RuntimeError("Gemini selected invalid candidate IDs")
    return review


def _review_with_cursor(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
) -> AgentReview:
    if not settings.cursor_api_key:
        raise RuntimeError("Cursor Agent is not configured")

    manifest = {
        "device": device.model_dump(mode="json"),
        "research": bundle.model_dump(mode="json"),
    }
    manifest_path = settings.asset_dir(device.id) / "agent-input.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    prompt = f"""
You are reviewing image candidates for an exact laboratory instrument 3D reconstruction.
Read {manifest_path}. Inspect every local image path listed in the research bundle and
the downloaded PDF, text, and web-results files under the sibling evidence directory.
Do not edit any files and do not perform web searches.

Select 1 to 4 images that unquestionably depict the exact same manufacturer and model,
prefer complementary front/side/rear views, and reject collages, severe watermarks,
screenshots, low quality images, duplicate angles, accessories, and nearby model variants.
Do not select multiple images if exact identity is uncertain. Preserve supplied dimensions
unless the downloaded evidence contains stronger source-backed values. Any dimensions you
add must include the exact source URL and a confidence reflecting evidence quality.

Return only one JSON object matching:
{{
  "selected_image_ids": ["id"],
  "view_labels": {{"id": "front|side|rear|three-quarter"}},
  "rejected": {{"id": "reason"}},
  "identity_confidence": 0.0,
  "summary": "brief evidence-based summary",
  "dimensions": {{
    "width_mm": null, "depth_mm": null, "height_mm": null, "weight_kg": null,
    "source_url": null, "notes": "", "confidence": 0.0
  }}
}}
"""
    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=settings.cursor_api_key,
                model=settings.cursor_model,
                name=f"asset-review-{device.id[:32]}",
                local=LocalAgentOptions(
                    cwd=settings.asset_dir(device.id),
                    setting_sources=[],
                    sandbox_options={"enabled": True},
                ),
            ),
        )
        if str(result.status).casefold() not in {"finished", "success", "completed"}:
            raise RuntimeError(f"Cursor Agent run failed: {result.status}")
        return AgentReview.model_validate(_extract_json(result.result))
    except (CursorAgentError, ValueError, ValidationError) as error:
        raise RuntimeError("Cursor visual review failed") from error


def _review_with_codex_cli(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
) -> AgentReview:
    executable = shutil.which(settings.codex_cli_path)
    if not executable:
        raise RuntimeError(f"Codex CLI was not found: {settings.codex_cli_path}")
    images = [
        image
        for image in bundle.images
        if image.local_path and Path(image.local_path).exists()
    ]
    if not images:
        raise RuntimeError("No local candidate images are available")
    record_dir = settings.asset_dir(device.id) / "candidate-review"
    record_dir.mkdir(parents=True, exist_ok=True)
    schema_path = record_dir / "response-schema.json"
    result_path = record_dir / "codex-result.json"
    request_path = record_dir / "codex-request.json"
    run_path = record_dir / "codex-run.json"
    schema = {
        "type": "object",
        "properties": {
            "selected_image_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 4,
            },
            "view_labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["id", "label"],
                    "additionalProperties": False,
                },
            },
            "rejected": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "reason"],
                    "additionalProperties": False,
                },
            },
            "reconstruction_scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["id", "score"],
                    "additionalProperties": False,
                },
            },
            "identity_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "summary": {"type": "string"},
        },
        "required": [
            "selected_image_ids",
            "view_labels",
            "rejected",
            "reconstruction_scores",
            "identity_confidence",
            "summary",
        ],
        "additionalProperties": False,
    }
    candidate_lines = "\n".join(
        f"- ID {image.id}: {image.title}; source={image.page_url or image.source_url}; "
        f"file={image.local_path}"
        for image in images
    )
    prompt = f"""
Act as a strict product-image reviewer for exact-model 3D reconstruction.
Target: {device.manufacturer_model}
Device type: {device.device_type}

Inspect the attached local images. Match each attachment to its ID using the file path
listed below. Reject nearby models, other brands, collages, manuals, logos, accessories,
hands, tables, screenshots, severe crops, and duplicate angles. Select exactly one clean
full-object front or mild three-quarter view by default. Select 2-4 only when they depict
the same physical configuration from complementary views. Score reconstruction fitness,
not image resolution. Return only the required JSON.

Candidates:
{candidate_lines}
""".strip()
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    request_path.write_text(
        json.dumps(
            {
                "device_id": device.id,
                "manufacturer_model": device.manufacturer_model,
                "prompt": prompt,
                "candidate_ids": [image.id for image in images],
                "image_paths": [
                    str(Path(image.local_path or "").resolve()) for image in images
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    command = [
        executable,
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(result_path),
        "-C",
        str(settings.asset_dir(device.id)),
    ]
    if settings.codex_model:
        command.extend(["--model", settings.codex_model])
    for image in images:
        command.append(f"--image={Path(image.local_path or '').resolve()}")
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=settings.codex_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Codex candidate review timed out after {settings.codex_timeout_seconds}s"
        ) from error
    run_path.write_text(
        json.dumps(
            {
                "provider": "codex-cli",
                "model": settings.codex_model or "configured-default",
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
                "completed_at": utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Codex candidate review failed: {detail[-1000:]}")
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    included = {image.id for image in images}
    selected = raw.get("selected_image_ids", [])
    if not selected or any(image_id not in included for image_id in selected):
        raise RuntimeError("Codex selected invalid candidate IDs")
    return AgentReview(
        selected_image_ids=selected,
        view_labels={item["id"]: item["label"] for item in raw.get("view_labels", [])},
        rejected={item["id"]: item["reason"] for item in raw.get("rejected", [])},
        reconstruction_scores={
            item["id"]: item["score"] for item in raw.get("reconstruction_scores", [])
        },
        identity_confidence=raw.get("identity_confidence", 0.0),
        summary=raw.get("summary", ""),
    )


def review_with_vision_agent(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
) -> ResearchBundle:
    failures: list[str] = []
    if settings.candidate_review_provider.casefold().strip() == "codex":
        try:
            return apply_review(
                bundle, _review_with_codex_cli(settings, device, bundle)
            )
        except (RuntimeError, ValidationError, json.JSONDecodeError) as error:
            failures.append(f"Codex: {error}")
    if settings.gemini_api_key:
        try:
            return apply_review(bundle, _review_with_gemini(settings, device, bundle))
        except (httpx.HTTPError, RuntimeError, ValidationError) as error:
            failures.append(f"Gemini: {error}")
    if settings.cursor_api_key:
        try:
            return apply_review(bundle, _review_with_cursor(settings, device, bundle))
        except RuntimeError as error:
            failures.append(f"Cursor: {error}")
    if failures:
        raise RuntimeError(
            "All configured visual reviewers failed: " + " | ".join(failures)
        )
    review = _fallback_review(bundle)
    return apply_review(bundle, review)


def visual_qc_evidence(
    bundle: ResearchBundle, output_dir: Path
) -> tuple[list[Path], list[Path]]:
    references = [
        Path(image.local_path)
        for image in bundle.selected_images()
        if image.local_path and Path(image.local_path).exists()
    ]
    if not references:
        raise RuntimeError("Visual QC requires at least one approved reference image")
    preview_paths = [
        output_dir / "preview-front.png",
        output_dir / "preview-right.png",
        output_dir / "preview-back.png",
        output_dir / "preview-left.png",
    ]
    missing = [path.name for path in preview_paths if not path.exists()]
    if missing:
        raise RuntimeError(
            "Visual QC requires all four generated previews; missing: "
            + ", ".join(missing)
        )
    return references, preview_paths


def visual_qc_prompt(device: DeviceRecord, threshold: float) -> str:
    return f"""
Act as a layout-usability reviewer for a generated laboratory-equipment 3D asset.
Target exact manufacturer and model: {device.manufacturer_model}

The attached images contain approved product references followed by generated model
views named front, right, back, and left. This asset is intended for laboratory layout,
simulation placement, and recognizable visualization rather than manufacturing-grade
digital-twin reconstruction. Pass when the model is clearly the requested instrument,
its overall equipment category and major silhouette are recognizable, its recorded
real-world bounding dimensions are suitable, and it is a standalone usable asset.

Treat small dents, melted local details, uncertain rear details, imperfect labels,
minor panel/component displacement, and harmless texture projection as warnings rather
than failures. Fail only for a wrong or unrecognizable instrument, a wrong major
configuration, grossly wrong overall size, collapsed/missing main body, or substantial
unrelated furniture/accessories that make the target's scale or identity unusable.

Set passed=true only when similarity_score is at least {threshold:.2f} and there are no
blocking identity, scale, or standalone-asset issues. Return only the JSON object
required by the supplied schema.
""".strip()


def build_visual_qc_request(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
    output_dir: Path,
) -> dict:
    references, previews = visual_qc_evidence(bundle, output_dir)
    return {
        "schema_version": 1,
        "device_id": device.id,
        "manufacturer_model": device.manufacturer_model,
        "provider": settings.visual_qc_provider,
        "qc_profile": "layout_identity_scale",
        "similarity_threshold": settings.visual_similarity_threshold,
        "prompt_version": VISUAL_QC_PROMPT_VERSION,
        "prompt": visual_qc_prompt(device, settings.visual_similarity_threshold),
        "reference_images": [str(path.resolve()) for path in references],
        "generated_previews": [str(path.resolve()) for path in previews],
    }


def _review_generated_asset_with_codex(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
    output_dir: Path,
) -> GeneratedVisualReview:
    request = build_visual_qc_request(settings, device, bundle, output_dir)
    executable = shutil.which(settings.codex_cli_path)
    if not executable:
        raise RuntimeError(f"Codex CLI was not found: {settings.codex_cli_path}")

    record_dir = output_dir / "visual-qc"
    record_dir.mkdir(parents=True, exist_ok=True)
    schema_path = record_dir / "response-schema.json"
    result_path = record_dir / "codex-result.json"
    request_path = record_dir / "codex-request.json"
    run_path = record_dir / "codex-run.json"
    schema = {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "similarity_score": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string"},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["passed", "similarity_score", "summary", "issues"],
        "additionalProperties": False,
    }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    image_paths = request["reference_images"] + request["generated_previews"]
    command = [
        executable,
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(result_path),
        "-C",
        str(output_dir),
    ]
    if settings.codex_model:
        command.extend(["--model", settings.codex_model])
    for path in image_paths:
        command.append(f"--image={path}")

    try:
        completed = subprocess.run(
            command,
            input=request["prompt"],
            capture_output=True,
            text=True,
            timeout=settings.codex_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Codex visual QC timed out after {settings.codex_timeout_seconds}s"
        ) from error
    run_path.write_text(
        json.dumps(
            {
                "provider": "codex-cli",
                "model": settings.codex_model or "configured-default",
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
                "completed_at": utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Codex visual QC failed: {detail[-1000:]}")
    if not result_path.exists():
        raise RuntimeError("Codex visual QC did not write its structured result")

    raw = json.loads(result_path.read_text(encoding="utf-8"))
    score = float(raw.get("similarity_score", 0.0))
    passed = bool(raw.get("passed")) and score >= settings.visual_similarity_threshold
    return GeneratedVisualReview(
        passed=passed,
        similarity_score=score,
        summary=str(raw.get("summary", "")),
        issues=[str(issue) for issue in raw.get("issues", [])],
        provider="codex-cli",
        model=settings.codex_model or "configured-default",
        evidence_paths=image_paths,
    )


def _review_generated_asset_with_gemini(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
    output_dir: Path,
) -> GeneratedVisualReview:
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini visual QC is not configured")
    references, preview_paths = visual_qc_evidence(bundle, output_dir)
    parts: list[dict] = [
        {"text": visual_qc_prompt(device, settings.visual_similarity_threshold)}
    ]
    for path in references:
        parts.extend(
            [
                {"text": f"APPROVED REFERENCE {path.name}"},
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": _gemini_image(path),
                    }
                },
            ]
        )
    for path in preview_paths:
        parts.extend(
            [
                {"text": f"GENERATED MODEL VIEW {path.stem}"},
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": _gemini_image(path),
                    }
                },
            ]
        )
    schema = {
        "type": "OBJECT",
        "properties": {
            "passed": {"type": "BOOLEAN"},
            "similarity_score": {
                "type": "NUMBER",
                "minimum": 0,
                "maximum": 1,
            },
            "summary": {"type": "STRING"},
            "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["passed", "similarity_score", "summary", "issues"],
    }
    response_data = _gemini_post(
        settings,
        {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        },
        "visual QC",
    )
    candidates = response_data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini visual QC returned no candidates")
    raw = json.loads(candidates[0]["content"]["parts"][0]["text"])
    score = float(raw.get("similarity_score", 0.0))
    return GeneratedVisualReview(
        passed=bool(raw.get("passed"))
        and score >= settings.visual_similarity_threshold,
        similarity_score=score,
        summary=str(raw.get("summary", "")),
        issues=[str(issue) for issue in raw.get("issues", [])],
        provider="gemini",
        model=settings.gemini_model,
        evidence_paths=[str(path.resolve()) for path in references + preview_paths],
    )


def review_generated_asset(
    settings: Settings,
    device: DeviceRecord,
    bundle: ResearchBundle,
    output_dir: Path,
) -> GeneratedVisualReview:
    provider = settings.visual_qc_provider.casefold().strip()
    if provider == "codex":
        return _review_generated_asset_with_codex(settings, device, bundle, output_dir)
    if provider == "gemini":
        return _review_generated_asset_with_gemini(settings, device, bundle, output_dir)
    raise RuntimeError(f"Unsupported visual QC provider: {settings.visual_qc_provider}")


def apply_review(bundle: ResearchBundle, review: AgentReview) -> ResearchBundle:
    selected_ids = set(review.selected_image_ids)
    for image in bundle.images:
        image.selected = image.id in selected_ids
        image.view_label = review.view_labels.get(image.id, "")
        image.rejection_reason = review.rejected.get(image.id, "")
        image.reconstruction_score = max(
            0.0, min(1.0, review.reconstruction_scores.get(image.id, 0.0))
        )
    bundle.identity_confidence = review.identity_confidence
    bundle.agent_summary = review.summary
    if review.dimensions and (
        review.dimensions.complete or not bundle.dimensions.complete
    ):
        bundle.dimensions = review.dimensions
    return bundle
