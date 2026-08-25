from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .models import (
    Approval,
    DeviceRecord,
    MeshyTask,
    QCReport,
    ResearchBundle,
    WorkflowStatus,
    utc_now,
)

T = TypeVar("T", bound=BaseModel)


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    source_row INTEGER NOT NULL,
                    route TEXT NOT NULL,
                    workflow_status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    device_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (device_id, kind),
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    gate TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            approval_columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(approvals)").fetchall()
            }
            if "details" not in approval_columns:
                db.execute(
                    "ALTER TABLE approvals ADD COLUMN details TEXT NOT NULL DEFAULT '{}'"
                )

    def upsert_devices(self, devices: Iterable[DeviceRecord]) -> None:
        now = utc_now()
        with self.connect() as db:
            for device in devices:
                initial = (
                    WorkflowStatus.REUSE_REVIEW
                    if device.route == "reuse_existing"
                    else (
                        WorkflowStatus.MANUAL
                        if device.route == "manual_identification"
                        else WorkflowStatus.IMPORTED
                    )
                )
                db.execute(
                    """
                    INSERT INTO devices
                        (id, source_row, route, workflow_status, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        source_row=excluded.source_row,
                        route=excluded.route,
                        payload=excluded.payload,
                        updated_at=excluded.updated_at
                    """,
                    (
                        device.id,
                        device.source_row,
                        device.route,
                        initial.value,
                        device.model_dump_json(),
                        now,
                        now,
                    ),
                )

    def get_device(self, device_id: str) -> DeviceRecord:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM devices WHERE id=?", (device_id,)
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown device: {device_id}")
        return DeviceRecord.model_validate_json(row["payload"])

    def list_devices(
        self, status: WorkflowStatus | None = None, route: str | None = None
    ) -> list[tuple[DeviceRecord, WorkflowStatus]]:
        query = "SELECT payload, workflow_status FROM devices"
        clauses: list[str] = []
        params: list[str] = []
        if status:
            clauses.append("workflow_status=?")
            params.append(status.value)
        if route:
            clauses.append("route=?")
            params.append(route)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY source_row"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [
            (
                DeviceRecord.model_validate_json(row["payload"]),
                WorkflowStatus(row["workflow_status"]),
            )
            for row in rows
        ]

    def set_status(self, device_id: str, status: WorkflowStatus) -> None:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE devices SET workflow_status=?, updated_at=? WHERE id=?",
                (status.value, utc_now(), device_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown device: {device_id}")

    def save_artifact(self, device_id: str, kind: str, value: BaseModel | dict) -> None:
        payload = (
            value.model_dump_json()
            if isinstance(value, BaseModel)
            else json.dumps(value)
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO artifacts (device_id, kind, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id, kind) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (device_id, kind, payload, utc_now()),
            )

    def get_artifact(self, device_id: str, kind: str, model: type[T]) -> T | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM artifacts WHERE device_id=? AND kind=?",
                (device_id, kind),
            ).fetchone()
        return model.model_validate_json(row["payload"]) if row else None

    def list_artifact_kinds(self, device_id: str) -> list[str]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT kind FROM artifacts WHERE device_id=? ORDER BY kind",
                (device_id,),
            ).fetchall()
        return [str(row["kind"]) for row in rows]

    def delete_artifact(self, device_id: str, kind: str) -> None:
        with self.connect() as db:
            db.execute(
                "DELETE FROM artifacts WHERE device_id=? AND kind=?",
                (device_id, kind),
            )

    def save_research(self, bundle: ResearchBundle) -> None:
        self.save_artifact(bundle.device_id, "research", bundle)

    def get_research(self, device_id: str) -> ResearchBundle | None:
        return self.get_artifact(device_id, "research", ResearchBundle)

    def save_meshy_task(self, task: MeshyTask) -> None:
        self.save_artifact(task.device_id, "meshy_task", task)

    def get_meshy_task(self, device_id: str) -> MeshyTask | None:
        return self.get_artifact(device_id, "meshy_task", MeshyTask)

    def save_qc(self, report: QCReport) -> None:
        self.save_artifact(report.device_id, "qc", report)

    def get_qc(self, device_id: str) -> QCReport | None:
        return self.get_artifact(device_id, "qc", QCReport)

    def add_approval(self, approval: Approval) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO approvals
                    (device_id, gate, decision, note, details, decided_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.device_id,
                    approval.gate,
                    approval.decision,
                    approval.note,
                    json.dumps(
                        {
                            "reviewer": approval.reviewer,
                            "override_qc": approval.override_qc,
                        },
                        ensure_ascii=False,
                    ),
                    approval.decided_at,
                ),
            )

    def list_approvals(self, device_id: str) -> list[Approval]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT device_id, gate, decision, note, details, decided_at
                FROM approvals WHERE device_id=? ORDER BY id
                """,
                (device_id,),
            ).fetchall()
        approvals: list[Approval] = []
        for row in rows:
            payload = dict(row)
            details = json.loads(payload.pop("details") or "{}")
            payload.update(details)
            approvals.append(Approval.model_validate(payload))
        return approvals

    def set_metadata(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO metadata (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, utc_now()),
            )

    def get_metadata(self, key: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM metadata WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None
