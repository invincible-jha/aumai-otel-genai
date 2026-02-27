"""Tests for aumai-otel-genai CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from aumai_otel_genai.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def usage_jsonl(tmp_path: Path) -> Path:
    """Write a JSONL file of usage events."""
    events = [
        {
            "provider": "openai",
            "model": "gpt-4",
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 250.0,
            "error": False,
        },
        {
            "provider": "openai",
            "model": "gpt-4",
            "input_tokens": 200,
            "output_tokens": 100,
            "latency_ms": 400.0,
            "error": False,
        },
        {
            "provider": "anthropic",
            "model": "claude-3",
            "input_tokens": 150,
            "output_tokens": 75,
            "latency_ms": 300.0,
            "error": True,
        },
    ]
    f = tmp_path / "usage.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in events))
    return f


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def test_cli_version(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


# ---------------------------------------------------------------------------
# instrument command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider",
    ["openai", "anthropic", "cohere", "google", "mistral", "custom"],
)
def test_instrument_command_all_providers(
    runner: CliRunner, provider: str
) -> None:
    result = runner.invoke(
        main,
        ["instrument", "--provider", provider, "--exporter", "memory"],
    )
    assert result.exit_code == 0
    assert provider in result.output


def test_instrument_command_console_exporter(runner: CliRunner) -> None:
    result = runner.invoke(
        main,
        ["instrument", "--provider", "openai", "--exporter", "console"],
    )
    assert result.exit_code == 0
    assert "console" in result.output


def test_instrument_command_memory_exporter(runner: CliRunner) -> None:
    result = runner.invoke(
        main,
        ["instrument", "--provider", "openai", "--exporter", "memory"],
    )
    assert result.exit_code == 0
    assert "memory" in result.output


def test_instrument_command_demo_flag(runner: CliRunner) -> None:
    result = runner.invoke(
        main,
        [
            "instrument",
            "--provider", "openai",
            "--exporter", "memory",
            "--demo",
        ],
    )
    assert result.exit_code == 0
    assert "Demo span emitted" in result.output


def test_instrument_requires_provider(runner: CliRunner) -> None:
    result = runner.invoke(main, ["instrument"])
    assert result.exit_code != 0


def test_instrument_invalid_provider(runner: CliRunner) -> None:
    result = runner.invoke(
        main, ["instrument", "--provider", "unknown-provider"]
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# metrics command
# ---------------------------------------------------------------------------


def test_metrics_command_no_usage_file_prometheus(
    runner: CliRunner,
) -> None:
    result = runner.invoke(main, ["metrics", "--format", "prometheus"])
    assert result.exit_code == 0
    assert "genai_requests_total" in result.output
    assert "TYPE" in result.output


def test_metrics_command_no_usage_file_json(runner: CliRunner) -> None:
    result = runner.invoke(main, ["metrics", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_metrics_command_with_usage_file_prometheus(
    runner: CliRunner, usage_jsonl: Path
) -> None:
    result = runner.invoke(
        main,
        ["metrics", "--usage", str(usage_jsonl), "--format", "prometheus"],
    )
    assert result.exit_code == 0
    assert 'provider="openai"' in result.output
    assert 'provider="anthropic"' in result.output
    assert "genai_requests_total" in result.output


def test_metrics_command_with_usage_file_json(
    runner: CliRunner, usage_jsonl: Path
) -> None:
    result = runner.invoke(
        main,
        ["metrics", "--usage", str(usage_jsonl), "--format", "json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "openai/gpt-4" in data
    assert "anthropic/claude-3" in data


def test_metrics_token_counts_in_output(
    runner: CliRunner, usage_jsonl: Path
) -> None:
    result = runner.invoke(
        main,
        ["metrics", "--usage", str(usage_jsonl), "--format", "json"],
    )
    data = json.loads(result.output)
    openai_metrics = data["openai/gpt-4"]
    # 2 requests: (100+50) + (200+100) = 450 tokens
    assert openai_metrics["token_count"] == 450
    assert openai_metrics["request_count"] == 2


def test_metrics_error_count(
    runner: CliRunner, usage_jsonl: Path
) -> None:
    result = runner.invoke(
        main,
        ["metrics", "--usage", str(usage_jsonl), "--format", "json"],
    )
    data = json.loads(result.output)
    anthropic_metrics = data["anthropic/claude-3"]
    assert anthropic_metrics["error_count"] == 1


def test_metrics_command_skips_blank_lines(
    runner: CliRunner, tmp_path: Path
) -> None:
    f = tmp_path / "usage.jsonl"
    f.write_text(
        '\n{"provider":"openai","model":"gpt-4","input_tokens":10,'
        '"output_tokens":5,"latency_ms":100,"error":false}\n\n'
    )
    result = runner.invoke(
        main, ["metrics", "--usage", str(f), "--format", "json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["openai/gpt-4"]["request_count"] == 1


# ---------------------------------------------------------------------------
# help text
# ---------------------------------------------------------------------------


def test_help_text(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "instrument" in result.output
    assert "metrics" in result.output


def test_instrument_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["instrument", "--help"])
    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--exporter" in result.output
    assert "--demo" in result.output


def test_metrics_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["metrics", "--help"])
    assert result.exit_code == 0
    assert "--usage" in result.output
    assert "--format" in result.output
