from __future__ import annotations

import csv
import hashlib
import math
import re
import shutil
from pathlib import Path

import trimesh
from PIL import Image

from .agent import (
    GeneratedVisualReview,
    build_visual_qc_request,
    review_generated_asset,
    review_with_vision_agent,
)
from .config import Settings
from .meshy import MeshyClient
from .models import (
    Approval,
    CandidateImage,
    Dimensions,
    MeshyTask,
    QCReport,
    WorkflowStatus,
)
from .qc import normalize_and_check_glb, write_manifest
from .research import ImageResearcher
from .state import StateStore
from .workbook import (
    import_coverage_csv,
    import_devices,
    write_coverage_results,
    write_results,
)


class PipelineError(RuntimeError):
    pass


class AssetPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = StateStore(settings.database_path)

    def bootstrap(self) -> tuple[int, int]:
        devices, _ = import_devices(self.settings.workbook_path)
        self.store.upsert_devices(devices)
        generated = sum(device.route == "needs_generation" for device in devices)
        reused = sum(device.route == "reuse_existing" for device in devices)
        self.store.set_metadata("source_workbook", str(self.settings.workbook_path))
        return generated, reused

    def import_coverage(self, path: Path) -> tuple[int, int]:
        devices, _ = import_coverage_csv(path)
        self.store.upsert_devices(devices)
        generation = sum(device.route == "needs_generation" for device in devices)
        manual = sum(device.route == "manual_identification" for device in devices)
        self.store.set_metadata("coverage_csv", str(path.resolve()))
        return generation, manual

    def research_device(self, device_id: str) -> None:
        device = self.store.get_device(device_id)
        self.store.set_status(device_id, WorkflowStatus.RESEARCHING)
        try:
            with ImageResearcher(self.settings) as researcher:
                bundle = researcher.research(device)
            bundle = review_with_vision_agent(self.settings, device, bundle)
            self.store.save_research(bundle)
            self.store.set_status(device_id, WorkflowStatus.AWAITING_RESEARCH_APPROVAL)
            self._write_manifest(device_id)
        except Exception:
            self.store.set_status(device_id, WorkflowStatus.FAILED)
            raise

    def approve_research(self, device_id: str, note: str = "") -> None:
        bundle = self.store.get_research(device_id)
        if not bundle or not 1 <= len(bundle.selected_images()) <= 4:
            raise PipelineError(
                "Select 1 to 4 downloaded images before approving research"
            )
        if bundle.identity_confidence < self.settings.research_identity_threshold:
            raise PipelineError(
                f"Identity confidence {bundle.identity_confidence:.2f} is below "
                f"{self.settings.research_identity_threshold:.2f}"
            )
        if not bundle.dimensions.complete or not bundle.dimensions.source_url:
            raise PipelineError(
                "Verified width/depth/height and a dimension source URL are required"
            )
        self.store.add_approval(
            Approval(
                device_id=device_id, gate="research", decision="approved", note=note
            )
        )
        self.store.set_status(device_id, WorkflowStatus.AWAITING_GENERATION_APPROVAL)
        self._write_manifest(device_id)

    def reject_research(self, device_id: str, note: str) -> None:
        self.store.add_approval(
            Approval(
                device_id=device_id, gate="research", decision="rejected", note=note
            )
        )
        self.store.set_status(device_id, WorkflowStatus.IMPORTED)

    def approve_generation(self, device_ids: list[str], note: str = "") -> int:
        expected_credits = len(device_ids) * 30
        if expected_credits > self.settings.max_batch_credits:
            raise PipelineError(
                f"Expected {expected_credits} credits exceeds configured batch cap "
                f"{self.settings.max_batch_credits}"
            )
        statuses = {device.id: status for device, status in self.store.list_devices()}
        for device_id in device_ids:
            if statuses.get(device_id) != WorkflowStatus.AWAITING_GENERATION_APPROVAL:
                raise PipelineError(f"{device_id} is not awaiting generation approval")
            bundle = self.store.get_research(device_id)
            if not bundle or not 1 <= len(bundle.selected_images()) <= 4:
                raise PipelineError(f"{device_id} has no approved research bundle")
            if not bundle.dimensions.complete or not bundle.dimensions.source_url:
                raise PipelineError(
                    f"{device_id} has no source-backed width/depth/height dimensions"
                )
        for device_id in device_ids:
            self.store.add_approval(
                Approval(
                    device_id=device_id,
                    gate="generation",
                    decision="approved",
                    note=note,
                )
            )
            self.store.set_status(device_id, WorkflowStatus.GENERATION_APPROVED)
        return expected_credits

    def set_dimensions(
        self,
        device_id: str,
        width_mm: float,
        depth_mm: float,
        height_mm: float,
        source_url: str,
        note: str = "",
    ) -> Dimensions:
        if min(width_mm, depth_mm, height_mm) <= 0 or not source_url.startswith(
            ("http://", "https://")
        ):
            raise PipelineError(
                "Positive dimensions and an HTTP(S) source URL are required"
            )
        bundle = self.store.get_research(device_id)
        if not bundle:
            raise PipelineError(f"No research bundle for {device_id}")
        bundle.dimensions = Dimensions(
            width_mm=width_mm,
            depth_mm=depth_mm,
            height_mm=height_mm,
            source_url=source_url,
            notes=note,
            confidence=0.95,
        )
        self.store.save_research(bundle)
        self._write_manifest(device_id)
        return bundle.dimensions

    def add_reference_image(
        self,
        device_id: str,
        source_path: Path,
        source_url: str,
        page_url: str = "",
        title: str = "",
        view_label: str = "",
        replace_selected: bool = False,
    ) -> CandidateImage:
        """Import an inspected exact-model image into the research audit trail."""
        bundle = self.store.get_research(device_id)
        if not bundle:
            raise PipelineError(f"No research bundle for {device_id}")
        source_path = source_path.expanduser().resolve()
        if not source_path.is_file():
            raise PipelineError(f"Reference image does not exist: {source_path}")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        suffix = source_path.suffix.lower() or ".jpg"
        destination = (
            self.settings.asset_dir(device_id)
            / "candidates"
            / f"manual-{digest[:10]}{suffix}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source_path, destination)
        with Image.open(destination) as image:
            width, height = image.size
        if replace_selected:
            for existing in bundle.images:
                existing.selected = False
        candidate = CandidateImage(
            id=digest[:16],
            source_url=source_url,
            page_url=page_url,
            title=title,
            source_name="manual_exact_model_reference",
            search_provider="manual_import",
            local_path=str(destination),
            sha256=digest,
            width=width,
            height=height,
            score=1.0,
            reconstruction_score=0.9,
            selected=True,
            view_label=view_label,
        )
        bundle.images = [image for image in bundle.images if image.sha256 != digest]
        bundle.images.append(candidate)
        if source_url and source_url not in bundle.evidence_urls:
            bundle.evidence_urls.append(source_url)
        self.store.save_research(bundle)
        self._write_manifest(device_id)
        return candidate

    def generate_device(self, device_id: str) -> MeshyTask:
        bundle = self.store.get_research(device_id)
        if not bundle:
            raise PipelineError(f"No research bundle for {device_id}")
        self.store.set_status(device_id, WorkflowStatus.GENERATING)
        existing = self.store.get_meshy_task(device_id)
        try:
            with MeshyClient(self.settings) as client:
                if (
                    existing
                    and existing.task_id
                    and existing.status not in {"FAILED", "CANCELED"}
                ):
                    task = client.get_task(
                        device_id, existing.task_id, existing.api_endpoint
                    )
                else:
                    task = client.create_task(bundle)
                    self.store.save_meshy_task(task)
                if task.status not in MeshyClient.TERMINAL_STATUSES:
                    task = client.wait_for_task(
                        device_id, task.task_id, task.api_endpoint
                    )
                self.store.save_meshy_task(task)
                if task.status != "SUCCEEDED":
                    self.store.set_status(device_id, WorkflowStatus.FAILED)
                    return task
                output_dir = self.settings.asset_dir(device_id) / "output"
                source_glb = client.download_outputs(task, output_dir)
            final_glb = output_dir / "final.glb"
            report = normalize_and_check_glb(
                device_id,
                source_glb,
                final_glb,
                bundle.dimensions,
            )
            report.visual_required = self.settings.visual_qc_required
            if self.settings.visual_qc_required:
                try:
                    visual_review = review_generated_asset(
                        self.settings,
                        self.store.get_device(device_id),
                        bundle,
                        output_dir,
                    )
                    self._apply_visual_review(report, visual_review)
                except Exception as error:
                    report.visual_pass = False
                    report.visual_provider = self.settings.visual_qc_provider
                    report.visual_error = str(error)
                    report.visual_issues = []
                    report.visual_notes = f"Visual QC failed to run: {error}"
                    report.passed = False
            else:
                report.visual_provider = "disabled"
                report.visual_notes = (
                    "Visual QC was explicitly disabled by configuration."
                )
                report.passed = report.geometry_pass
            self.store.save_qc(report)
            self.store.set_status(device_id, WorkflowStatus.AWAITING_FINAL_APPROVAL)
            self._write_manifest(device_id)
            return task
        except Exception:
            self.store.set_status(device_id, WorkflowStatus.FAILED)
            raise

    def prepare_generation_retry(self, device_id: str, note: str = "") -> int:
        task = self.store.get_meshy_task(device_id)
        report = self.store.get_qc(device_id)
        bundle = self.store.get_research(device_id)
        if not task or not report or report.passed:
            raise PipelineError(f"{device_id} has no failed generated asset to retry")
        if not bundle or not bundle.dimensions.complete or not bundle.selected_images():
            raise PipelineError(f"{device_id} has incomplete retry evidence")
        retry_prefix = "meshy_task_retry_"
        prior_retries = sum(
            kind.startswith(retry_prefix)
            for kind in self.store.list_artifact_kinds(device_id)
        )
        retry_number = prior_retries + 1
        if retry_number > self.settings.max_retry_per_device:
            raise PipelineError(
                f"{device_id} exceeds max retry count "
                f"({self.settings.max_retry_per_device})"
            )
        self.store.save_artifact(device_id, f"meshy_task_retry_{retry_number}", task)
        self.store.save_artifact(device_id, f"qc_retry_{retry_number}", report)
        self.store.delete_artifact(device_id, "meshy_task")
        self.store.delete_artifact(device_id, "qc")
        self.store.add_approval(
            Approval(
                device_id=device_id,
                gate=f"generation_retry_{retry_number}",
                decision="approved",
                note=note,
            )
        )
        self.store.set_status(device_id, WorkflowStatus.GENERATION_APPROVED)
        self._write_manifest(device_id)
        return retry_number

    def visual_qc_request(self, device_id: str) -> dict:
        bundle = self.store.get_research(device_id)
        if not bundle:
            raise PipelineError(f"No research bundle for {device_id}")
        output_dir = self.settings.asset_dir(device_id) / "output"
        return build_visual_qc_request(
            self.settings,
            self.store.get_device(device_id),
            bundle,
            output_dir,
        )

    def run_visual_qc(self, device_id: str) -> QCReport:
        bundle = self.store.get_research(device_id)
        report = self.store.get_qc(device_id)
        if not bundle or not report:
            raise PipelineError(
                f"Research and geometry QC are required for {device_id}"
            )
        output_dir = self.settings.asset_dir(device_id) / "output"
        try:
            review = review_generated_asset(
                self.settings,
                self.store.get_device(device_id),
                bundle,
                output_dir,
            )
            self._apply_visual_review(report, review)
        except Exception as error:
            report.visual_required = True
            report.visual_pass = False
            report.visual_provider = self.settings.visual_qc_provider
            report.visual_error = str(error)
            report.visual_issues = []
            report.visual_notes = f"Visual QC failed to run: {error}"
            report.passed = False
        self.store.save_qc(report)
        self._record_visual_decision(device_id, report)
        self._write_manifest(device_id)
        return report

    def record_visual_qc(
        self, device_id: str, review: GeneratedVisualReview
    ) -> QCReport:
        report = self.store.get_qc(device_id)
        if not report:
            raise PipelineError(f"Geometry QC is required for {device_id}")
        self._apply_visual_review(report, review)
        self.store.save_qc(report)
        self._record_visual_decision(device_id, report)
        self._write_manifest(device_id)
        return report

    def _record_visual_decision(self, device_id: str, report: QCReport) -> None:
        self.store.add_approval(
            Approval(
                device_id=device_id,
                gate="visual_qc",
                decision="approved" if report.visual_pass else "rejected",
                note=report.visual_notes or report.visual_error,
                reviewer=report.visual_provider,
            )
        )
        if not report.passed:
            self.store.set_status(device_id, WorkflowStatus.AWAITING_FINAL_APPROVAL)

    def _apply_visual_review(
        self, report: QCReport, review: GeneratedVisualReview
    ) -> None:
        threshold = self.settings.visual_similarity_threshold
        if report.geometry_pass:
            # Older records stored visual findings in the generic warning list.
            # A successful geometry pass has no geometry warnings to preserve.
            report.warnings = []
        report.visual_required = True
        report.visual_similarity_score = review.similarity_score
        report.visual_pass = review.passed and review.similarity_score >= threshold
        report.visual_provider = review.provider
        report.visual_model = review.model
        report.visual_prompt_version = review.prompt_version
        report.visual_reviewed_at = review.reviewed_at
        report.visual_evidence_paths = review.evidence_paths
        report.visual_notes = review.summary
        report.visual_issues = list(review.issues)
        report.visual_error = ""
        report.passed = report.geometry_pass and bool(report.visual_pass)

    def approve_final(
        self, device_id: str, note: str = "", override_qc: bool = False
    ) -> None:
        qc = self.store.get_qc(device_id)
        task = self.store.get_meshy_task(device_id)
        if task is not None and (not qc or not qc.passed) and not override_qc:
            raise PipelineError(
                "Automatic QC did not pass; use an explicit override to approve"
            )
        self.store.add_approval(
            Approval(
                device_id=device_id,
                gate="final",
                decision="approved",
                note=note,
                reviewer="human",
                override_qc=override_qc,
            )
        )
        self.store.set_status(device_id, WorkflowStatus.APPROVED)
        self.publish_approved_asset(device_id)
        self._write_manifest(device_id)

    def retry_generation(self, device_id: str, note: str) -> None:
        retries = sum(
            approval.gate == "final" and approval.decision == "retry"
            for approval in self.store.list_approvals(device_id)
        )
        if retries >= self.settings.max_retry_per_device:
            raise PipelineError("Configured per-device retry limit has been reached")
        self.store.add_approval(
            Approval(device_id=device_id, gate="final", decision="retry", note=note)
        )
        with self.store.connect() as db:
            db.execute(
                "DELETE FROM artifacts WHERE device_id=? AND kind IN ('meshy_task', 'qc')",
                (device_id,),
            )
        self.store.set_status(device_id, WorkflowStatus.AWAITING_GENERATION_APPROVAL)

    def export_results(self) -> Path:
        for device, status in self.store.list_devices():
            if status == WorkflowStatus.APPROVED:
                self.publish_approved_asset(device.id)
            self._write_manifest(device.id)
        return write_results(
            self.settings.workbook_path,
            self.settings.output_workbook_path,
            self.store,
        )

    def export_coverage(self, output_path: Path | None = None) -> Path:
        source_value = self.store.get_metadata("coverage_csv")
        if not source_value:
            raise PipelineError("No coverage CSV has been imported")
        source = Path(source_value)
        destination = output_path or source.with_name(
            f"{source.stem}_资产结果{source.suffix}"
        )
        return write_coverage_results(source, destination, self.store)

    def export_dimension_report(self, output_path: Path) -> Path:
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, object]] = []
        for device, status in self.store.list_devices():
            if device.source_kind != "coverage_csv":
                continue
            bundle = self.store.get_research(device.id)
            task = self.store.get_meshy_task(device.id)
            report = self.store.get_qc(device.id)
            dimensions = bundle.dimensions if bundle else Dimensions()
            rows.append(
                {
                    "device_id": device.id,
                    "厂商和型号": device.manufacturer_model,
                    "工作流状态": status.value,
                    "身份置信度": bundle.identity_confidence if bundle else "",
                    "宽_mm": dimensions.width_mm or "",
                    "深_mm": dimensions.depth_mm or "",
                    "高_mm": dimensions.height_mm or "",
                    "尺寸来源": dimensions.source_url or "",
                    "尺寸说明": dimensions.notes,
                    "已选参考图数": len(bundle.selected_images()) if bundle else 0,
                    "Meshy任务": task.task_id if task else "",
                    "实际Credits": task.consumed_credits if task else 0,
                    "几何QC": report.geometry_pass if report else "",
                    "视觉QC": report.visual_pass if report else "",
                    "视觉分数": report.visual_similarity_score if report else "",
                    "可发布": report.passed if report else False,
                }
            )
        fieldnames = list(rows[0]) if rows else []
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return output_path

    def publish_approved_asset(self, device_id: str) -> Path | None:
        device = self.store.get_device(device_id)
        qc = self.store.get_qc(device_id)
        if not qc or not qc.final_glb:
            return None
        source = Path(qc.final_glb)
        if not source.exists():
            raise PipelineError(f"Approved GLB does not exist: {source}")
        filename = re.sub(r'[\\/:*?"<>|]+', "-", device.manufacturer_model).strip(" .-")
        glb_destination = self.settings.approved_assets_dir / f"{filename}.glb"
        stl_destination = self.settings.approved_assets_dir / f"{filename}.stl"
        glb_destination.parent.mkdir(parents=True, exist_ok=True)

        scene = trimesh.load_scene(source, process=False)
        scene.apply_transform(
            trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0])
        )
        bounds = scene.bounds
        scene.apply_translation(
            [
                -float((bounds[0, 0] + bounds[1, 0]) / 2),
                -float((bounds[0, 1] + bounds[1, 1]) / 2),
                -float(bounds[0, 2]),
            ]
        )
        glb_data = scene.export(file_type="glb")
        if not isinstance(glb_data, bytes):
            raise PipelineError("Unexpected GLB export result")
        glb_destination.write_bytes(glb_data)

        mesh = scene.to_mesh()
        mesh.apply_scale(1000.0)
        exported = mesh.export(file_type="stl")
        if not isinstance(exported, bytes):
            raise PipelineError("Unexpected STL export result")
        stl_destination.write_bytes(exported)

        self.store.set_metadata(f"published:{device_id}", str(glb_destination))
        self.store.set_metadata(f"published_stl:{device_id}", str(stl_destination))
        return glb_destination

    def _write_manifest(self, device_id: str) -> None:
        device = self.store.get_device(device_id)
        approvals = [
            approval.model_dump(mode="json")
            for approval in self.store.list_approvals(device_id)
        ]
        write_manifest(
            self.settings.asset_dir(device_id) / "manifest.json",
            device,
            self.store.get_research(device_id),
            self.store.get_meshy_task(device_id),
            self.store.get_qc(device_id),
            approvals,
        )
