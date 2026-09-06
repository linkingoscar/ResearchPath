from __future__ import annotations

# Pandas' dynamically typed column/index operations are isolated in this
# service; API and persistence contracts remain statically checked elsewhere.
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportIndexIssue=false, reportOperatorIssue=false, reportAssignmentType=false, reportCallIssue=false
import hashlib
import json
import math
import re
import uuid
from typing import Any

import numpy as np
import pandas as pd

from app.data_quality_contracts import (
    DataQualityRun,
    DataQualityRunRequest,
)
from app.services.data_quality_io import _write_parquet_atomic
from app.services.dataset_repository import DatasetRepository
from app.services.repository_io import _write_json_atomic
from app.settings import Settings


class DataQualityError(ValueError):
    pass


PandasFrame = Any
PandasSeries = Any


_ID_PATTERN = re.compile(r"(^|[_\s-])(id|uuid|编号|序号|code)($|[_\s-])", re.I)
_RESPONSE_ID_PATTERN = re.compile(r"response.?id|respondent|participant|subject|被试|受访", re.I)
_DURATION_PATTERN = re.compile(r"duration|duration.?in.?seconds|time.?spent|时长|答题时间", re.I)
_TEXT_EMPTY_PATTERN = re.compile(r"^(?:nan|none|null|na|n/a|无|未填写)?$", re.I)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if not isinstance(result, (list, tuple, np.ndarray)) else False
    except (TypeError, ValueError):
        return False


def _as_json_value(value: object) -> object:
    if _is_missing(value):
        return None
    if isinstance(value, np.generic):
        return _as_json_value(value.item())
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)


def _normalize_text(value: object) -> str:
    if _is_missing(value):
        return ""
    normalized = re.sub(r"\s+", " ", str(value)).strip().casefold()
    return "" if _TEXT_EMPTY_PATTERN.fullmatch(normalized) else normalized


def _summary(series: PandasSeries) -> dict[str, object]:
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna().astype(float)
    if valid.empty:
        return {"available": False, "validCount": 0}
    return {
        "available": True,
        "validCount": int(valid.size),
        "missingCount": int(numeric.isna().sum()),
        "mean": float(valid.mean()),
        "median": float(valid.median()),
        "min": float(valid.min()),
        "max": float(valid.max()),
        "p95": float(valid.quantile(0.95)),
    }


def _max_run(values: list[object]) -> tuple[int, int]:
    previous: str | None = None
    current = 0
    maximum = 0
    valid_count = 0
    for value in values:
        if _is_missing(value):
            previous = None
            current = 0
            continue
        normalized = str(value)
        valid_count += 1
        if normalized == previous:
            current += 1
        else:
            previous = normalized
            current = 1
        maximum = max(maximum, current)
    return maximum, valid_count


def _resolve_variable_names(dataset: dict[str, object], variable_ids: list[str]) -> list[str]:
    variables = dataset.get("variables")
    if not isinstance(variables, list):
        raise DataQualityError("数据字典缺少变量列表")
    mapping = {
        str(variable["id"]): str(variable["originalName"])
        for variable in variables
        if isinstance(variable, dict) and "id" in variable and "originalName" in variable
    }
    unknown = [variable_id for variable_id in variable_ids if variable_id not in mapping]
    if unknown:
        raise DataQualityError("未知变量 ID: " + ", ".join(unknown))
    return [mapping[variable_id] for variable_id in variable_ids]


def _validate_columns(dataframe: PandasFrame, names: list[str], label: str) -> None:
    available = {str(name) for name in dataframe.columns}
    missing = sorted({name for name in names if name not in available})
    if missing:
        raise DataQualityError(f"{label} 不存在于已导入数据: {', '.join(missing)}")


def _infer_role(
    dataset: dict[str, object], pattern: re.Pattern[str], excluded: set[str]
) -> tuple[str | None, str | None]:
    variables = dataset.get("variables")
    if not isinstance(variables, list):
        return None, None
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        name = str(variable.get("originalName", ""))
        if name not in excluded and pattern.search(name):
            return str(variable["id"]), name
    return None, None


