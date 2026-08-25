"""Read-only SolidWorks Pack-and-Go probe for the initial asset-pipeline trial.

The adapter refuses to attach when a SOLIDWORKS process already exists.  It
opens only the requested document, never saves the CAD source, and terminates
only processes that were created by this probe.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import struct
import sys
import time
import traceback
from pathlib import Path
from typing import Any


SW_TYPELIB = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--glb-ascii")
    parser.add_argument("--progid", default="SldWorks.Application.33")
    parser.add_argument("--visible", action="store_true")
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def solidworks_pids() -> set[int]:
    command = "@(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue).Id -join ','"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    return {int(item) for item in result.stdout.strip().split(",") if item.strip().isdigit()}


def stop_owned_processes(before: set[int]) -> list[int]:
    stopped: list[int] = []
    for pid in sorted(solidworks_pids() - before):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        stopped.append(pid)
    return stopped


def scalar(value: Any, default: Any = None) -> Any:
    try:
        return value() if callable(value) else value
    except Exception:
        return default


def quaternion_xyzw(rotation: list[float]) -> list[float]:
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = rotation[:9]
    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (m21 - m12) / scale
        y = (m02 - m20) / scale
        z = (m10 - m01) / scale
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / scale
        x = 0.25 * scale
        y = (m01 + m10) / scale
        z = (m02 + m20) / scale
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / scale
        x = (m01 + m10) / scale
        y = 0.25 * scale
        z = (m12 + m21) / scale
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / scale
        x = (m02 + m20) / scale
        y = (m12 + m21) / scale
        z = 0.25 * scale
    return [x, y, z, w]


def component_transform(component: Any) -> dict[str, Any] | None:
    transform = scalar(getattr(component, "GetTotalTransform", None), None)
    if callable(getattr(component, "GetTotalTransform", None)):
        try:
            transform = component.GetTotalTransform(False)
        except Exception:
            transform = None
    if isinstance(transform, tuple):
        transform = transform[0] if transform else None
    if transform is None:
        return None
    data = list(scalar(getattr(transform, "ArrayData", None), []) or [])
    if len(data) < 13:
        return {"raw": data, "status": "unparsed"}
    return {
        "xyz_m": [float(data[9]), float(data[10]), float(data[11])],
        "quat_xyzw": quaternion_xyzw([float(value) for value in data[:9]]),
        "scale": float(data[12]),
        "raw_solidworks_math_transform": [float(value) for value in data],
    }


def component_snapshot(component: Any) -> dict[str, Any]:
    parent = scalar(getattr(component, "GetParent", None))
    parent_name = str(scalar(getattr(parent, "Name2", None), "")) if parent is not None else None
    suppression = int(scalar(getattr(component, "GetSuppression", None), -1))
    return {
        "id": str(scalar(getattr(component, "Name2", None), "")),
        "document": str(scalar(getattr(component, "GetPathName", None), "")),
        "parent": parent_name or None,
        "referenced_configuration": str(scalar(getattr(component, "ReferencedConfiguration", None), "")),
        "suppression_code": suppression,
        "suppressed": bool(scalar(getattr(component, "IsSuppressed", None), False)),
        "visibility_code": scalar(getattr(component, "Visible", None), None),
        "transform_world": component_transform(component),
    }


def mate_candidates(components: list[Any]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for component in components:
        component_name = str(scalar(getattr(component, "Name2", None), ""))
        mates = scalar(getattr(component, "GetMates", None), None)
        if mates is None:
            continue
        for index, mate in enumerate(mates if isinstance(mates, (tuple, list)) else [mates]):
            name = f"{component_name}:mate:{index:04d}"
            key = f"{name}:{scalar(getattr(mate, 'Type', None), 'unknown')}"
            candidates.setdefault(
                key,
                {
                    "id": name,
                    "type_code": scalar(getattr(mate, "Type", None), None),
                    "alignment_code": scalar(getattr(mate, "Alignment", None), None),
                    "source_component": component_name,
                    "status": "unproven",
                    "role": "candidate",
                },
            )
    return sorted(candidates.values(), key=lambda item: item["id"])


def glb_magic(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size < 4:
        return None
    return path.read_bytes()[:4].decode("ascii", errors="replace")


def glb_geometry_summary(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        return {"nodes": 0, "meshes": 0, "primitives": 0, "accessors": 0}
    offset = 12
    document: dict[str, Any] = {}
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
            break
    meshes = document.get("meshes", [])
    return {
        "nodes": len(document.get("nodes", [])),
        "meshes": len(meshes),
        "primitives": sum(len(mesh.get("primitives", [])) for mesh in meshes),
        "accessors": len(document.get("accessors", [])),
    }


def main() -> int:
    args = parse_args()
    assembly = Path(args.assembly).resolve()
    snapshot_path = Path(args.snapshot).resolve()
    report_path = Path(args.report).resolve()
    glb_path = Path(args.glb_ascii).resolve() if args.glb_ascii else None
    started_at = time.time()
    before = solidworks_pids()
    report: dict[str, Any] = {
        "schema": "lab.solidworks_capture_report/v0",
        "source_document": str(assembly),
        "source_read_only": not assembly.exists() or not assembly.stat().st_mode & 0o200,
        "status": "blocked",
        "existing_solidworks_pids": sorted(before),
        "com_revision": None,
        "open_errors": None,
        "open_warnings": None,
        "component_count": 0,
        "mate_candidate_count": 0,
        "glb_export": None,
        "failure": None,
    }
    raw = None
    sw = None
    title = None
    exit_code = 2

    try:
        if not assembly.exists():
            raise FileNotFoundError(assembly)
        if before:
            raise RuntimeError("SOLIDWORKS was already running; probe refused to risk user documents")

        import pythoncom
        import win32com.client
        from win32com.client import gencache

        pythoncom.CoInitialize()
        raw = win32com.client.DispatchEx(args.progid)
        module = gencache.EnsureModule(SW_TYPELIB, 0, 33, 0)
        sw = module.ISldWorks(raw._oleobj_)
        sw.Visible = bool(args.visible)
        report["com_revision"] = str(sw.RevisionNumber())

        # 2=assembly, 1=silent, 2=read-only.
        open_result = sw.OpenDoc6(str(assembly), 2, 3, "", 0, 0)
        if isinstance(open_result, tuple):
            document = open_result[0]
            if len(open_result) > 1:
                report["open_errors"] = int(open_result[1])
            if len(open_result) > 2:
                report["open_warnings"] = int(open_result[2])
        else:
            document = open_result
        if document is None:
            raise RuntimeError("OpenDoc6 returned no document")
        title = str(document.GetTitle())
        assembly_document = module.IAssemblyDoc(document._oleobj_)
        report["resolve_lightweight_result"] = bool(
            assembly_document.ResolveAllLightWeightComponents(False)
        )
        report["force_rebuild_result"] = bool(document.ForceRebuild3(False))
        for method_name, method_args in (
            ("ShowNamedView2", ("*Isometric", 7)),
            ("ViewZoomtofit2", ()),
            ("GraphicsRedraw2", ()),
        ):
            try:
                getattr(document, method_name)(*method_args)
            except Exception:
                pass
        components_raw = assembly_document.GetComponents(False)
        components = [] if components_raw is None else list(
            components_raw if isinstance(components_raw, (tuple, list)) else [components_raw]
        )
        # GetComponents does not guarantee a stable traversal order between
        # independent SolidWorks sessions.  Persist a deterministic snapshot;
        # the native GLB is assessed separately because its node order remains
        # controlled by the exporter.
        instances = sorted(
            (component_snapshot(component) for component in components),
            key=lambda item: item["id"],
        )
        candidates = mate_candidates(components)
        roots = [item for item in instances if item["parent"] is None]
        snapshot = {
            "schema": "lab.assembly_snapshot/v0",
            "source_document": str(assembly),
            "capture_adapter": "SwPackAndGoAdapter/trial-v0",
            "units": {"length": "m", "angle": "rad", "orientation": "quaternion_xyzw"},
            "instances": instances,
            "mates_candidate": candidates,
            "root_occurrences": [item["id"] for item in roots],
        }
        write_json(snapshot_path, snapshot)
        report["component_count"] = len(instances)
        report["mate_candidate_count"] = len(candidates)

        if glb_path is not None:
            if any(ord(character) > 127 for character in str(glb_path)):
                raise RuntimeError("SolidWorks GLB output must use an ASCII path")
            glb_path.parent.mkdir(parents=True, exist_ok=True)
            document.ClearSelection2(True)
            sw.ActivateDoc3(title, True, 0, 0)
            save_result = document.Extension.SaveAs3(str(glb_path), 0, 1, None, None, 0, 0)
            if isinstance(save_result, tuple):
                saved = bool(save_result[0])
                save_errors = int(save_result[1]) if len(save_result) > 1 else None
                save_warnings = int(save_result[2]) if len(save_result) > 2 else None
            else:
                saved = bool(save_result)
                save_errors = None
                save_warnings = None
            report["glb_export"] = {
                "requested": True,
                "save_result": saved,
                "save_errors": save_errors,
                "save_warnings": save_warnings,
                "exists": glb_path.exists(),
                "bytes": glb_path.stat().st_size if glb_path.exists() else 0,
                "magic": glb_magic(glb_path),
                "geometry": glb_geometry_summary(glb_path) if glb_path.exists() else None,
            }
            geometry = report["glb_export"]["geometry"] or {}
            if (
                not saved
                or glb_magic(glb_path) != "glTF"
                or geometry.get("primitives", 0) == 0
                or geometry.get("accessors", 0) == 0
            ):
                raise RuntimeError("SolidWorks SaveAs3 did not produce a non-empty GLB")

        report["status"] = "passed"
        exit_code = 0
    except Exception as exc:
        report["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        if raw is not None:
            try:
                if title:
                    raw.CloseDoc(title)
            except Exception:
                pass
            try:
                raw.ExitApp()
            except Exception:
                pass
        try:
            import pythoncom

            pythoncom.CoUninitialize()
        except Exception:
            pass
        time.sleep(2.0)
        report["terminated_owned_pids"] = stop_owned_processes(before)
        report["duration_s"] = round(time.time() - started_at, 3)
        write_json(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
