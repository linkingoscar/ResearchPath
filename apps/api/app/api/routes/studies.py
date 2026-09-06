from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.analysis_context_contracts import (
    AnalysisDraft,
    AnalysisDraftCreateRequest,
    AnalysisDraftMutation,
    ApplicableCapabilitiesResponse,
    DatasetStructureValidationRequest,
    DatasetStructureVersion,
    DatasetStructureVersionInput,
    ResolvedAnalysisContext,
    StructureValidationResponse,
    StudyContextMutation,
    StudyContextVersion,
)
from app.api.dependencies import ApiServices, get_services
from app.services.analysis_context import AnalysisContextResolutionError
from app.services.analysis_drafts import AnalysisDraftError
from app.services.dataset_repository import DatasetNotFoundError
from app.study_context_contracts import (
    DatasetStructureInput,
    DatasetStructureRecord,
    StudyContextInput,
)

router = APIRouter(tags=["study-context"])


@router.post(
    "/datasets/{dataset_id}/analysis-drafts",
    response_model=AnalysisDraft,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis_draft(
    dataset_id: str,
    request: AnalysisDraftCreateRequest,
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        return services.workflow_services.analysis_draft.create(
            dataset_id, request.slice_id, request.context_hash
        )
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AnalysisDraftError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "details": {},
                "remediation": "重新读取当前分析上下文并选择适用且可执行的方法。",
            },
        ) from error


@router.put("/analysis-drafts/{draft_id}", response_model=AnalysisDraft)
def update_analysis_draft(
    draft_id: str,
    request: AnalysisDraftMutation,
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        return services.workflow_services.analysis_draft.update(
            draft_id,
            request.expected_revision,
            request.spec,
            {
                role: value.model_dump(by_alias=True)
                for role, value in request.role_overrides.items()
            },
        )
    except AnalysisDraftError as error:
        status_code = 404 if error.code == "ANALYSIS_DRAFT_NOT_FOUND" else 409
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": error.code,
                "message": str(error),
                "details": {},
                "remediation": "读取最新草稿；过期草稿请创建替代草稿。",
            },
        ) from error


@router.get("/analysis-drafts/{draft_id}", response_model=AnalysisDraft)
def get_analysis_draft(
    draft_id: str, services: ApiServices = Depends(get_services)
) -> dict[str, object]:
    stored = services.dataset_repository.get_analysis_draft(draft_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="分析草稿不存在")
    return stored


@router.get("/analysis-drafts/{draft_id}/validity", response_model=AnalysisDraft)
def get_analysis_draft_validity(
    draft_id: str, services: ApiServices = Depends(get_services)
) -> dict[str, object]:
    try:
        return services.workflow_services.analysis_draft.get_validity(draft_id)
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AnalysisDraftError as error:
        status_code = 404 if error.code == "ANALYSIS_DRAFT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.get(
    "/datasets/{dataset_id}/applicable-capabilities",
    response_model=ApplicableCapabilitiesResponse,
)
def get_applicable_capabilities(
    dataset_id: str,
    context_hash: str | None = Query(default=None, alias="contextHash"),
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        resolved = services.analysis_context_service.resolve(dataset_id)
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if context_hash is not None and context_hash != resolved["contextHash"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ANALYSIS_CONTEXT_STALE",
                "message": "请求的 contextHash 不是当前可解析上下文",
                "details": {"currentContextHash": resolved["contextHash"]},
                "remediation": "重新读取 resolved-analysis-context 后刷新方法目录。",
            },
        )
    return {
        "schemaVersion": "1.0.0",
        "contextHash": resolved["contextHash"],
        "capabilities": services.capability_applicability_service.list(resolved),
    }


