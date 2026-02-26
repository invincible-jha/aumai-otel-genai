"""CLI entry point for aumai-otel-genai."""

from __future__ import annotations

import json
import time
from pathlib import Path

import click

from .core import GenAIInstrumentor, GenAIMetricsCollector
from .models import GenAISpanAttributes


@click.group()
@click.version_option()
def main() -> None:
    """AumAI OTel GenAI — standard GenAI telemetry instrumentation."""


@main.command("instrument")
@click.option(
    "--provider",
    required=True,
    type=click.Choice(["openai", "anthropic", "cohere", "google", "mistral", "custom"]),
    help="LLM provider to instrument.",
)
@click.option(
    "--exporter",
    "exporter_type",
    default="console",
    show_default=True,
    type=click.Choice(["console", "memory"]),
    help="OTel span exporter backend.",
)
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="Emit a demo span to verify instrumentation.",
)
def instrument_command(
    provider: str, exporter_type: str, demo: bool
) -> None:
    """Set up OTel instrumentation for an LLM provider."""
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = (
        InMemorySpanExporter() if exporter_type == "memory" else ConsoleSpanExporter()
    )
    instrumentor = GenAIInstrumentor(exporter=exporter)
    instrumentor.instrument(provider)
    click.echo(f"Instrumented provider: {provider}")
    click.echo(f"Exporter             : {exporter_type}")

    if demo:
        attrs = GenAISpanAttributes(
            model="demo-model",
            provider=provider,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.002,
            temperature=0.7,
            finish_reason="stop",
            latency_ms=0.0,
        )
        with instrumentor.create_span("chat.completions", attrs) as span:
            time.sleep(0.01)
            span.set_attribute("demo", True)
        click.echo("Demo span emitted.")

    instrumentor.shutdown()


@main.command("metrics")
@click.option(
    "--usage",
    "usage_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="JSONL file of usage events to load and summarize.",
)
@click.option(
    "--format",
    "output_fmt",
    default="prometheus",
    show_default=True,
    type=click.Choice(["prometheus", "json"]),
    help="Output format.",
)
def metrics_command(usage_path: str | None, output_fmt: str) -> None:
    """Collect and display GenAI metrics."""
    collector = GenAIMetricsCollector()

    if usage_path:
        for line in Path(usage_path).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            collector.record(
                provider=event.get("provider", "unknown"),
                model=event.get("model", "unknown"),
                input_tokens=int(event.get("input_tokens", 0)),
                output_tokens=int(event.get("output_tokens", 0)),
                latency_ms=float(event.get("latency_ms", 0.0)),
                error=bool(event.get("error", False)),
            )

    if output_fmt == "prometheus":
        click.echo(collector.render_prometheus())
    else:
        all_m = {
            k: v.model_dump() for k, v in collector.all_metrics().items()
        }
        click.echo(json.dumps(all_m, indent=2))


if __name__ == "__main__":
    main()
