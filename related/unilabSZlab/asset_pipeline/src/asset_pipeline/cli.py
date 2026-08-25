from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import subprocess
import sys
from pathlib import Path

from .agent import GeneratedVisualReview
from .catalog import write_asset_catalog
from .config import get_settings
from .models import WorkflowStatus
from .pipeline import AssetPipeline
from .workbook import write_team_instrument_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Laboratory 3D asset automation pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("bootstrap", help="Import and classify in-progress devices")
    subparsers.add_parser("list", help="List devices and workflow states")

    set_input = subparsers.add_parser(
        "set-input",
        help="Write first-run instrument names into the simple team workbook",
    )
    set_input.add_argument(
        "--instrument",
        action="append",
        required=True,
        dest="instruments",
        help="Exact manufacturer/model name; repeat for multiple instruments",
    )
    set_input.add_argument("--replace", action="store_true")

    import_coverage = subparsers.add_parser(
        "import-coverage",
        help="Import rows with empty model locations from coverage CSV",
    )
    import_coverage.add_argument("path", type=Path)

    research = subparsers.add_parser(
        "research", help="Research one or all imported devices"
    )
    research.add_argument("device_id", nargs="?")
    research.add_argument("--all", action="store_true")
    research.add_argument(
        "--pilot", action="store_true", help="Only research the first device"
    )
    research.add_argument("--workers", type=int, default=1)
    research.add_argument("--retry-failed", action="store_true")

    approve_research = subparsers.add_parser("approve-research")
    approve_research.add_argument("device_id")
    approve_research.add_argument("--note", default="")

    dimensions = subparsers.add_parser("set-dimensions")
    dimensions.add_argument("device_id")
    dimensions.add_argument("width_mm", type=float)
    dimensions.add_argument("depth_mm", type=float)
    dimensions.add_argument("height_mm", type=float)
    dimensions.add_argument("source_url")
    dimensions.add_argument("--note", default="")

    reference = subparsers.add_parser(
        "add-reference-image",
        help="Import an inspected exact-model image and record its provenance",
    )
    reference.add_argument("device_id")
    reference.add_argument("source_path", type=Path)
    reference.add_argument("source_url")
    reference.add_argument("--page-url", default="")
    reference.add_argument("--title", default="")
    reference.add_argument("--view-label", default="")
    reference.add_argument("--replace-selected", action="store_true")

    approve_generation = subparsers.add_parser("approve-generation")
    approve_generation.add_argument("device_ids", nargs="+")
    approve_generation.add_argument("--note", default="")

    generate = subparsers.add_parser("generate")
    generate.add_argument("device_id", nargs="?")
    generate.add_argument("--all", action="store_true")

    retry_generation = subparsers.add_parser(
        "retry-generation",
        help="Archive a failed task/QC and authorize one evidence-backed new task",
    )
    retry_generation.add_argument("device_id")
    retry_generation.add_argument("--note", default="")

    approve_final = subparsers.add_parser("approve-final")
    approve_final.add_argument("device_id")
    approve_final.add_argument("--note", default="")
    approve_final.add_argument("--override-qc", action="store_true")

    visual_qc = subparsers.add_parser(
        "visual-qc", help="Run the configured visual QC provider"
    )
    visual_qc.add_argument("device_id")

    visual_request = subparsers.add_parser(
        "visual-qc-request", help="Print evidence paths and rubric for Codex review"
    )
    visual_request.add_argument("device_id")

    record_visual = subparsers.add_parser(
        "record-visual-qc", help="Persist a structured visual QC result"
    )
    record_visual.add_argument("device_id")
    record_visual.add_argument("result_json", type=Path)
    record_visual.add_argument("--reviewer", default="codex-interactive")
    record_visual.add_argument("--model", default="current-session")

    catalog = subparsers.add_parser(
        "catalog", help="Write the auditable published-asset catalog"
    )
    catalog.add_argument("--output", type=Path)

    subparsers.add_parser(
        "advance", help="Run every non-interactive stage until an approval gate"
    )
    subparsers.add_parser("export", help="Write the result workbook")
    export_coverage = subparsers.add_parser(
        "export-coverage", help="Write coverage CSV with approved model paths"
    )
    export_coverage.add_argument("--output", type=Path)
    export_dimensions = subparsers.add_parser(
        "export-dimensions",
        help="Write coverage-device dimensions, evidence, credits, and QC CSV",
    )
    export_dimensions.add_argument("output", type=Path)
    subparsers.add_parser("dashboard", help="Launch the local approval dashboard")
    return parser


def _print_devices(pipeline: AssetPipeline) -> None:
    for device, status in pipeline.store.list_devices():
        print(
            f"{device.id}\t{status.value}\t{device.route}\t{device.manufacturer_model}"
        )


def _research_targets(
    pipeline: AssetPipeline,
    device_id: str | None,
    all_devices: bool,
    pilot: bool,
    retry_failed: bool = False,
) -> list[str]:
    if device_id:
        return [device_id]
    if not all_devices and not pilot:
        raise SystemExit("Provide a device id, --all, or --pilot")
    targets = [
        device.id
        for device, _ in pipeline.store.list_devices(WorkflowStatus.IMPORTED)
        if device.route == "needs_generation"
    ]
    if retry_failed:
        targets.extend(
            device.id
            for device, _ in pipeline.store.list_devices(WorkflowStatus.FAILED)
            if device.route == "needs_generation"
        )
    return targets[:1] if pilot else targets


