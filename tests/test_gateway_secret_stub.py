from pathlib import Path
from types import SimpleNamespace
import importlib

import pytest

from runta_agent_eval.core.config import Settings
from runta_agent_eval.runta.gateway import RuntaGateway


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        runta_token="rt_test",
        openai_api_key="sk_test",
        openai_model="gpt-5-mini",
        openai_api_url="https://api.openai.com/v1/responses",
        app_host="0.0.0.0",
        app_port=8000,
        database_path=tmp_path / "db.sqlite3",
        artifact_dir=tmp_path / "artifacts",
        experiment_dir=tmp_path / "experiments",
        runta_vcpus=1,
        runta_memory_mib=1024,
        runta_memory_max_mib=2048,
        runta_keep_runtimes=True,
        runta_secret_name="openai-api-key",
        runta_idle_suspend_secs=0,
        max_candidates=12,
        agent_max_steps=24,
    )


class FakeRuntime:
    def __init__(self, runtime_id: str):
        self.id = runtime_id
        self.waited = False

    async def wait_until_ready(self, *, timeout, poll_interval):
        self.waited = True
        assert timeout == 240.0
        assert poll_interval == 0.5


class FakeRuntimes:
    def __init__(self):
        self.got = None
        self.runtime = None

    async def get(self, runtime_id):
        self.got = runtime_id
        self.runtime = FakeRuntime(runtime_id)
        return self.runtime


@pytest.mark.asyncio
async def test_checkpoint_candidate_created_atomically_with_secret_configuration(monkeypatch, tmp_path: Path):
    captured = {}

    class FakeResponse:
        status_code = 201
        text = '{"data":{"id":"runtime-123"}}'
        def json(self):
            return {"data": {"id": "runtime-123"}}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return None
        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    gateway_module = importlib.import_module("runta_agent_eval.runta.gateway")
    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", FakeAsyncClient)

    gateway = RuntaGateway(_settings(tmp_path))
    gateway._openai_secret_id = "secret-uuid-123"
    runtimes = FakeRuntimes()
    gateway.client = SimpleNamespace(runtimes=runtimes)
    gateway._runta_module = SimpleNamespace()

    handle = await gateway.create_runtime(
        "candidate-1",
        checkpoint_id="checkpoint-abc",
        allowed_hosts=["api.openai.com"],
        with_openai_secret=True,
    )

    assert captured["url"] == "https://api.runta.com/v2/runtimes"
    assert captured["headers"]["Authorization"] == "Bearer rt_test"
    body = captured["json"]
    assert body["name"] == "candidate-1"
    assert body["checkpoint_id"] == "checkpoint-abc"
    assert "resources" not in body
    assert body["egress_policy"] == {"mode": "allowlist", "allowed_hosts": ["api.openai.com"]}
    assert body["idle_policy"] == {"mode": "disabled"}
    assert body["secret_configuration"] == [
        {
            "secret_id": "secret-uuid-123",
            "environment": [],
            "egress_rules": [
                {
                    "host_pattern": "api.openai.com",
                    "path_pattern": "/v1/*",
                    "action": "header",
                    "name": "Authorization",
                    "value_template": "Bearer ${secret}",
                }
            ],
            "files": [],
        }
    ]
    assert runtimes.got == "runtime-123"
    assert runtimes.runtime.waited is True
    assert handle.id == "runtime-123"


@pytest.mark.asyncio
async def test_fresh_judge_created_atomically_with_resources_and_secret(monkeypatch, tmp_path: Path):
    captured = {}

    class FakeResponse:
        status_code = 201
        text = '{"data":{"id":"judge-123"}}'
        def json(self): return {"data": {"id": "judge-123"}}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): return None
        async def post(self, url, *, headers, json):
            captured["json"] = json
            return FakeResponse()

    gateway_module = importlib.import_module("runta_agent_eval.runta.gateway")
    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", FakeAsyncClient)

    gateway = RuntaGateway(_settings(tmp_path))
    gateway._openai_secret_id = "secret-uuid-123"
    runtimes = FakeRuntimes()
    gateway.client = SimpleNamespace(runtimes=runtimes)
    gateway._runta_module = SimpleNamespace()

    await gateway.create_runtime(
        "judge",
        allowed_hosts=["api.openai.com"],
        memory_mib=512,
        memory_max_mib=1024,
        with_openai_secret=True,
    )

    body = captured["json"]
    assert "checkpoint_id" not in body
    assert body["resources"] == {
        "requests": {"vcpus": 1, "memory_mib": 512},
        "limits": {"memory_mib": 1024},
    }
    assert body["secret_configuration"][0]["secret_id"] == "secret-uuid-123"


@pytest.mark.asyncio
async def test_atomic_secret_create_rejects_missing_secret_id(tmp_path: Path):
    gateway = RuntaGateway(_settings(tmp_path))
    gateway.client = SimpleNamespace()
    gateway._runta_module = SimpleNamespace()

    with pytest.raises(RuntimeError, match="ensure_openai_secret"):
        await gateway.create_runtime(
            "candidate",
            checkpoint_id="cp",
            allowed_hosts=["api.openai.com"],
            with_openai_secret=True,
        )


def test_openai_secret_configuration_uses_runta_secret_placeholder():
    from types import SimpleNamespace
    from runta_agent_eval.runta.gateway import RuntaGateway

    gateway = object.__new__(RuntaGateway)
    gateway._openai_secret_id = "secret-123"
    cfg = gateway._openai_secret_configuration()
    template = cfg[0]["egress_rules"][0]["value_template"]
    assert template == "Bearer ${secret}"
    assert template.count("${secret}") == 1
    assert "${credential}" not in template
