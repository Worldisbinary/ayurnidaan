from typer.testing import CliRunner

from ayurnidaan import cli, config


def test_audit_command_reports_verdicts(synthetic_settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: synthetic_settings)
    result = CliRunner().invoke(cli.app, ["--log-level", "WARNING", "audit"])
    assert result.exit_code == 0, result.output
    assert result.output.count("PASS") == 5


def test_settings_read_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("AYUR_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("AYUR_API_KEY", "k")
    s = config.Settings()
    assert s.artifacts_dir == tmp_path and s.api_key == "k"
    assert s.warehouse_path == tmp_path / "warehouse.duckdb"
