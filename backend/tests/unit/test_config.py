"""Configuration must load from the documented .env formats (regression: comma lists crashed startup)."""

from app.core.config import Settings


def test_cors_origins_comma_separated_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000")
    s = Settings(_env_file=None)
    assert s.cors_origin_list == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_cors_origins_json_list_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.test","http://b.test"]')
    assert Settings(_env_file=None).cors_origin_list == ["http://a.test", "http://b.test"]


def test_env_example_file_loads(tmp_path, monkeypatch):
    """The shipped .env.example must parse cleanly - it is what `cp .env.example .env` produces."""
    import pathlib

    example = pathlib.Path(__file__).resolve().parents[3] / ".env.example"
    for key in ("CORS_ORIGINS", "DATABASE_URL", "SECRET_KEY", "ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=str(example))
    assert s.cors_origin_list and s.llm_provider == "mock"
