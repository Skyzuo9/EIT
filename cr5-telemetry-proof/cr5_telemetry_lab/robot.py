"""SourceRelease 预览包的机器人 Registry 声明。"""

from unilabos.registry.decorators import device


@device(
    id="dobot_cr5",
    category=["robot", "cr5", "source-release-preview"],
    displayname="Dobot CR5",
    description="只读厂家 ZIP 派生的 CR5 kinematic-preview，不授予真机执行权。",
    version="0.2.0",
    model={
        "type": "package_moveit",
        "provider": "cr5_telemetry_lab.source_release_model:build_dobot_cr5_model",
        "source_digest": "487463ecc4941fe7df57e9fb2fea38477164d91907699a0e0de3e0c2c44b468c",
    },
)
class DobotCr5Arm:
    def __init__(self, **kwargs):
        del kwargs


@device(
    id="fairino_fr5",
    category=["robot", "fr5", "source-release-preview"],
    displayname="FAIRINO FR5",
    description="只读厂家 ZIP 派生的 FR5 kinematic-preview，不授予真机执行权。",
    version="0.2.0",
    model={
        "type": "package_moveit",
        "provider": "cr5_telemetry_lab.source_release_model:build_fairino_fr5_model",
        "source_digest": "5e46a19e271638a7e1420f2727aaf8fb977016101a354b3694cc440f1fb9f071",
    },
)
class FairinoFr5Arm:
    def __init__(self, **kwargs):
        del kwargs


@device(
    id="duco_gcr5_910",
    category=["robot", "gcr5", "source-release-preview", "project-cad-export"],
    displayname="DUCO GCR5-910",
    description="摘要锁定的项目 CAD URDF 预览；非厂家关节限位，不授予真机执行权。",
    version="0.3.0",
    model={
        "type": "package_moveit",
        "provider": "cr5_telemetry_lab.source_release_model:build_duco_gcr5_910_model",
        "source_digest": "c91cd096d8c6acde34bb57c85d4b7916c6ab17dc22feff09c502f29256230612",
    },
)
class DucoGcr5910Arm:
    def __init__(self, **kwargs):
        del kwargs


__all__ = ["DobotCr5Arm", "DucoGcr5910Arm", "FairinoFr5Arm"]
