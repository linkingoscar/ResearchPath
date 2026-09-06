from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from model_test_helpers import _model_dataset, client
from test_empirical_center import _await_empirical_job, _fetch_full_report

from app.settings import get_settings


def test_multigroup_empirical_analysis_reports_robust_tests_and_games_howell() -> None:
    dataset, measurement = _model_dataset(group_count=3)
    group = next(
        variable for variable in dataset["variables"] if variable["originalName"] == "group"
    )
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
        json={"factor_count": 4, "group_variable_id": group["id"]},
    )

    meta = _await_empirical_job(response)
    report = _fetch_full_report(client, dataset["id"], measurement["version"], meta["reportId"])
    report["reportId"] = meta["reportId"]
    settings = get_settings()
    derived = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    for comparison in report["groupComparison"]["results"]:
        assert comparison["assumptionTests"]["brownForsythe"]["pValue"] is not None
        assert comparison["robustTest"]["method"] == "Welch one-way ANOVA"
        assert len(comparison["pairwiseGamesHowell"]) == 3
        outcome = derived[["group", comparison["id"]]].dropna()
        group_values = np.asarray(outcome["group"], dtype=str)
        outcome_values = np.asarray(outcome[comparison["id"]], dtype=float)
        group_levels = np.unique(group_values)
        grand_mean = outcome_values.mean()
        ss_between = sum(
            np.sum(group_values == level)
            * (outcome_values[group_values == level].mean() - grand_mean) ** 2
            for level in group_levels
        )
        ss_within = sum(
            np.sum(
                (
                    outcome_values[group_values == level]
                    - outcome_values[group_values == level].mean()
                )
                ** 2
            )
            for level in group_levels
        )
        df_between = len(group_levels) - 1
        df_within = len(outcome_values) - len(group_levels)
        mse = ss_within / df_within
        reference_omega_squared = (ss_between - df_between * mse) / (
            ss_between + ss_within + mse
        )
        assert comparison["omegaSquared"] == pytest.approx(reference_omega_squared, abs=1e-8)

    exported = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{report['reportId']}/export"
    )
    assert exported.status_code == 200, exported.text
    with ZipFile(BytesIO(exported.content)) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        assert "稳健组间检验" in workbook_xml
        assert "事后比较" in workbook_xml
