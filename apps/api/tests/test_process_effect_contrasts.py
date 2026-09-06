from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from model_test_helpers import _await_analysis, _model_dataset, _spec, client

from app.settings import get_settings


def test_model_6_bootstraps_pairwise_specific_indirect_effect_contrasts() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_6", dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 1000
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={
            "model_spec": model,
            "override_reason": "横截面模型仅比较特定间接关联，不作因果机制结论。",
        },
    ).json()
    result = _await_analysis(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
        )
    )["result"]

    settings = get_settings()
    data = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    values = np.asarray(data[["scale_x", "scale_m", "scale_y", "scale_w", "age"]], dtype=float)
    x, m1, m2, y, age = (values[:, index] for index in range(values.shape[1]))
    m1_beta = np.linalg.lstsq(np.column_stack([np.ones(len(x)), x, age]), m1, rcond=None)[0]
    m2_beta = np.linalg.lstsq(
        np.column_stack([np.ones(len(x)), x, m1, age]), m2, rcond=None
    )[0]
    y_beta = np.linalg.lstsq(
        np.column_stack([np.ones(len(x)), x, m1, m2, age]), y, rcond=None
    )[0]
    indirects = np.asarray(
        [
            m1_beta[1] * y_beta[2],
            m2_beta[1] * y_beta[3],
            m1_beta[1] * m2_beta[2] * y_beta[3],
        ]
    )
    expected = {
        "effect_contrast_ind1_ind2": indirects[0] - indirects[1],
        "effect_contrast_ind1_ind3": indirects[0] - indirects[2],
        "effect_contrast_ind2_ind3": indirects[1] - indirects[2],
    }
    contrasts = {
        effect["id"]: effect for effect in result["effects"] if effect["type"] == "contrast"
    }

    assert contrasts.keys() == expected.keys()
    for effect_id, estimate in expected.items():
        assert contrasts[effect_id]["estimate"] == pytest.approx(estimate, abs=1e-8)
        interval = contrasts[effect_id]["confidenceInterval"]
        assert interval["replicates"] == 1000
        assert interval["lower"] < interval["upper"]
