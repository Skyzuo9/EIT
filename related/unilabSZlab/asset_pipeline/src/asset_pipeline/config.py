from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
TEAM_WORKBOOK_PATH = WORKSPACE_ROOT / "待生成3D资产仪器清单.xlsx"
LEGACY_WORKBOOK_PATH = WORKSPACE_ROOT / "硬件规格清单_设备结构化.xlsx"


def _default_workbook_path() -> Path:
    return TEAM_WORKBOOK_PATH if TEAM_WORKBOOK_PATH.is_file() else LEGACY_WORKBOOK_PATH


DEFAULT_WORKBOOK_PATH = _default_workbook_path()
DEFAULT_OUTPUT_WORKBOOK_PATH = DEFAULT_WORKBOOK_PATH.with_name(
    f"{DEFAULT_WORKBOOK_PATH.stem}_资产结果.xlsx"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    workbook_path: Path = DEFAULT_WORKBOOK_PATH
    output_workbook_path: Path = DEFAULT_OUTPUT_WORKBOOK_PATH
    approved_assets_dir: Path = WORKSPACE_ROOT / "模型资产"
    data_dir: Path = PROJECT_ROOT / "data"
    assets_dir: Path = PROJECT_ROOT / "assets"
    database_path: Path = PROJECT_ROOT / "data" / "pipeline.sqlite3"

    brave_search_api_key: str | None = None
    meshy_api_key: str | None = None
    cursor_api_key: str | None = None
    cursor_model: str = "auto"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    candidate_review_provider: str = "codex"
    visual_qc_provider: str = "codex"
    visual_qc_required: bool = True
    visual_similarity_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    research_identity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    codex_cli_path: str = "codex"
    codex_model: str | None = None
    codex_timeout_seconds: float = Field(default=300.0, ge=30.0)

    brave_image_api_url: str = "https://api.search.brave.com/res/v1/images/search"
    brave_web_api_url: str = "https://api.search.brave.com/res/v1/web/search"
    meshy_api_url: str = "https://api.meshy.ai/openapi/v1"
    image_candidates_per_device: int = Field(default=12, ge=4, le=50)
    meshy_poll_seconds: float = Field(default=10.0, ge=1.0)
    meshy_timeout_seconds: float = Field(default=1800.0, ge=60.0)
    max_retry_per_device: int = Field(default=1, ge=0, le=3)
    max_batch_credits: int = Field(default=540, ge=30)

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def asset_dir(self, device_id: str) -> Path:
        path = self.assets_dir / device_id
        path.mkdir(parents=True, exist_ok=True)
        return path


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