def _generate_targets(
    pipeline: AssetPipeline, device_id: str | None, all_devices: bool
) -> list[str]:
    if device_id:
        return [device_id]
    if not all_devices:
        raise SystemExit("Provide a device id or --all")
    return [
        device.id
        for device, _ in pipeline.store.list_devices(WorkflowStatus.GENERATION_APPROVED)
    ]


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    pipeline = AssetPipeline(get_settings())
    if args.command == "set-input":
        if pipeline.store.list_devices():
            raise SystemExit(
                "Refusing to rewrite team input after pipeline state exists. "
                "Resume the existing SQLite state instead."
            )
        count = write_team_instrument_names(
            pipeline.settings.workbook_path,
            args.instruments,
            replace=args.replace,
        )
        print(f"Wrote {count} instruments to {pipeline.settings.workbook_path}")
    elif args.command == "bootstrap":
        generated, reused = pipeline.bootstrap()
        print(f"Imported {generated + reused}: {generated} generation, {reused} reuse")
    elif args.command == "import-coverage":
        generated, manual = pipeline.import_coverage(args.path)
        print(
            f"Imported {generated + manual}: {generated} generation, "
            f"{manual} manual identification"
        )
    elif args.command == "list":
        _print_devices(pipeline)
    elif args.command == "research":
        targets = _research_targets(
            pipeline,
            args.device_id,
            args.all,
            args.pilot,
            args.retry_failed,
        )
        if args.workers <= 1:
            for device_id in targets:
                print(f"Researching {device_id}")
                pipeline.research_device(device_id)
        else:
            failures: list[str] = []
            with ThreadPoolExecutor(max_workers=min(args.workers, 8)) as executor:
                futures = {
                    executor.submit(pipeline.research_device, device_id): device_id
                    for device_id in targets
                }
                for future in as_completed(futures):
                    device_id = futures[future]
                    try:
                        future.result()
                        print(f"Researched {device_id}")
                    except Exception as error:
                        failures.append(f"{device_id}: {error}")
                        print(f"Research failed {device_id}: {error}", file=sys.stderr)
            if failures:
                raise SystemExit(f"Research failures: {len(failures)}")
    elif args.command == "approve-research":
        pipeline.approve_research(args.device_id, args.note)
    elif args.command == "set-dimensions":
        print(
            pipeline.set_dimensions(
                args.device_id,
                args.width_mm,
                args.depth_mm,
                args.height_mm,
                args.source_url,
                args.note,
            ).model_dump_json(indent=2)
        )
    elif args.command == "add-reference-image":
        print(
            pipeline.add_reference_image(
                args.device_id,
                args.source_path,
                args.source_url,
                page_url=args.page_url,
                title=args.title,
                view_label=args.view_label,
                replace_selected=args.replace_selected,
            ).model_dump_json(indent=2)
        )
    elif args.command == "approve-generation":
        credits = pipeline.approve_generation(args.device_ids, args.note)
        print(f"Approved expected spend: {credits} credits")
    elif args.command == "generate":
        for device_id in _generate_targets(pipeline, args.device_id, args.all):
            print(f"Generating {device_id}")
            pipeline.generate_device(device_id)
    elif args.command == "retry-generation":
        retry_number = pipeline.prepare_generation_retry(args.device_id, args.note)
        print(f"Prepared retry {retry_number}; expected spend: 30 credits")
    elif args.command == "approve-final":
        pipeline.approve_final(args.device_id, args.note, args.override_qc)
    elif args.command == "visual-qc":
        print(pipeline.run_visual_qc(args.device_id).model_dump_json(indent=2))
    elif args.command == "visual-qc-request":
        print(
            json.dumps(
                pipeline.visual_qc_request(args.device_id),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "record-visual-qc":
        payload = json.loads(args.result_json.read_text(encoding="utf-8"))
        payload.setdefault("provider", args.reviewer)
        payload.setdefault("model", args.model)
        request = pipeline.visual_qc_request(args.device_id)
        payload.setdefault(
            "evidence_paths",
            request["reference_images"] + request["generated_previews"],
        )
        review = GeneratedVisualReview.model_validate(payload)
        print(
            pipeline.record_visual_qc(args.device_id, review).model_dump_json(indent=2)
        )
    elif args.command == "advance":
        pipeline.bootstrap()
        imported = _research_targets(pipeline, None, True, False)
        for device_id in imported:
            pipeline.research_device(device_id)
        for device_id in _generate_targets(pipeline, None, True):
            pipeline.generate_device(device_id)
        print("Pipeline is waiting at the next human approval gate.")
    elif args.command == "export":
        print(pipeline.export_results())
    elif args.command == "export-coverage":
        print(pipeline.export_coverage(args.output))
    elif args.command == "export-dimensions":
        print(pipeline.export_dimension_report(args.output))
    elif args.command == "catalog":
        print(write_asset_catalog(pipeline.settings, pipeline.store, args.output))
    elif args.command == "dashboard":
        dashboard_path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
        environment = os.environ.copy()
        environment["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        environment["STREAMLIT_SERVER_HEADLESS"] = "true"
        raise SystemExit(
            subprocess.run(
                [sys.executable, "-m", "streamlit", "run", str(dashboard_path)],
                env=environment,
                check=False,
            ).returncode
        )


if __name__ == "__main__":
    main()
