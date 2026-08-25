from __future__ import annotations

from pathlib import Path

import streamlit as st

from .config import get_settings
from .models import WorkflowStatus
from .pipeline import AssetPipeline


def _rerun_after(action, success: str) -> None:
    try:
        action()
        st.toast(success)
        st.rerun()
    except Exception as error:
        st.error(str(error))


def _research_gate(pipeline: AssetPipeline) -> None:
    st.header("审批 1：图片与尺寸证据")
    rows = pipeline.store.list_devices(WorkflowStatus.AWAITING_RESEARCH_APPROVAL)
    if not rows:
        st.caption("当前没有等待图片审阅的设备。")
        return
    for device, _ in rows:
        bundle = pipeline.store.get_research(device.id)
        if not bundle:
            continue
        with st.expander(device.manufacturer_model, expanded=True):
            st.write(bundle.agent_summary)
            st.caption(f"型号置信度：{bundle.identity_confidence:.0%}")
            dimensions = bundle.dimensions
            columns = st.columns(3)
            width = columns[0].number_input(
                "宽 (mm)",
                min_value=0.0,
                value=float(dimensions.width_mm or 0),
                key=f"w-{device.id}",
            )
            depth = columns[1].number_input(
                "深 (mm)",
                min_value=0.0,
                value=float(dimensions.depth_mm or 0),
                key=f"d-{device.id}",
            )
            height = columns[2].number_input(
                "高 (mm)",
                min_value=0.0,
                value=float(dimensions.height_mm or 0),
                key=f"h-{device.id}",
            )
            source = st.text_input(
                "尺寸来源 URL",
                value=dimensions.source_url or "",
                key=f"source-{device.id}",
            )
            for image in bundle.images:
                left, right = st.columns([1, 2])
                with left:
                    if image.local_path and Path(image.local_path).exists():
                        st.image(
                            image.local_path, caption=image.view_label or image.title
                        )
                with right:
                    image.selected = st.checkbox(
                        "提交给 Meshy",
                        value=image.selected,
                        key=f"select-{device.id}-{image.id}",
                    )
                    image.view_label = st.selectbox(
                        "视角",
                        ["", "front", "side", "rear", "three-quarter"],
                        index=["", "front", "side", "rear", "three-quarter"].index(
                            image.view_label
                        )
                        if image.view_label
                        in {"front", "side", "rear", "three-quarter"}
                        else 0,
                        key=f"view-{device.id}-{image.id}",
                    )
                    st.caption(
                        f"{image.width}×{image.height} · {image.search_provider or 'unknown'}"
                        f" · 检索评分 {image.score:.0%}"
                        f" · 3D适用度 {image.reconstruction_score:.0%}\n\n"
                        f"{image.page_url or image.source_url}"
                    )
            note = st.text_input("审批备注", key=f"research-note-{device.id}")
            save_col, approve_col, reject_col = st.columns(3)

            def save_bundle() -> None:
                bundle.dimensions.width_mm = width or None
                bundle.dimensions.depth_mm = depth or None
                bundle.dimensions.height_mm = height or None
                bundle.dimensions.source_url = source or None
                bundle.dimensions.confidence = (
                    1.0 if bundle.dimensions.complete and source else 0.5
                )
                pipeline.store.save_research(bundle)

            if save_col.button("保存修改", key=f"save-{device.id}"):
                _rerun_after(save_bundle, "候选包已保存")
            if approve_col.button(
                "批准图片与尺寸", type="primary", key=f"approve-r-{device.id}"
            ):

                def approve() -> None:
                    save_bundle()
                    pipeline.approve_research(device.id, note)

                _rerun_after(approve, "研究审批已通过")
            if reject_col.button("退回重新检索", key=f"reject-r-{device.id}"):
                _rerun_after(
                    lambda: pipeline.reject_research(device.id, note or "人工退回"),
                    "已退回",
                )


def _generation_gate(pipeline: AssetPipeline) -> None:
    st.header("审批 2：生成预算")
    rows = pipeline.store.list_devices(WorkflowStatus.AWAITING_GENERATION_APPROVAL)
    if not rows:
        st.caption("当前没有等待生成批准的设备。")
        return
    selected: list[str] = []
    for device, _ in rows:
        if st.checkbox(device.manufacturer_model, value=True, key=f"batch-{device.id}"):
            selected.append(device.id)
    expected = len(selected) * 30
    st.metric("本批预计 Meshy credits", expected)
    st.caption(
        f"配置上限 {pipeline.settings.max_batch_credits} credits；"
        f"每台最多重试 {pipeline.settings.max_retry_per_device} 次。"
    )
    note = st.text_input("批次备注", key="generation-note")
    if st.button("批准本批生成", type="primary", disabled=not selected):
        _rerun_after(
            lambda: pipeline.approve_generation(selected, note),
            f"已批准 {len(selected)} 台设备",
        )

    approved = pipeline.store.list_devices(WorkflowStatus.GENERATION_APPROVED)
    if approved:
        st.subheader("已批准，等待执行")
        for device, _ in approved:
            if st.button(
                f"生成 {device.manufacturer_model}", key=f"generate-{device.id}"
            ):
                _rerun_after(
                    lambda device_id=device.id: pipeline.generate_device(device_id),
                    "Meshy 任务和自动质检已完成",
                )


