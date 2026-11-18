"""Models staff add in the console: everything needed to call one, its own key and charges, and
which one is the default (and which writes emails), live without a restart."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.config import Settings
from outbound.domain.enums import PlatformRole
from outbound.services.vendors import VendorService
from tests.api.conftest import Api, add_user, sign_in
from tests.api.test_admin import audited

STAFF = "models@platform.example"
KEY = "placeholder-model-key-9876"
DEEPSEEK = {
    "label": "DeepSeek V3 on DeepInfra",
    "provider": "openai_compatible",
    "model": "deepseek-ai/DeepSeek-V3",
    "base_url": "https://api.deepinfra.com/v1/openai",
    "temperature": 0.5,
    "max_tokens": 6000,
    "reasoning_effort": "",
    "input_credits": 30,
    "output_credits": 110,
    "api_key": KEY,
}


@pytest.fixture
def staff(app_and_services: tuple[FastAPI, Services]) -> Api:
    app, _ = app_and_services
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)
    return sign_in(app, STAFF)


def service(services: Services, base: Settings | None = None) -> VendorService:
    return VendorService(services.container.platform, base or Settings(_env_file=None))


def test_the_form_knows_every_kind_of_provider(staff: Api) -> None:
    listing = staff.get("/api/admin/vendors").json()
    providers = {p["code"]: p for p in listing["providers"]}
    assert set(providers) == {
        "openai_compatible", "openai", "anthropic", "gemini", "ollama", "github_copilot",
    }  # fmt: skip
    assert providers["openai_compatible"]["needs_base_url"] is True
    assert providers["ollama"]["needs_key"] is False
    assert providers["openai"]["default_base_url"].startswith("https://")
    assert listing["models"] == [] and listing["default_model"] == ""


def test_a_model_is_added_with_its_own_key_never_shown_and_audited(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    _, services = app_and_services
    out = staff.put("/api/admin/models/deepseek-v3", json=DEEPSEEK)
    assert out.status_code == 200 and KEY not in out.text
    [model] = out.json()["models"]
    assert (model["code"], model["provider"], model["key"]) == (
        "deepseek-v3",
        "openai_compatible",
        "••••9876",
    )
    assert (model["input_credits"], model["output_credits"]) == (30, 110)
    # Changing it without a key keeps the key.
    changed = staff.put(
        "/api/admin/models/deepseek-v3", json={**DEEPSEEK, "temperature": 0.2, "api_key": None}
    ).json()["models"][0]
    assert changed["temperature"] == 0.2 and changed["key"] == "••••9876"
    entries = audited(services, "model_saved")
    assert len(entries) == 2 and KEY not in str(entries)


def test_a_model_must_say_everything_its_provider_needs(staff: Api) -> None:
    url = "/api/admin/models/m1"
    assert staff.put(url, json={**DEEPSEEK, "base_url": ""}).status_code == 422  # compatible
    assert staff.put(url, json={**DEEPSEEK, "provider": "nonsense"}).status_code == 422
    assert staff.put(url, json={**DEEPSEEK, "base_url": "ftp://x"}).status_code == 422
    assert staff.put(url, json={**DEEPSEEK, "reasoning_effort": "max"}).status_code == 422
    keyless = staff.put(url, json={**DEEPSEEK, "api_key": None})
    assert keyless.status_code == 200  # saved; it cannot be the default without a key
    choose = {"default_model": "m1"}
    assert staff.put("/api/admin/models/default", json=choose).status_code == 422
    assert staff.put("/api/admin/models/bad code", json=DEEPSEEK).status_code == 422
    local = {**DEEPSEEK, "provider": "ollama", "base_url": "", "model": "llama3", "api_key": None}
    assert staff.put("/api/admin/models/local", json=local).status_code == 200  # needs no key


def test_the_default_model_drives_every_model_call_and_its_charge_counts(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    _, services = app_and_services
    staff.put("/api/admin/models/deepseek-v3", json=DEEPSEEK)
    writer = {**DEEPSEEK, "label": "R1 writer", "model": "deepseek-ai/DeepSeek-R1", "api_key": None}
    staff.put("/api/admin/models/deepseek-r1", json=writer)
    before, _ = service(services).effective_settings()
    assert before.llm_model != DEEPSEEK["model"]  # nothing chosen: the environment's settings
    chosen = staff.put(
        "/api/admin/models/default",
        json={"default_model": "deepseek-v3", "writer_model": "deepseek-r1"},
    ).json()
    assert (chosen["default_model"], chosen["writer_model"]) == ("deepseek-v3", "deepseek-r1")
    live, _ = service(services).effective_settings()
    assert (live.llm_provider, live.llm_model, live.llm_base_url) == (
        "openai_compatible",
        "deepseek-ai/DeepSeek-V3",
        "https://api.deepinfra.com/v1/openai",
    )
    assert (live.llm_temperature, live.llm_max_tokens) == (0.5, 6000)
    assert live.llm_copy_model == "deepseek-ai/DeepSeek-R1"
    assert live.llm_api_key.get_secret_value() == KEY
    with services.container.platform() as p:
        settings, _ = p.settings.get()
    assert settings.charge("deepseek-ai/DeepSeek-V3") == (30.0, 110.0)
    assert len(audited(services, "models_chosen")) == 1


def test_a_chosen_model_cannot_be_removed_and_unknown_or_mismatched_choices_are_refused(
    staff: Api,
) -> None:
    staff.put("/api/admin/models/deepseek-v3", json=DEEPSEEK)
    other = {**DEEPSEEK, "provider": "openai", "base_url": "", "model": "gpt-5"}
    staff.put("/api/admin/models/gpt", json=other)
    choose = "/api/admin/models/default"
    assert staff.put(choose, json={"default_model": "ghost"}).status_code == 422
    assert staff.put(choose, json={"writer_model": "gpt"}).status_code == 422  # no default
    mismatched = {"default_model": "deepseek-v3", "writer_model": "gpt"}
    assert staff.put(choose, json=mismatched).status_code == 422  # another provider
    staff.put(choose, json={"default_model": "deepseek-v3"})
    assert staff.delete("/api/admin/models/deepseek-v3").status_code == 422
    assert staff.delete("/api/admin/models/gpt").status_code == 200
    back = staff.put(choose, json={"default_model": ""}).json()  # back to the environment's
    assert back["default_model"] == "" and [m["code"] for m in back["models"]] == ["deepseek-v3"]


def test_testing_a_model_makes_one_tiny_call_with_its_own_settings(
    staff: Api, app_and_services: tuple[FastAPI, Services]
) -> None:
    _, services = app_and_services
    staff.put("/api/admin/models/deepseek-v3", json=DEEPSEEK)
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 1}}  # fmt: skip
        return httpx.Response(200, json=reply)

    client = httpx.Client(transport=httpx.MockTransport(answer))
    result = service(services).test_model("deepseek-v3", by=None, client=client)
    assert result.ok is True
    [request] = seen
    assert str(request.url).startswith("https://api.deepinfra.com/v1/openai")
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert b"deepseek-ai/DeepSeek-V3" in request.content


def test_platform_staff_without_keys_rights_and_customers_cannot_touch_models(api: Api) -> None:
    assert api.put("/api/admin/models/x", json=DEEPSEEK).status_code == 403
    assert api.put("/api/admin/models/default", json={"default_model": ""}).status_code == 403
