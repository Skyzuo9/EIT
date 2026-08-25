import json

import httpx
import pytest
from PIL import Image

from asset_pipeline.config import Settings
from asset_pipeline.meshy import MeshyClient
from asset_pipeline.models import CandidateImage, ResearchBundle


@pytest.mark.parametrize(
    ("image_count", "expected_endpoint"),
    [(1, "image-to-3d"), (2, "multi-image-to-3d")],
)
def test_meshy_create_and_resume_payload(
    tmp_path, image_count: int, expected_endpoint: str
) -> None:
    image_path = tmp_path / "input.png"
    Image.new("RGB", (512, 512), "white").save(image_path)
    bundle = ResearchBundle(
        device_id="device-1",
        images=[
            CandidateImage(
                id=f"image-{index}",
                source_url="https://example.com/input.png",
                local_path=str(image_path),
                selected=True,
            )
            for index in range(image_count)
        ],
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["target_formats"] == ["glb"]
            assert payload["enable_pbr"] is True
            image_values = (
                [payload["image_url"]]
                if expected_endpoint == "image-to-3d"
                else payload["image_urls"]
            )
            assert len(image_values) == image_count
            assert image_values[0].startswith("data:image/jpeg;base64,")
            return httpx.Response(200, json={"result": "task-123"})
        return httpx.Response(
            200,
            json={
                "id": "task-123",
                "status": "SUCCEEDED",
                "consumed_credits": 30,
                "model_urls": {"glb": "https://example.com/model.glb"},
            },
        )

    settings = Settings(
        meshy_api_key="secret",
        meshy_api_url="https://api.meshy.test/openapi/v1",
        data_dir=tmp_path / "data",
        assets_dir=tmp_path / "assets",
        database_path=tmp_path / "data" / "pipeline.sqlite3",
    )
    client = MeshyClient(settings)
    client.client = httpx.Client(
        base_url="https://api.meshy.test/openapi/v1/",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer secret"},
    )
    task = client.create_task(bundle)
    assert task.task_id == "task-123"
    assert task.api_endpoint == expected_endpoint
    completed = client.get_task(bundle.device_id, task.task_id, task.api_endpoint)
    assert completed.status == "SUCCEEDED"
    assert completed.consumed_credits == 30
    assert requests[0].url.path == f"/openapi/v1/{expected_endpoint}"
    client.close()
