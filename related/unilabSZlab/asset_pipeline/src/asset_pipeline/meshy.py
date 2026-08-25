from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import httpx
from PIL import Image

from .config import Settings
from .models import MeshyTask, ResearchBundle, utc_now


class MeshyError(RuntimeError):
    pass


class MeshyClient:
    TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED"}

    def __init__(self, settings: Settings):
        if not settings.meshy_api_key:
            raise MeshyError("MESHY_API_KEY is required for generation")
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.meshy_api_url.rstrip("/") + "/",
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            headers={
                "Authorization": f"Bearer {settings.meshy_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "LabAssetPipeline/0.1",
            },
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> MeshyClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _data_uri(path: Path) -> str:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((4096, 4096))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=94, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def create_task(self, bundle: ResearchBundle) -> MeshyTask:
        selected = bundle.selected_images()
        if not 1 <= len(selected) <= 4:
            raise MeshyError("Meshy requires 1 to 4 approved local images")
        encoded_images = [
            self._data_uri(Path(image.local_path or "")) for image in selected
        ]
        payload = {
            "ai_model": "latest",
            "should_texture": True,
            "enable_pbr": True,
            "hd_texture": True,
            "should_remesh": True,
            "topology": "triangle",
            "target_polycount": 30000,
            "image_enhancement": True,
            "remove_lighting": True,
            "moderation": True,
            "target_formats": ["glb"],
            "auto_size": False,
            "multi_view_thumbnails": True,
            "alpha_thumbnail": True,
        }
        endpoint = "image-to-3d" if len(encoded_images) == 1 else "multi-image-to-3d"
        if endpoint == "image-to-3d":
            payload["image_url"] = encoded_images[0]
        else:
            payload["image_urls"] = encoded_images
        response = self.client.post(endpoint, json=payload)
        self._raise_for_status(response)
        data = response.json()
        task_id = data.get("result") or data.get("id")
        if not task_id:
            raise MeshyError(f"Meshy response did not contain a task id: {data}")
        return MeshyTask(
            device_id=bundle.device_id,
            task_id=str(task_id),
            api_endpoint=endpoint,
            status=str(data.get("status", "PENDING")),
            raw=data,
        )

    def get_task(
        self, device_id: str, task_id: str, endpoint: str = "multi-image-to-3d"
    ) -> MeshyTask:
        response = self.client.get(f"{endpoint}/{task_id}")
        self._raise_for_status(response)
        data = response.json()
        task_error = data.get("task_error") or {}
        model_urls = data.get("model_urls") or {}
        return MeshyTask(
            device_id=device_id,
            task_id=task_id,
            api_endpoint=endpoint,
            status=str(data.get("status", "UNKNOWN")),
            consumed_credits=int(data.get("consumed_credits") or 0),
            model_url=model_urls.get("glb"),
            thumbnail_url=data.get("thumbnail_url"),
            error=str(task_error.get("message") or ""),
            raw=data,
            updated_at=utc_now(),
        )

    def wait_for_task(
        self, device_id: str, task_id: str, endpoint: str = "multi-image-to-3d"
    ) -> MeshyTask:
        deadline = time.monotonic() + self.settings.meshy_timeout_seconds
        while time.monotonic() < deadline:
            task = self.get_task(device_id, task_id, endpoint)
            if task.status in self.TERMINAL_STATUSES:
                return task
            time.sleep(self.settings.meshy_poll_seconds)
        raise MeshyError(
            f"Meshy task timed out after {self.settings.meshy_timeout_seconds}s"
        )

    def download_outputs(self, task: MeshyTask, output_dir: Path) -> Path:
        if task.status != "SUCCEEDED" or not task.model_url:
            raise MeshyError(f"Cannot download incomplete Meshy task: {task.status}")
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "source.glb"
        self._download(task.model_url, model_path)
        if task.thumbnail_url:
            self._download(task.thumbnail_url, output_dir / "preview.png")
        for view, url in (task.raw.get("thumbnail_urls") or {}).items():
            if url:
                self._download(str(url), output_dir / f"preview-{view}.png")
        return model_path

    def _download(self, url: str, path: Path) -> None:
        response = self.client.get(url)
        self._raise_for_status(response)
        path.write_bytes(response.content)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = response.text[:1000]
            raise MeshyError(f"Meshy API {response.status_code}: {detail}") from error