@router.get(
    "/datasets/{dataset_id}/resolved-analysis-context",
    response_model=ResolvedAnalysisContext,
)
def get_resolved_analysis_context(
    dataset_id: str,
    measurement_version: int | None = Query(default=None, alias="measurementVersion"),
    sample_version_id: str | None = Query(default=None, alias="sampleVersionId"),
    imputation_version_id: str | None = Query(default=None, alias="imputationVersionId"),
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        return services.analysis_context_service.resolve(
            dataset_id,
            measurement_version=measurement_version,
            sample_version_id=sample_version_id,
            imputation_version_id=imputation_version_id,
        )
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AnalysisContextResolutionError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "details": error.details,
                "remediation": "选择属于当前数据版本的对象后重试。",
            },
        ) from error


@router.get("/projects/{project_id}/study-context", response_model=StudyContextVersion)
def get_study_context(
    project_id: str, services: ApiServices = Depends(get_services)
) -> dict[str, object]:
    stored = services.dataset_repository.get_study_context(project_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="研究项目尚未保存数据结构上下文")
    return stored


@router.get(
    "/projects/{project_id}/study-context/versions",
    response_model=list[StudyContextVersion],
)
def get_study_context_versions(
    project_id: str, services: ApiServices = Depends(get_services)
) -> list[dict[str, object]]:
    return services.dataset_repository.list_study_context_versions(project_id)


@router.put("/projects/{project_id}/study-context", response_model=StudyContextVersion)
def put_study_context(
    project_id: str,
    request: StudyContextInput | StudyContextMutation,
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        if isinstance(request, StudyContextMutation):
            return services.dataset_repository.save_study_context_version(
                project_id,
                request.context.model_dump(by_alias=True),
                request.expected_revision,
            )
        # The whole-document request form saves without a revision precondition.
        return services.dataset_repository.save_study_context(
            project_id, request.model_dump(by_alias=True)
        )
    except ValueError as error:
        code = str(error).split(":", 1)[0]
        status_code = 409 if code == "REVISION_CONFLICT" else 422
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": code,
                "message": str(error),
                "details": {},
                "remediation": "读取最新版本后重新确认变更。",
            },
        ) from error


@router.get(
    "/datasets/{dataset_id}/study-structure", response_model=DatasetStructureRecord
)
def get_dataset_structure(
    dataset_id: str, services: ApiServices = Depends(get_services)
) -> dict[str, object]:
    try:
        stored = services.dataset_repository.get_dataset_structure(dataset_id)
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if stored is None:
        raise HTTPException(status_code=404, detail="当前数据版本尚未确认结构角色")
    return stored


@router.put(
    "/datasets/{dataset_id}/study-structure",
    response_model=DatasetStructureRecord,
    status_code=status.HTTP_200_OK,
)
def put_dataset_structure(
    dataset_id: str,
    request: DatasetStructureInput,
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        return services.dataset_repository.save_dataset_structure(
            dataset_id,
            request.model_dump(by_alias=True),
            allow_existing_warning_override=False,
        )
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/datasets/{dataset_id}/study-structure/validate",
    response_model=StructureValidationResponse,
)
def validate_dataset_structure(
    dataset_id: str,
    request: DatasetStructureValidationRequest,
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        return services.dataset_repository.validate_dataset_structure(
            dataset_id,
            request.study_context_version_id,
            request.roles.model_dump(by_alias=True),
        )
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        code = str(error).split(":", 1)[0]
        raise HTTPException(
            status_code=422,
            detail={
                "code": code,
                "message": str(error),
                "details": {},
                "remediation": "检查结构角色和当前项目上下文版本。",
            },
        ) from error


@router.post(
    "/datasets/{dataset_id}/study-structures",
    response_model=DatasetStructureVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_structure_version(
    dataset_id: str,
    request: DatasetStructureVersionInput,
    services: ApiServices = Depends(get_services),
) -> dict[str, object]:
    try:
        return services.dataset_repository.save_dataset_structure_version(
            dataset_id,
            request.study_context_version_id,
            request.roles.model_dump(by_alias=True),
            request.override_reason,
            request.expected_revision,
        )
    except DatasetNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        code = str(error).split(":", 1)[0]
        status_code = 409 if code == "REVISION_CONFLICT" else 422
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": code,
                "message": str(error),
                "details": {},
                "remediation": "读取最新结构版本并重新确认角色或质量警告。",
            },
        ) from error
