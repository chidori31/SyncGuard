import types

import groq
import httpx
import pytest

from tools.ai_helper import main, sanitize


@pytest.mark.parametrize(
    "secret",
    [
        'GROQ_API_KEY="synthetic-key-value"',
        'API_KEY_VALUE="synthetic-key-value"',
        'CLIENT_SECRET_V2="synthetic-secret-value"',
        'token_hash="synthetic-token-value"',
        '{"secrets": "synthetic-secret-value"}',
        'sort_keys="synthetic-secret-value"',
        "MY_TOKEN=synthetic-token-value",
        '{"password": "synthetic-password-value"}',
        "Authorization: Bearer synthetic-bearer-value",
        "postgresql+psycopg://someone:synthetic-password@server/db",
        "gsk_syntheticNotARealKey123456789",
        "eyJsynthetic.eyJpayload.signature",
        "-----BEGIN RSA PRIVATE KEY-----\nsynthetic-private-material\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_redaction(secret):
    assert "synthetic" not in sanitize(secret)
    assert "REDACTED" in sanitize(secret)


def test_env_secret_redacted(monkeypatch):
    monkeypatch.setenv("OTHER_SECRET", "a-value-without-recognizable-pattern")
    assert "a-value" not in sanitize("context a-value-without-recognizable-pattern")


def test_http_credential_url_is_redacted():
    assert "synthetic-password" not in sanitize("https://user:synthetic-password@example.test/private")


def test_code_identifiers_are_not_mistaken_for_credentials():
    source = "key = name.casefold()\njson.dumps(data, sort_keys=True)\n"
    assert sanitize(source) == source


def test_redaction_preserves_quoted_code_literal_syntax():
    result = sanitize('api_key = "synthetic-secret-value"')
    assert '"[REDACTED]"' in result and "synthetic" not in result


@pytest.mark.parametrize("finish,expected", [("stop", 0), ("length", 1)])
def test_delegated_code_is_only_returned_when_complete(monkeypatch, capsys, finish, expected):
    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            assert "delegated software engineer" in kwargs["messages"][0]["content"]
            assert kwargs["reasoning_effort"] == "low"
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(content="def result():\n    return 1"), finish_reason=finish
                    )
                ]
            )

    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key-value")
    monkeypatch.setattr(groq, "Groq", FakeClient)
    assert main(["implement", "Write a bounded synthetic function"]) == expected
    output = capsys.readouterr()
    if finish == "length":
        assert output.out == "" and "incomplete" in output.err
    else:
        assert "def result()" in output.out


def test_missing_key_is_safe(monkeypatch, capsys):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert main(["review", "synthetic prompt"]) == 2
    assert "set GROQ_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["429", "503", "401", "timeout", "network", "empty"])
def test_provider_failures(monkeypatch, capsys, failure):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 2
            self.chat = types.SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            assert kwargs["reasoning_effort"] == "medium"
            if failure.isnumeric():
                raise groq.APIStatusError(
                    "synthetic-secret-error", response=httpx.Response(int(failure), request=request), body=None
                )
            if failure == "timeout":
                raise groq.APITimeoutError(request=request)
            if failure == "network":
                raise groq.APIConnectionError(request=request)
            return types.SimpleNamespace(choices=[])

    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key-value")
    monkeypatch.setattr(groq, "Groq", FakeClient)
    assert main(["review", "synthetic prompt"]) == 1
    assert "synthetic-secret-error" not in capsys.readouterr().err
