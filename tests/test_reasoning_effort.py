"""Reasoning capabilities, persisted settings, and outgoing request mapping."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from clanker.config.models import ModelConfig, create_llm_from_config
from clanker.config.reasoning import reasoning_capabilities, validate_reasoning_effort
from clanker.config.web.app import create_app


@pytest.mark.parametrize(('provider', 'model', 'levels'), [
    ('GitHubCopilot', 'gpt-6.1-sol', ['low', 'medium', 'high', 'xhigh', 'max']),
    ('OpenAI', 'gpt-6-astra', ['low', 'medium', 'high', 'xhigh', 'max']),
    ('OpenAI', 'gpt-5.2-codex', ['low', 'medium', 'high', 'xhigh']),
    ('OpenAI', 'gpt-5.2-pro', ['medium', 'high', 'xhigh']),
    ('OpenAI', 'gpt-5', ['minimal', 'low', 'medium', 'high']),
    ('AzureOpenAI', 'gpt-5.1', ['none', 'low', 'medium', 'high']),
    ('GitHubCopilot', 'gpt-5.2', ['none', 'low', 'medium', 'high', 'xhigh']),
    ('OpenAI', 'gpt-5.5', ['none', 'low', 'medium', 'high', 'xhigh']),
    ('OpenAI', 'o3-mini', ['low', 'medium', 'high']),
    ('OpenAI', 'gpt-4o', []),
    ('Anthropic', 'claude-opus-4-5', ['low', 'medium', 'high']),
    ('Anthropic', 'claude-sonnet-4-6', ['low', 'medium', 'high', 'max']),
    ('Anthropic', 'claude-opus-4-7', ['low', 'medium', 'high', 'xhigh', 'max']),
    ('Anthropic', 'claude-sonnet-4-20250514', []),
    ('GitHubCopilot', 'claude-sonnet-4.6', []),
    ('Ollama', 'qwen3', []),
    ('Antigravity', 'gemini-3.8-flash-tiered', []),
])
def test_capabilities(provider, model, levels):
    assert reasoning_capabilities(provider, model)['levels'] == levels


def test_defaults_and_invalid_effort():
    config = ModelConfig(name='test', provider='OpenAI', model='gpt-4o')
    assert ModelConfig(**config.model_dump()).reasoning_effort is None
    validate_reasoning_effort('OpenAI', 'gpt-4o', None)
    with pytest.raises(ValueError, match='Unsupported reasoning_effort'):
        validate_reasoning_effort('OpenAI', 'gpt-4o', 'high')
    with pytest.raises(ValueError):
        validate_reasoning_effort('Anthropic', 'claude-opus-4-6', 'xhigh')
    validate_reasoning_effort('AzureOpenAI', None, 'high', 'my-deployment')
    validate_reasoning_effort('OpenAI', 'custom-proxy-model', 'xhigh')


@pytest.mark.parametrize('responses', [False, True])
def test_openai_payload(monkeypatch, responses):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    model = create_llm_from_config(ModelConfig(
        name='test', provider='OpenAI', model='gpt-5.2',
        reasoning_effort='xhigh', use_responses_api=responses,
    ))
    payload = model._get_request_payload([HumanMessage(content='Hello')])
    if responses:
        assert payload['reasoning']['effort'] == 'xhigh'
    else:
        assert payload['reasoning_effort'] == 'xhigh'


@pytest.mark.parametrize(('model_id', 'thinking', 'effort', 'expected'), [
    ('claude-opus-4-6', True, 'max', {'type': 'adaptive'}),
    ('claude-opus-4-5', True, 'medium', {'type': 'enabled', 'budget_tokens': 10000}),
    ('claude-sonnet-4-6', False, 'low', None),
])
def test_anthropic_payload(monkeypatch, model_id, thinking, effort, expected):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    model = create_llm_from_config(ModelConfig(
        name='test', provider='Anthropic', model=model_id,
        reasoning_effort=effort, thinking_enabled=thinking,
    ))
    payload = model._get_request_payload([HumanMessage(content='Hello')])
    assert payload['output_config'] == {'effort': effort}
    assert payload.get('thinking') == expected


def test_unsupported_rejected_before_provider_auth():
    with pytest.raises(ValueError, match='Unsupported reasoning_effort'):
        create_llm_from_config(ModelConfig(
            name='test', provider='Antigravity', model='gemini', reasoning_effort='high',
        ))


def test_capability_endpoint_and_save_validation():
    client = TestClient(create_app())
    response = client.get('/api/models/reasoning-capabilities', params={
        'provider': 'Anthropic', 'model': 'claude-sonnet-4-6',
    })
    assert response.status_code == 200
    assert response.json()['adaptive_thinking'] is True
    assert 'max' in response.json()['levels']
    with patch('clanker.config.web.routes.add_model') as save:
        response = client.post('/api/models', json={
            'name': 'test', 'provider': 'OpenAI', 'model': 'gpt-4o', 'reasoning_effort': 'high',
        })
        assert response.status_code == 422
        save.assert_not_called()
        response = client.post('/api/models', json={
            'name': 'test', 'provider': 'Anthropic', 'model': 'claude-opus-4-6', 'reasoning_effort': 'max',
        })
        assert response.status_code == 200
        assert save.call_args.args[0].reasoning_effort == 'max'


@pytest.mark.parametrize('provider', ['AzureOpenAI', 'GitHubCopilot'])
def test_other_openai_compatible_payloads(monkeypatch, provider):
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'test-key')
    config = ModelConfig(
        name='test', provider=provider, model='gpt-5.2', reasoning_effort='high',
        deployment_name='deployment', base_url='https://example.openai.azure.com',
        api_version='2024-10-21',
    )
    with patch('clanker.config.copilot_auth.get_valid_copilot_token', return_value='test-token'):
        model = create_llm_from_config(config)
    payload = model._get_request_payload([HumanMessage(content='Hello')])
    if provider == 'GitHubCopilot':
        assert payload['reasoning']['effort'] == 'high'
    else:
        assert payload['reasoning_effort'] == 'high'


def test_update_rejects_unsupported_effort_without_saving():
    client = TestClient(create_app())
    existing = ModelConfig(name='test', provider='OpenAI', model='gpt-5.2')
    with patch('clanker.config.web.routes.get_model_by_name', return_value=existing), patch(
        'clanker.config.web.routes.add_model'
    ) as save:
        response = client.put('/api/models/test', json={
            'name': 'test', 'provider': 'OpenAI', 'model': 'gpt-5.2', 'reasoning_effort': 'minimal',
        })
    assert response.status_code == 422
    save.assert_not_called()
