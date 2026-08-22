"""Tests for correlation.langchain_agents._build_llm()'s provider selection.

No provider-branch tests existed before this change (anthropic/openai were
untested at this layer). This file adds coverage for the new pluggable
gemini branch (deferred change "B" from architecture/mvp-scope-and-llm-provider,
now implemented) without requiring real network credentials.
"""
import pytest

import config
from correlation.langchain_agents import _build_llm


@pytest.fixture
def restore_llm_config():
    original_provider = config.LLM_PROVIDER
    original_model = config.LLM_MODEL
    original_order = config.OPENROUTER_PROVIDER_ORDER
    original_fallbacks = config.OPENROUTER_ALLOW_FALLBACKS
    yield
    config.LLM_PROVIDER = original_provider
    config.LLM_MODEL = original_model
    config.OPENROUTER_PROVIDER_ORDER = original_order
    config.OPENROUTER_ALLOW_FALLBACKS = original_fallbacks


def test_build_llm_gemini_constructs_chat_google_generative_ai(restore_llm_config, monkeypatch):
    from langchain_google_genai import ChatGoogleGenerativeAI

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-construction-only")
    config.LLM_PROVIDER = "gemini"
    config.LLM_MODEL = "gemini-2.5-flash"

    llm = _build_llm()

    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model == "gemini-2.5-flash"
    assert llm.temperature == config.LLM_TEMPERATURE


def test_build_llm_gemini_defaults_model_when_llm_model_env_unset(restore_llm_config, monkeypatch):
    from langchain_google_genai import ChatGoogleGenerativeAI

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-construction-only")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    config.LLM_PROVIDER = "gemini"
    config.LLM_MODEL = "claude-sonnet-5"  # config.py's shared, Anthropic-flavored default

    llm = _build_llm()

    assert isinstance(llm, ChatGoogleGenerativeAI)
    # "gemini-2.5-flash" (the model this SDD change was originally scoped
    # around, per architecture/mvp-scope-and-llm-provider) returns 404
    # "no longer available to new users" for this API key as of 2026-08-16 —
    # discovered via a live harness run. "gemini-flash-latest" is Google's
    # stable rolling alias for the current recommended flash model, so it
    # does not go stale the same way a dated model id does.
    assert llm.model == "gemini-flash-latest"


def test_build_llm_openrouter_constructs_chat_openai(restore_llm_config, monkeypatch):
    from langchain_openai import ChatOpenAI

    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-construction-only")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.LLM_PROVIDER = "openrouter"
    config.LLM_MODEL = "openai/gpt-4o-mini"

    llm = _build_llm()

    assert isinstance(llm, ChatOpenAI)
    assert llm.openai_api_base == "https://openrouter.ai/api/v1"
    assert llm.model_name == "openai/gpt-4o-mini"
    assert llm.openai_api_key.get_secret_value() == "fake-key-for-construction-only"
    assert llm.temperature == config.LLM_TEMPERATURE


def test_build_llm_openrouter_defaults_model_when_llm_model_env_unset(restore_llm_config, monkeypatch):
    from langchain_openai import ChatOpenAI

    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-construction-only")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    config.LLM_PROVIDER = "openrouter"
    config.LLM_MODEL = "claude-sonnet-5"  # config.py's shared, Anthropic-flavored default

    llm = _build_llm()

    assert isinstance(llm, ChatOpenAI)
    # "openai/gpt-4o-mini" confirmed live via OpenRouter's /api/v1/models
    # listing to support "tools", "tool_choice", and "structured_outputs" in
    # supported_parameters — required since this pipeline calls
    # .with_structured_output(CorrelationResult) on whatever _build_llm()
    # returns.
    assert llm.model_name == "openai/gpt-4o-mini"


def test_build_llm_openrouter_does_not_fall_back_to_openai_api_key(restore_llm_config, monkeypatch):
    # ChatOpenAI's own validate_environment() falls back to OPENAI_API_KEY
    # whenever the resolved api_key is None — and that fallback lookup
    # triggers identically whether api_key was never passed OR explicitly
    # passed as None (see langchain_core.utils._gateway._resolve_gateway_config,
    # which only special-cases "api_key is not None"). Passing
    # os.getenv("OPENROUTER_API_KEY", "") keeps the value a non-None string
    # even when unset, so that OPENAI_API_KEY fallback lookup never runs.
    # An empty api_key then makes the underlying openai SDK client raise
    # immediately at construction — fail loud, never silently authenticate
    # against OpenRouter with an OPENAI_API_KEY-shaped credential from a
    # completely different provider.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-key-should-not-be-used")
    config.LLM_PROVIDER = "openrouter"
    config.LLM_MODEL = "openai/gpt-4o-mini"

    with pytest.raises(Exception, match="Missing credentials"):
        _build_llm()


def test_build_llm_unsupported_provider_raises(restore_llm_config):
    config.LLM_PROVIDER = "not-a-real-provider"

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        _build_llm()


def test_build_llm_openrouter_pins_backend_provider_routing(restore_llm_config, monkeypatch):
    """OpenRouter load-balances one model id across many backend providers,
    and several of them return tool-call arguments this pipeline cannot parse
    (measured 2026-08-21 on z-ai/glm-5.2: Mistral 0/3 valid, emitting raw
    '<tool_call>...<arg_key>' chat-template tokens; Friendli/Fireworks 3/3).
    Because .with_structured_output(CorrelationResult) parses those arguments,
    unpinned routing turns a correct run into a pydantic "Invalid JSON" error
    at random, so the routing block must actually reach the wire."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-construction-only")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.LLM_PROVIDER = "openrouter"
    config.LLM_MODEL = "z-ai/glm-5.2"
    config.OPENROUTER_PROVIDER_ORDER = ["Friendli", "Fireworks"]
    config.OPENROUTER_ALLOW_FALLBACKS = False

    llm = _build_llm()

    # "provider" is an OpenRouter extension, not an OpenAI Chat Completions
    # field, so it can only travel as extra_body — asserting on the config
    # value alone would still pass if the wiring were dropped.
    routing = llm.extra_body["provider"]
    assert routing["order"] == ["Friendli", "Fireworks"]
    assert routing["allow_fallbacks"] is False
    assert routing["require_parameters"] is True


def test_build_llm_openrouter_routing_follows_config_overrides(restore_llm_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-construction-only")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.LLM_PROVIDER = "openrouter"
    config.LLM_MODEL = "z-ai/glm-5.2"
    config.OPENROUTER_PROVIDER_ORDER = ["Fireworks"]
    config.OPENROUTER_ALLOW_FALLBACKS = True

    routing = _build_llm().extra_body["provider"]

    assert routing["order"] == ["Fireworks"]
    assert routing["allow_fallbacks"] is True
    # require_parameters stays on even with fallbacks enabled: it is what keeps
    # an escape-hatch fallback from landing on a provider that does not declare
    # tool/structured-output support at all.
    assert routing["require_parameters"] is True
