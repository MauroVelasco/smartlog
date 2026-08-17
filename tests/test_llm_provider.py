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
    yield
    config.LLM_PROVIDER = original_provider
    config.LLM_MODEL = original_model


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


def test_build_llm_unsupported_provider_raises(restore_llm_config):
    config.LLM_PROVIDER = "not-a-real-provider"

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        _build_llm()
