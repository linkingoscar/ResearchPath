from __future__ import annotations

import json
import time
from dataclasses import replace

import model_test_helpers
import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.settings import get_settings

pytestmark = pytest.mark.serial


@pytest.mark.parametrize("competing_jobs", [0, 2])
def test_repeated_bootstrap_cancellation_under_load(tmp_path, monkeypatch, competing_jobs):
    """Measure terminal API latency, not just event-setting or DELETE acceptance."""
    settings = replace(get_settings(), state_root=tmp_path / "state", r_worker_count=3)
    app = create_app(settings)
    services = app.state.services
    api = TestClient(app, headers={"X-ResearchPath-Token": settings.session_token})
    monkeypatch.setattr(model_test_helpers, "client", api)
    run_ids: list[str] = []
    timings: list[float] = []

    def wait_for(run_id, predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = api.get(f"/api/v1/analyses/{run_id}").json()
            assert state["status"] != "failed", state
            if predicate(state):
                return state
            time.sleep(0.02)
        pytest.fail(f"Task did not reach expected state: {state}")

    try:
        dataset, measurement = model_test_helpers._model_dataset(row_count=120)
        model = model_test_helpers._spec("model_7", dataset, measurement)
        model["estimation"]["bootstrap"]["replicates"] = 50000
        frozen = api.post(
            f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
            json={"model_spec": model, "override_reason": "重复取消与资源清理验证，不作实质推断。"},
        )
        assert frozen.status_code == 200, frozen.text
        endpoint = f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen.json()['version']}/analysis"

        def start():
            response = api.post(endpoint)
            assert response.status_code == 202, response.text
            run_id = response.json()["id"]
            run_ids.append(run_id)
            return run_id

        for _ in range(competing_jobs):
            wait_for(start(), lambda state: state.get("completedReplicates", 0) > 0)
        for iteration in range(5):
            run_id = start()
            # Include cold/repaired startup and an actually executing bootstrap.
            wait_for(run_id, lambda state, index=iteration: state["status"] == "running" if index % 2 == 0 else state.get("completedReplicates", 0) > 0)
            started = time.monotonic()
            assert api.delete(f"/api/v1/analyses/{run_id}").status_code == 200
            state = wait_for(run_id, lambda state: state["status"] == "cancelled", timeout=5)
            elapsed = time.monotonic() - started
            timings.append(elapsed)
            assert elapsed < 2.5, timings
            assert state["result"] is None
            assert state.get("resultPath") is None
            assert not (services.analysis_job_manager._path(run_id).parent / "work").exists()
            deadline = time.monotonic() + 1
            while run_id in services.analysis_job_manager.futures and time.monotonic() < deadline:
                time.sleep(0.01)
            assert run_id not in services.analysis_job_manager.futures
            assert run_id not in services.analysis_job_manager.events
        print(json.dumps({"competingJobs": competing_jobs, "cancelSeconds": timings, "maximum": max(timings)}))
    finally:
        for run_id in run_ids:
            api.delete(f"/api/v1/analyses/{run_id}")
        services.analysis_job_manager.close()
        processes = [worker.process for worker in services.r_worker_pool._workers]
        services.r_worker_pool.close()
        assert all(process.poll() is not None for process in processes)
        api.close()
