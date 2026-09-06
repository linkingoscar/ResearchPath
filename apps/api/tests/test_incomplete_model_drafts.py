from __future__ import annotations

import pytest
from model_test_helpers import _model_dataset, _spec, client


@pytest.mark.parametrize("family,node_count", [("ols", 0), ("ols", 1), ("ols", 2), ("sem", 0)])
def test_incomplete_graph_is_saved_but_never_frozen(family: str, node_count: int) -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_4", dataset, measurement)
    model["nodes"] = model["nodes"][:node_count]
    model["edges"] = []
    model["moderations"] = []
    model["covariates"] = []
    model["estimation"]["family"] = family
    model["estimation"]["centering"]["nodeIds"] = []
    endpoint = f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}"
    saved = client.put(f"{endpoint}/draft", json={"model_spec": model})
    assert saved.status_code == 200, saved.text
    assert saved.json()["validation"]["valid"] is False
    assert saved.json()["validation"]["executionAvailable"] is False
    assert client.get(f"{endpoint}/draft").json()["modelSpec"] == model
    frozen = client.post(f"{endpoint}/freeze", json={"model_spec": model})
    assert frozen.status_code == 422, frozen.text


@pytest.mark.parametrize("invalid", ["unsafe_id", "unknown_field", "budget", "bad_type"])
def test_partial_draft_does_not_relax_field_safety(invalid: str) -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_4", dataset, measurement)
    model["edges"] = []
    if invalid == "unsafe_id":
        model["nodes"][0]["id"] = "../../elsewhere"
    elif invalid == "unknown_field":
        model["unexpected"] = True
    elif invalid == "budget":
        model["estimation"]["bootstrap"]["replicates"] = 999999999
    else:
        model["nodes"] = "not an array"
    endpoint = f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/draft"
    response = client.put(endpoint, json={"model_spec": model})
    assert response.status_code == 422, response.text
    assert client.get(endpoint).json() is None
