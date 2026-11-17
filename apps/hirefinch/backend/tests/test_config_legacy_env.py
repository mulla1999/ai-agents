from hirefinch.config import get_settings


def test_pre_rename_env_names_still_apply(monkeypatch):
    monkeypatch.delenv("HIREFINCH_PUBLIC_URL", raising=False)
    monkeypatch.setenv("JOB_AGENT_PUBLIC_URL", "https://old-name.example.com")
    get_settings.cache_clear()
    try:
        assert get_settings().public_url == "https://old-name.example.com"
    finally:
        monkeypatch.delenv("HIREFINCH_PUBLIC_URL", raising=False)
        get_settings.cache_clear()


def test_new_env_name_wins_over_the_old_one(monkeypatch):
    monkeypatch.setenv("HIREFINCH_PUBLIC_URL", "https://new-name.example.com")
    monkeypatch.setenv("JOB_AGENT_PUBLIC_URL", "https://old-name.example.com")
    get_settings.cache_clear()
    try:
        assert get_settings().public_url == "https://new-name.example.com"
    finally:
        get_settings.cache_clear()
