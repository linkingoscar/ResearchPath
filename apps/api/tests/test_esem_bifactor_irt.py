import csv
import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.advanced_contracts import QuestionnaireMeasurementSpec
from app.services.advanced_analysis import advanced_analysis_registry
from app.settings import get_settings


def _run_measurement_fixture(
    spec_filename: str,
    *,
    add_group: bool = False,
    binary_items: bool = False,
    missing_item_subject_ids: set[int] | None = None,
) -> dict:
    settings = get_settings()
    root = settings.project_root
    spec_path = root / "apps/api/tests/fixtures/advanced" / spec_filename
    source_data_path = root / "apps/api/tests/fixtures/advanced/longitudinal/clpm-three-wave.csv"
    runner = root / "engine/R/run_advanced_analysis.R"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        data_path = source_data_path
        if add_group or binary_items:
            rows = list(csv.DictReader(source_data_path.open(encoding="utf-8", newline="")))
            for row in rows:
                if add_group:
                    row["group"] = "g1" if int(row["subject_id"]) <= 50 else "g2"
                if binary_items:
                    for item_id in spec["itemIds"]:
                        row[item_id] = "1" if float(row[item_id]) >= 5.5 else "0"
                if missing_item_subject_ids and int(row["subject_id"]) in missing_item_subject_ids:
                    row[spec["itemIds"][0]] = ""
            if spec.get("itemScale") == "ordinal" and not binary_items:
                for item_id in spec["itemIds"]:
                    observed = [
                        (index, float(row[item_id]))
                        for index, row in enumerate(rows)
                        if row[item_id] != ""
                    ]
                    ordered = sorted(observed, key=lambda entry: entry[1])
                    for rank, (row_index, _) in enumerate(ordered):
                        rows[row_index][item_id] = str(min(5, 1 + rank * 5 // len(ordered)))
            data_path = work / "binary-grouped-clpm.csv"
            with data_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[*rows[0].keys()])
                writer.writeheader()
                writer.writerows(rows)
        elif spec.get("itemScale") == "ordinal":
            rows = list(csv.DictReader(source_data_path.open(encoding="utf-8", newline="")))
            for row in rows:
                for item_id in spec["itemIds"]:
                    value = float(row[item_id])
                    row[item_id] = str(max(1, min(5, int(round((value - 4.0) / 1.0) + 3))))
            data_path = work / "ordinal-clpm.csv"
            with data_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[*rows[0].keys()])
                writer.writeheader()
                writer.writerows(rows)
        input_path = work / "input.json"
        output_path = work / "output.json"
        input_path.write_text(
            json.dumps({"spec": spec, "dataPath": str(data_path), "artifactDirectory": str(work)}),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["R_LIBS_USER"] = str(settings.r_library_path)
        completed = subprocess.run(
            [
                str(settings.rscript_path),
                "--vanilla",
                str(runner),
                str(input_path),
                str(output_path),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        result = (
            json.loads(output_path.read_text(encoding="utf-8")) if output_path.is_file() else None
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert result is not None
    return result


def test_esem_bifactor_irt_capability_slice_registered() -> None:
    capabilities = advanced_analysis_registry.capabilities()
    qm_cap = next((c for c in capabilities if c.get("family") == "questionnaire_measurement"), {})
    assert qm_cap
    slices = qm_cap.get("slices", [])  # type: ignore
    esem_slice = next(
        (s for s in slices if s.get("id") == "questionnaire_measurement.esem_bifactor_irt"), {}
    )  # type: ignore
    assert esem_slice.get("executionAvailable") is True  # type: ignore
    assert esem_slice.get("status") == "experimental"  # type: ignore


def test_esem_bifactor_irt_spec_validation() -> None:
    spec = QuestionnaireMeasurementSpec.model_validate(
        {
            "analysisId": "measure_test_01",
            "name": "Questionnaire measurement",
            "datasetVersionId": "dataset_001",
            "family": "questionnaire_measurement",
            "modelType": "esem_bifactor_irt",
            "itemIds": ["item_01", "item_02", "item_03", "item_04"],
            "constructs": [
                {"id": "construct_01", "label": "Construct 1", "itemIds": ["item_01", "item_02"]},
                {"id": "construct_02", "label": "Construct 2", "itemIds": ["item_03", "item_04"]},
            ],
            "rotation": "target",
            "seed": 20260720,
        }
    )
    validated = advanced_analysis_registry.validate(spec)
    assert validated.get("valid") is True
    assert validated.get("sliceId") == "questionnaire_measurement.esem_bifactor_irt"
    assert validated.get("executionAvailable") is True


def test_questionnaire_reliability_r_runner_returns_construct_diagnostics() -> None:
    settings = get_settings()
    root = settings.project_root
    spec_path = (
        root / "apps/api/tests/fixtures/advanced/questionnaire-reliability-toothgrowth.spec.json"
    )
    data_path = root / "apps/api/tests/fixtures/advanced/reference/toothgrowth-factorial.csv"
    runner = root / "engine/R/run_advanced_analysis.R"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        input_path = work / "input.json"
        output_path = work / "output.json"
        input_path.write_text(
            json.dumps({"spec": spec, "dataPath": str(data_path), "artifactDirectory": str(work)}),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["R_LIBS_USER"] = str(settings.r_library_path)
        completed = subprocess.run(
            [
                str(settings.rscript_path),
                "--vanilla",
                str(runner),
                str(input_path),
                str(output_path),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        result = (
            json.loads(output_path.read_text(encoding="utf-8")) if output_path.is_file() else None
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert result is not None
    assert result["familyResult"]["reliability"]["available"] is True
    assert len(result["familyResult"]["reliability"]["constructs"]) == 2
    assert result["sampleFlow"]["included"] == 60


def test_efa_r_runner_returns_loadings_and_parallel_analysis() -> None:
    result = _run_measurement_fixture("questionnaire-efa-clpm.spec.json")
    efa = result["familyResult"]["efa"]
    assert efa["available"] is True
    assert efa["factorCount"] == 2
    assert len(efa["loadings"]) == 6
    assert efa["parallelAnalysis"] is not None
    # Parallel analysis declares the correlation world it ran in; the
    # continuous fixture must report Pearson, never an ordinal simulation.
    assert efa["parallelAnalysis"]["available"] is True
    assert efa["parallelAnalysis"]["correlationType"] == "pearson"
    assert efa["parallelAnalysis"]["simulationType"] == "continuous_pearson"
    assert efa["parallelAnalysis"]["quantile"] == 0.95
    # Numerical fallbacks surface inside the result document
    # diagnostics (empty here because no fallback was needed).
    assert efa["diagnostics"]["numericalFallbacks"] == []
    assert efa["requestedCorrelationType"] == "pearson"
    assert efa["executedCorrelationType"] == "pearson"
    assert efa["requestedExtractionMethod"] == "ml"
    assert efa["executedExtractionMethod"] == "ml"
    assert efa["requestedRotation"] == "promax"
    assert efa["executedRotation"] == "promax"
    # Split validation refits the user's estimator spec (ML, Pearson
    # for the continuous fixture) instead of silently swapping to ML/factanal
    # defaults.
    assert efa["splitValidation"]["available"] is True
    assert efa["splitValidation"]["method"] == "ml"
    assert efa["splitValidation"]["correlationType"] == "pearson"
    assert efa["splitValidation"]["extractionMethod"] == "ml"
    assert efa["splitValidation"]["requestedCorrelationType"] == "pearson"
    assert efa["splitValidation"]["executedCorrelationType"] == "pearson"
    fingerprints = efa["splitValidation"]["executionFingerprints"]
    assert fingerprints["primary"] == fingerprints["train"]
    assert fingerprints["primary"] == fingerprints["holdout"]
    assert isinstance(efa["splitValidation"]["tuckerCongruence"], (int, float))


def test_cfa_r_runner_returns_fit_and_standardized_loadings() -> None:
    result = _run_measurement_fixture("questionnaire-cfa-clpm.spec.json")
    cfa = result["familyResult"]["cfa"]
    assert cfa["available"] is True
    assert cfa["converged"] is True
    assert cfa["itemCount"] == 6
    assert len(cfa["standardizedLoadings"]) == 6


def test_ordinal_cfa_r_runner_uses_wlsmv_thresholds() -> None:
    result = _run_measurement_fixture("questionnaire-cfa-ordinal-clpm.spec.json")
    cfa = result["familyResult"]["cfa"]
    assert cfa["available"] is True
    assert cfa["estimator"].endswith("WLSMV)")
    assert cfa["itemCount"] == 6


def test_measurement_invariance_r_runner_returns_selected_levels() -> None:
    result = _run_measurement_fixture("questionnaire-invariance-clpm.spec.json", add_group=True)
    invariance = result["familyResult"]["invariance"]
    assert invariance["available"] is True
    assert set(invariance["models"]) == {"configural", "metric", "scalar"}


def test_esem_runner_returns_a_method_specific_result() -> None:
    result = _run_measurement_fixture("questionnaire-esem-clpm.spec.json")
    esem = result["familyResult"]["esem"]
    assert esem["available"] is True
    assert esem["method"] == "ESEM_targetQ_declared_construct_target"
    assert esem["requestedRotation"] == "target"
    assert esem["executedRotation"] == "targetQ"
    assert esem["targetSource"] == "declared_construct_membership"
    assert esem["methodExecution"]["fallbackApplied"] is False
    assert esem["factorCount"] == 2
    assert len(esem["loadings"]) == 4


def test_binary_irt_fixture_returns_item_parameters_and_dif_diagnostics() -> None:
    result = _run_measurement_fixture(
        "questionnaire-irt-dif-binary.spec.json",
        add_group=True,
        binary_items=True,
    )
    irt = result["familyResult"]["irt"]
    assert irt["available"] is True
    assert irt["converged"] is True
    assert irt["estimator"] == "mirt_MML_2PL"
    assert irt["executedIrtModel"] == "2PL"
    assert irt["difStatus"] == "available"
    assert irt["difSampleSize"] == 100
    assert len(irt["itemParameters"]) == 6
    assert len(irt["difAnalysis"]) == 6
    assert {row["itemId"] for row in irt["difAnalysis"]} == {"x1", "y1", "x2", "y2", "x3", "y3"}


def test_ordinal_grm_fixture_returns_polytomous_parameters_and_dif() -> None:
    result = _run_measurement_fixture(
        "questionnaire-irt-dif-grm.spec.json",
        add_group=True,
    )
    irt = result["familyResult"]["irt"]
    assert irt["available"] is True
    assert irt["estimator"] == "mirt_MML_GRM"
    assert irt["executedIrtModel"] == "GRM"
    assert irt["difStatus"] == "available"
    assert all(row["itemType"] == "graded" for row in irt["itemParameters"])
    assert all(len(row["difficulties"]) >= 2 for row in irt["itemParameters"])
    assert all("pValueAdjusted" in row for row in irt["difAnalysis"])


def test_dif_group_rows_follow_the_item_complete_case_mask() -> None:
    result = _run_measurement_fixture(
        "questionnaire-irt-dif-binary.spec.json",
        add_group=True,
        binary_items=True,
        missing_item_subject_ids={1},
    )
    irt = result["familyResult"]["irt"]
    assert irt["available"] is True
    assert irt["sampleSize"] == 99
    assert irt["difSampleSize"] == 99
    assert irt["difStatus"] == "available"
    assert len(irt["difAnalysis"]) == 6


def test_esem_bifactor_irt_slice_reports_unsupported_irt_data_honestly() -> None:
    settings = get_settings()
    root = settings.project_root
    source_spec = json.loads(
        (root / "apps/api/tests/fixtures/advanced/questionnaire-cfa-clpm.spec.json").read_text(
            encoding="utf-8"
        )
    )
    source_spec["modelType"] = "esem_bifactor_irt"
    source_spec["analysisId"] = "measurement_esem_bifactor_irt_continuous_fixture"
    source_spec["name"] = "Continuous ESEM/Bifactor/IRT failure boundary fixture"
    source_spec["groupVariableId"] = "subject_id"
    source_spec["rotation"] = "target"

    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        source_data_path = root / "apps/api/tests/fixtures/advanced/longitudinal/clpm-three-wave.csv"
        input_path = work / "input.json"
        output_path = work / "output.json"
        input_path.write_text(
            json.dumps(
                {"spec": source_spec, "dataPath": str(source_data_path), "artifactDirectory": str(work)}
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["R_LIBS_USER"] = str(settings.r_library_path)
        completed = subprocess.run(
            [str(settings.rscript_path), "--vanilla", str(root / "engine/R/run_advanced_analysis.R"), str(input_path), str(output_path)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        result = json.loads(output_path.read_text(encoding="utf-8"))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert result["familyResult"]["irt"]["available"] is False
    assert "ORDERED_INTEGER_CATEGORIES" in result["familyResult"]["irt"]["reason"]
    warnings = {warning["code"]: warning["message"] for warning in result["warnings"]}
    assert "MEASUREMENT_IRT_UNAVAILABLE" in warnings
    assert "2PL/GRM" in warnings["MEASUREMENT_IRT_UNAVAILABLE"]