def _quality_variables(
    dataset: dict[str, object], dataframe: pd.DataFrame, request: DataQualityRunRequest
) -> list[str]:
    if request.quality_variable_ids:
        return _resolve_variable_names(dataset, request.quality_variable_ids)
    variables = dataset.get("variables")
    if not isinstance(variables, list):
        return []
    selected: list[str] = []
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        name = str(variable.get("originalName", ""))
        inferred = str(variable.get("confirmedType") or variable.get("inferredType") or "")
        if name in dataframe.columns and inferred in {"continuous", "binary", "ordinal", "likert"}:
            if not _ID_PATTERN.search(name):
                selected.append(name)
    return selected


def _attention_columns(
    request: DataQualityRunRequest, dataset: dict[str, object]
) -> list[tuple[str, object, str]]:
    result: list[tuple[str, object, str]] = []
    for index, check in enumerate(request.attention_checks, start=1):
        names = _resolve_variable_names(dataset, [check.variable_id])
        result.append((names[0], check.expected_value, f"attention_{index}"))
    return result


def _build_case_metrics(
    dataframe: PandasFrame,
    dataset: dict[str, object],
    request: DataQualityRunRequest,
) -> tuple[PandasFrame, dict[str, object], dict[str, str | None]]:
    variables = _quality_variables(dataset, dataframe, request)
    missing_variables = _resolve_variable_names(dataset, request.structural_missing_variable_ids)
    text_variables = _resolve_variable_names(dataset, request.text_variable_ids)
    group_variables = _resolve_variable_names(dataset, request.group_variable_ids)

    excluded = set(variables) | set(missing_variables) | set(text_variables) | set(group_variables)
    case_id_id, case_id_name = _infer_role(dataset, _RESPONSE_ID_PATTERN, excluded)
    response_id_id = request.response_id_variable_id or case_id_id
    response_id_name = (
        _resolve_variable_names(dataset, [response_id_id])[0] if response_id_id else None
    )
    duration_id = request.duration_variable_id
    duration_name = _resolve_variable_names(dataset, [duration_id])[0] if duration_id else None
    if duration_name is None:
        duration_id, duration_name = _infer_role(dataset, _DURATION_PATTERN, excluded)
    ip_name = (
        _resolve_variable_names(dataset, [request.ip_variable_id])[0]
        if request.ip_variable_id
        else None
    )
    device_name = (
        _resolve_variable_names(dataset, [request.device_variable_id])[0]
        if request.device_variable_id
        else None
    )
    case_id_name = (
        _resolve_variable_names(dataset, [request.case_id_variable_id])[0]
        if request.case_id_variable_id
        else case_id_name
    )
    attention_checks = _attention_columns(request, dataset)
    _validate_columns(dataframe, variables, "质量变量")
    _validate_columns(dataframe, missing_variables, "结构性缺失变量")
    _validate_columns(dataframe, text_variables, "文本变量")
    _validate_columns(dataframe, group_variables, "分组变量")
    _validate_columns(
        dataframe,
        [
            name
            for name in (case_id_name, response_id_name, duration_name, ip_name, device_name)
            if name
        ],
        "角色变量",
    )
    _validate_columns(dataframe, [name for name, _, _ in attention_checks], "注意力检查变量")
    text_value_rows: dict[str, set[int]] = {}
    if text_variables:
        for row_number, (_, row) in enumerate(dataframe.iterrows()):
            for name in text_variables:
                value = _normalize_text(row.get(name))
                if value:
                    text_value_rows.setdefault(value, set()).add(row_number)
    text_value_counts = {value: len(rows) for value, rows in text_value_rows.items()}

    numeric_frame: PandasFrame = (
        dataframe[variables].apply(pd.to_numeric, errors="coerce")
        if variables
        else pd.DataFrame(index=dataframe.index)
    )
    global_extremes: dict[str, set[float]] = {}
    for name in variables:
        valid = numeric_frame[name].dropna()
        if valid.nunique() >= 3:
            global_extremes[name] = {float(valid.min()), float(valid.max())}

    durations: PandasSeries = (
        pd.to_numeric(dataframe[duration_name], errors="coerce")
        if duration_name in dataframe.columns
        else pd.Series(np.nan, index=dataframe.index)
    )
    positive_durations = durations[durations > 0]
    median_duration = float(positive_durations.median()) if not positive_durations.empty else None
    response_ids: PandasSeries = (
        dataframe[response_id_name].map(_normalize_text)
        if response_id_name in dataframe.columns
        else pd.Series("", index=dataframe.index)
    )
    duplicate_ids: PandasSeries = response_ids.ne("") & response_ids.duplicated(keep=False)
    ip_values: PandasSeries = (
        dataframe[ip_name].map(_normalize_text)
        if ip_name in dataframe.columns
        else pd.Series("", index=dataframe.index)
    )
    device_values: PandasSeries = (
        dataframe[device_name].map(_normalize_text)
        if device_name in dataframe.columns
        else pd.Series("", index=dataframe.index)
    )
    duplicate_ip: PandasSeries = ip_values.ne("") & ip_values.duplicated(keep=False)
    duplicate_device: PandasSeries = device_values.ne("") & device_values.duplicated(keep=False)

    mahalanobis: PandasSeries = pd.Series(np.nan, index=dataframe.index, dtype=float)
    complete = numeric_frame.dropna()
    mahalanobis_meta: dict[str, object] = {
        "available": False,
        "completeRows": int(len(complete)),
        "variableCount": len(variables),
    }
    if len(variables) >= 2 and len(complete) > len(variables) + 2:
        values = complete.to_numpy(dtype=float)
        centered = values - values.mean(axis=0)
        covariance = np.atleast_2d(np.cov(values, rowvar=False, ddof=1))
        inverse = np.linalg.pinv(covariance)
        distances = np.einsum("ij,jk,ik->i", centered, inverse, centered)
        mahalanobis.loc[complete.index] = distances
        mahalanobis_meta = {
            "available": True,
            "completeRows": int(len(complete)),
            "variableCount": len(variables),
            "method": "classical_mahalanobis_pinv",
            "p95": float(np.quantile(distances, 0.95)),
        }

    rows: list[dict[str, object]] = []
    attention_fail_counts: list[int] = []
    for row_index, (_, row) in enumerate(dataframe.iterrows(), start=1):
        quality_values = [row.get(name) for name in variables]
        valid_values = [value for value in quality_values if not _is_missing(value)]
        max_run, valid_count = _max_run(quality_values)
        numeric_values = numeric_frame.iloc[row_index - 1]
        extremes = sum(
            float(numeric_values[name]) in global_extremes[name]
            for name in variables
            if name in global_extremes and not pd.isna(numeric_values[name])
        )
        attention_failed = 0
        for name, expected, _ in attention_checks:
            actual = row.get(name)
            if _is_missing(actual) or _normalize_text(actual) != _normalize_text(expected):
                attention_failed += 1
        normalized_text = [_normalize_text(row.get(name)) for name in text_variables]
        non_empty_text = [value for value in normalized_text if value]
        duplicate_text = any(text_value_counts.get(value, 0) > 1 for value in non_empty_text)
        rows.append(
            {
                "caseIndex": row_index,
                "caseId": _as_json_value(row.get(case_id_name)) if case_id_name else row_index,
                "missingRate": (len(quality_values) - len(valid_values)) / len(quality_values)
                if quality_values
                else None,
                "structuralMissingRate": (
                    sum(_is_missing(row.get(name)) for name in missing_variables)
                    / len(missing_variables)
                    if missing_variables
                    else None
                ),
                "durationSeconds": _as_json_value(durations.iloc[row_index - 1]),
                "relativeDuration": (
                    float(durations.iloc[row_index - 1]) / median_duration
                    if median_duration and pd.notna(durations.iloc[row_index - 1])
                    else None
                ),
                "longstringMax": max_run if valid_count else None,
                "responseVariance": (
                    float(
                        np.var(
                            pd.to_numeric(pd.Series(valid_values), errors="coerce").dropna(), ddof=1
                        )
                    )
                    if len(pd.to_numeric(pd.Series(valid_values), errors="coerce").dropna()) > 1
                    else None
                ),
                "straightlineRatio": max_run / valid_count if valid_count else None,
                "extremeResponseRatio": extremes / len(variables) if variables else None,
                "duplicateResponseId": bool(duplicate_ids.iloc[row_index - 1]),
                "duplicateIp": bool(duplicate_ip.iloc[row_index - 1]),
                "duplicateDevice": bool(duplicate_device.iloc[row_index - 1]),
                "attentionCheckFailed": attention_failed > 0,
                "attentionCheckFailCount": attention_failed,
                "duplicateText": duplicate_text,
                "emptyText": bool(text_variables) and not non_empty_text,
                "mahalanobisDistance": _as_json_value(mahalanobis.iloc[row_index - 1]),
            }
        )
        attention_fail_counts.append(attention_failed)

    case_metrics = pd.DataFrame(rows)
    duplicate_text = case_metrics["duplicateText"].astype(bool)
    duration_summary = _summary(case_metrics["durationSeconds"])
    metrics: dict[str, object] = {
        "qualityVariableCount": len(variables),
        "qualityVariableNames": variables,
        "duration": duration_summary,
        "relativeDuration": _summary(case_metrics["relativeDuration"]),
        "missingRate": _summary(case_metrics["missingRate"]),
        "structuralMissingRate": _summary(case_metrics["structuralMissingRate"]),
        "longstringMax": _summary(case_metrics["longstringMax"]),
        "responseVariance": _summary(case_metrics["responseVariance"]),
        "straightlineRatio": _summary(case_metrics["straightlineRatio"]),
        "extremeResponseRatio": _summary(case_metrics["extremeResponseRatio"]),
        "duplicateResponseId": {
            "available": response_id_name is not None,
            "variable": response_id_name,
            "duplicateRowCount": int(duplicate_ids.sum()),
            "uniqueValueCount": int(response_ids.replace("", np.nan).nunique(dropna=True)),
        },
        "duplicateIp": {
            "available": ip_name is not None,
            "variable": ip_name,
            "duplicateRowCount": int(duplicate_ip.sum()),
        },
        "duplicateDevice": {
            "available": device_name is not None,
            "variable": device_name,
            "duplicateRowCount": int(duplicate_device.sum()),
        },
        "attentionChecks": {
            "count": len(attention_checks),
            "failedRowCount": int((case_metrics["attentionCheckFailed"]).sum()),
            "totalFailureCount": int(sum(attention_fail_counts)),
        },
        "text": {
            "variableCount": len(text_variables),
            "duplicateRowCount": int(duplicate_text.sum()),
            "emptyRowCount": int(case_metrics["emptyText"].sum()),
        },
        "mahalanobis": mahalanobis_meta,
        "groups": {
            name: {
                str(key): int(value)
                for key, value in dataframe[name].value_counts(dropna=False).items()
            }
            for name in group_variables
        },
    }
    detected_roles = {
        "caseIdVariableId": request.case_id_variable_id or case_id_id,
        "caseIdVariableName": case_id_name,
        "responseIdVariableId": response_id_id,
        "responseIdVariableName": response_id_name,
        "durationVariableId": duration_id,
        "durationVariableName": duration_name,
        "ipVariableId": request.ip_variable_id,
        "ipVariableName": ip_name,
        "deviceVariableId": request.device_variable_id,
        "deviceVariableName": device_name,
    }
    return case_metrics, metrics, detected_roles