def _final_gate(pipeline: AssetPipeline) -> None:
    st.header("审批 3：最终 GLB")
    rows = pipeline.store.list_devices(WorkflowStatus.AWAITING_FINAL_APPROVAL)
    reuse = pipeline.store.list_devices(WorkflowStatus.REUSE_REVIEW)
    if not rows and not reuse:
        st.caption("当前没有等待最终审阅的资产。")
        return
    for device, _ in rows:
        task = pipeline.store.get_meshy_task(device.id)
        qc = pipeline.store.get_qc(device.id)
        with st.expander(device.manufacturer_model, expanded=True):
            preview = pipeline.settings.asset_dir(device.id) / "output" / "preview.png"
            if preview.exists():
                st.image(preview)
            if qc:
                st.write("自动质检：", "通过" if qc.passed else "未通过")
                st.caption(
                    "视觉质检："
                    f"{qc.visual_provider or '未执行'} · "
                    f"{qc.visual_similarity_score if qc.visual_similarity_score is not None else '无分数'}"
                )
                st.json(qc.model_dump(mode="json"))
                final_path = Path(qc.final_glb or "")
                if final_path.exists():
                    st.download_button(
                        "下载 GLB",
                        data=final_path.read_bytes(),
                        file_name=f"{device.id}.glb",
                        mime="model/gltf-binary",
                        key=f"download-{device.id}",
                    )
            note = st.text_input("最终审批备注", key=f"final-note-{device.id}")
            override = st.checkbox(
                "人工覆盖未通过的自动质检", key=f"override-{device.id}"
            )
            approve_col, retry_col = st.columns(2)
            if st.button("运行 Codex/配置的视觉质检", key=f"visual-qc-{device.id}"):
                _rerun_after(
                    lambda device_id=device.id: pipeline.run_visual_qc(device_id),
                    "视觉质检已完成并记录",
                )
            if approve_col.button(
                "批准最终资产", type="primary", key=f"final-{device.id}"
            ):
                _rerun_after(
                    lambda: pipeline.approve_final(device.id, note, override),
                    "最终资产已批准",
                )
            if retry_col.button("退回并重试", key=f"retry-{device.id}"):
                _rerun_after(
                    lambda: pipeline.retry_generation(
                        device.id, note or "人工要求重试"
                    ),
                    "已退回生成审批",
                )
            if task:
                st.caption(
                    f"Meshy task: {task.task_id} · {task.consumed_credits} credits"
                )

    for device, _ in reuse:
        with st.expander(f"复用现有模型：{device.manufacturer_model}"):
            st.write(device.model_evidence)
            st.write(device.repository_link)
            note = st.text_input("复用审批备注", key=f"reuse-note-{device.id}")
            if st.button("批准复用", key=f"reuse-{device.id}"):
                _rerun_after(
                    lambda: pipeline.approve_final(device.id, note, override_qc=True),
                    "现有模型已批准复用",
                )


def main() -> None:
    st.set_page_config(page_title="实验室 3D 资产流水线", layout="wide")
    settings = get_settings()
    pipeline = AssetPipeline(settings)
    st.title("实验室 3D 资产自动化流水线")
    with st.sidebar:
        st.subheader("连接状态")
        search_mode = (
            "官网优先 + Brave + DDGS 后备"
            if settings.brave_search_api_key
            else "官网优先 + DDGS 免费后备"
        )
        st.write("图片检索", search_mode)
        st.write(
            "Cursor API",
            "已配置" if settings.cursor_api_key else "未配置（使用规则评分）",
        )
        st.write("Meshy API", "已配置" if settings.meshy_api_key else "未配置")
        st.write(
            "视觉质检",
            f"{settings.visual_qc_provider}"
            + ("（强制）" if settings.visual_qc_required else "（已禁用门禁）"),
        )
        if st.button("导入/刷新设备清单"):
            _rerun_after(pipeline.bootstrap, "清单已导入")
        if st.button("导出结果工作簿"):
            _rerun_after(pipeline.export_results, "结果工作簿已生成")
    _research_gate(pipeline)
    _generation_gate(pipeline)
    _final_gate(pipeline)


if __name__ == "__main__":
    main()
