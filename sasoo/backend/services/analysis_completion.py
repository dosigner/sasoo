"""Read-only completion checks for saved analysis outputs, not scientific review."""

from __future__ import annotations

from collections.abc import Callable

from services.summary_contract import parse_summary_json, validate_summary_extensions


# These are saved deliverables, including local citation output, not LLM prompts.
STAGE_OUTPUTS = {
    "screening": ("스크리닝", {"domain": str, "summary": str, "key_topics": list}),
    "citation": ("인용 분석", {"total_references": int, "top_cited": list, "citation_distribution": dict}),
    "visual": ("시각 자료", {"quality_summary": str, "key_findings_from_visuals": list}),
    "recipe": ("레시피", {"title": str, "objective": str, "parameters": list, "steps": list}),
    "deep_dive": ("심층 분석", {"problem_definition": str, "method_summary": str, "key_results": str,
                               "section_answers": list, "transfer_checks": list}),
    "synthesis": ("종합", {"problem_sentence": str, "method_sentence": str, "key_metrics": list,
                          "equations": list, "result_figures": list, "key_parameters": list}),
    "visualization": ("시각화", {"items": list}),
}
SETTLED = {"completed", "skipped"}


def visualization_plan_matches(payload: dict) -> bool:
    planned = payload.get("planned_items")
    if planned is None:
        return True

    def identities(entries):
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or type(entry.get("id")) is not int
            or not isinstance(entry.get("tool"), str) for entry in entries
        ):
            return None
        pairs = [(entry["id"], entry["tool"]) for entry in entries]
        return set(pairs) if len({pair[0] for pair in pairs}) == len(pairs) else None

    expected, actual = identities(planned), identities(payload.get("items"))
    return expected is not None and actual is not None and expected == actual