def run_data_quality(
    dataset_id: str,
    request: DataQualityRunRequest,
    settings: Settings,
    repository: DatasetRepository,
) -> DataQualityRun:
    dataset = repository.get_dataset(dataset_id)
    data_path = repository.get_dataset_data_path(dataset_id)
    dataframe = pd.read_parquet(data_path)
    case_metrics, metrics, detected_roles = _build_case_metrics(dataframe, dataset, request)

    run_id = f"quality_{uuid.uuid4().hex[:16]}"
    run_root = (
        settings.state_root
        / "projects"
        / "default"
        / "datasets"
        / dataset_id
        / "quality"
        / "runs"
        / run_id
    )
    case_path = run_root / "cases.parquet"
    run_path = run_root / "run.json"
    _write_parquet_atomic(case_metrics, case_path)
    case_hash = _sha256_bytes(case_path.read_bytes())
    payload = DataQualityRun(
        id=run_id,
        dataset_version_id=dataset_id,
        dataset_sha256=str(dataset["originalFile"]["sha256"]),
        created_at=pd.Timestamp.utcnow().isoformat(),
        request=request,
        row_count=len(dataframe),
        case_metrics_path=case_path.relative_to(settings.state_root).as_posix(),
        case_metrics_hash=case_hash,
        detected_roles=detected_roles,
        metrics=metrics,
    )
    _write_json_atomic(run_path, payload.model_dump(by_alias=True))
    repository.record_data_quality_run(payload.model_dump(by_alias=True), run_path)
    return payload


# Facade used by route imports; sample creation
# and pagination live in their own service to keep the quality metric module
# within the repository's file-size boundary.
from app.services.data_quality_samples import (  # noqa: E402, F401
    create_analysis_sample,
    read_quality_case_page,
    read_sample_case_page,
)
