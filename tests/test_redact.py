from tgmcp_desk.core.redact import REDACTED, redact_env, redact_text


def test_redact_env_hides_secrets_and_ids():
    env = {
        "TELEGRAM_API_ID": "12345678",
        "TELEGRAM_API_HASH": "0123456789abcdef0123456789abcdef",
        "TELEGRAM_SESSION_NAME": "telegram_session",
        "TELEGRAM_ALLOWED_CHAT_IDS": "-1001234567890,@somechannel",
        "TELEGRAM_PROXY_PASSWORD": "pw",
        "TELEGRAM_PROXY_HOST": "127.0.0.1",
        "MCP_PORT": "18765",
        "TELEGRAM_EXPOSED_TOOLS": "read-only-list_contacts",
    }
    out = redact_env(env)
    for k in [
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_SESSION_NAME",
        "TELEGRAM_ALLOWED_CHAT_IDS",
        "TELEGRAM_PROXY_PASSWORD",
    ]:
        assert out[k] == REDACTED
    assert out["TELEGRAM_PROXY_HOST"] == "127.0.0.1"
    assert out["MCP_PORT"] == "18765"
    assert out["TELEGRAM_EXPOSED_TOOLS"] == "read-only-list_contacts"


def test_redact_text():
    text = (
        "chat -1001234567890 user 987654321 phone +86 138 0000 0000 @someone "
        "hash 0123456789abcdef0123456789abcdef C:\\Users\\alice\\x 127.0.0.1:18765 "
        "session 1" + "A" * 200
    )
    out = redact_text(text)
    for secret in [
        "1234567890",
        "987654321",
        "138",
        "@someone",
        "0123456789abcdef",
        "alice",
        "AAAA",
    ]:
        assert secret not in out, secret
    assert "127.0.0.1:18765" in out