def check_stage_output(stage: str, row: dict | None, *, item_available: Callable[[dict], bool] | None = None,
                       allow_legacy_plan_reuse: bool = False) -> dict:
    """Check the newest row without hiding failures behind an older successful row."""
    label, required = STAGE_OUTPUTS[stage]
    check = {"stage": stage, "label": label, "status": "missing", "reason": "저장된 산출물이 없습니다.",
             "required": list(required), "result_id": row.get("id") if row else None}
    if row is None:
        return check

    def result(state: str, reason: str) -> dict:
        return {**check, "status": state, "reason": reason}

    try:
        payload = parse_summary_json(row.get("result") or "")
    except (ValueError, TypeError):
        return result("error", "저장된 응답이 올바른 JSON 객체가 아닙니다.")
    if "error" in payload or "_parse_error" in payload:
        return result("error", str(payload.get("_parse_error") or payload.get("error") or "응답 검증에 실패했습니다."))
    if payload.get("incomplete") or payload.get("response_status") not in (None, "completed"):
        return result("partial", "응답이 완료되지 않았습니다.")
    if payload.get("skipped") is True:
        if stage in {"recipe", "deep_dive"} and row.get("model_used") == "system" and payload.get("reason"):
            return result("skipped", str(payload.get("message") or payload["reason"]))
        return result("partial", "건너뛴 이유를 확인할 수 없습니다.")
    if payload.get("_partial"):
        return result("partial", str(payload["_partial"]))
    missing = [key for key, kind in required.items()
               if not isinstance(payload.get(key), kind)
               or (kind is int and isinstance(payload.get(key), bool))
               or (kind is str and not payload[key].strip())]
    if missing:
        return result("partial", "필수 산출물이 없거나 형식이 다릅니다: " + ", ".join(missing))
    if stage == "citation":
        interpretation = payload.get("interpretation_status")
        if interpretation == "failed":
            return result("error", "인용 해석 요청이 실패했습니다. 로컬 통계는 읽을 수 있습니다.")
        if interpretation not in (None, "completed", "local_only"):
            return result("partial", "인용 해석 상태를 확인할 수 없습니다.")
        if interpretation == "completed" and not str(payload.get("summary") or "").strip():
            return result("partial", "인용 해석 결과가 없습니다.")
    if stage in {"screening", "visual", "recipe", "deep_dive", "synthesis"}:
        # The provider schemas also describe nested items and optional fields.
        from jsonschema import Draft202012Validator
        from services import analysis_execution

        schema = getattr(analysis_execution, f"_{stage.upper()}_SCHEMA")
        error = next(Draft202012Validator(schema).iter_errors(payload), None)
        if error is not None:
            path = ".".join(str(part) for part in error.absolute_path) or stage
            return result("partial", f"응답 스키마에 맞지 않습니다: {path} ({error.message})")
    if stage == "visual" and (payload.get("artifacts_partial") or payload.get("visual_ready") is False
                               or payload.get("visual_state", "ready") != "ready"):
        return result("partial", "시각 자료가 일부만 준비됐습니다. " + str(payload.get("visual_error") or "추출 상태를 확인해 주세요."))
    coverage = payload.get("_input_coverage")
    if isinstance(coverage, dict) and coverage.get("status") == "partial":
        return result("partial", "입력 원문이 일부만 제공됐습니다. 기존 결과는 계속 읽을 수 있습니다.")
    if stage == "deep_dive":
        try:
            validate_summary_extensions(payload, require=True)
        except ValueError as exc:
            return result("partial", str(exc))
    if stage == "visualization":
        items = payload["items"]
        if not visualization_plan_matches(payload):
            return result("partial", "계획한 시각화와 저장된 항목이 다릅니다.")
        if payload.get("complete", True) is not True:
            return result("partial", "중간 저장 결과입니다. 시각화 실행이 끝나지 않았습니다.")
        if not items and payload.get("planned_empty") is not True:
            return result("partial", "시각화가 없고 생성하지 않기로 한 계획도 확인되지 않습니다.")
        if payload.get("total_count", len(items)) != len(items):
            return result("partial", "계획한 시각화 수와 저장된 결과 수가 다릅니다.")
        for item in items:
            if not isinstance(item, dict) or item.get("status") != "completed":
                return result("partial", "실패하거나 끝나지 않은 시각화가 있습니다. 성공한 결과는 보존됩니다.")
            tool = item.get("tool")
            field = {"mermaid": "mermaid_code", "html": "html_code", "paperbanana": "image_path"}.get(tool) if isinstance(tool, str) else None
            value = item.get(field) if field else None
            if not isinstance(value, str) or not value.strip() or (item_available and not item_available(item)):
                return result("partial", "시각화 코드 또는 이미지 파일이 없거나 사용할 수 없습니다.")
            execution = item.get("execution_check")
            if isinstance(execution, dict) and execution.get("status") == "failed":
                return result("partial", "시각화 실행 검증에 실패했습니다.")
    if stage == "citation" and payload.get("interpretation_status") is None:
        return result("completed", "과거 결과입니다. 인용 해석 요청 여부는 확인할 수 없습니다.")
    if stage == "citation" and payload.get("interpretation_status") == "local_only":
        return result("completed", "인용 대상이 없어 로컬 통계만 생성했습니다.")
    if stage == "visualization" and payload.get("planned_items") is None:
        return result("completed" if allow_legacy_plan_reuse else "partial",
                      "저장된 과거 시각화입니다. 생성 계획과의 일치 여부는 확인할 수 없습니다.")
    return result("completed", "필수 산출물과 저장 형식을 확인했습니다.")


def build_completion_checks(rows: dict[str, dict], *, item_available: Callable[[dict], bool] | None = None) -> list[dict]:
    checks = [check_stage_output(stage, rows.get(stage), item_available=item_available) for stage in STAGE_OUTPUTS]
    plan = rows.get("viz_plan")
    visualization = rows.get("visualization")
    if plan and (plan.get("id") or 0) > ((visualization or {}).get("id") or 0):
        try:
            payload = parse_summary_json(plan.get("result") or "")
            failed = "error" in payload or "_parse_error" in payload or bool(payload.get("_partial"))
        except (ValueError, TypeError):
            failed = True
        if failed:
            checks[6] = {**checks[6], "status": "partial" if visualization else "error",
                         "reason": "새 시각화 계획을 완료하지 못했습니다. 이전에 저장한 결과는 유지됩니다."}
    # The existing screening gate omits both downstream stages in this case.
    if all(check["status"] == "skipped" for check in checks[3:5]):
        for index in (5, 6):
            checks[index] = {**checks[index], "status": "skipped", "result_id": None,
                             "reason": "레시피와 심층 분석을 모두 건너뛰어 이번 실행 대상이 아닙니다."}
    return checks


def completion_progress(checks: list[dict]) -> float:
    return 100.0 * sum(check["status"] in SETTLED for check in checks) / len(checks) if checks else 0.0
