"""Shared test fixtures for aumai-otel-genai."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aumai_otel_genai.core import GenAIInstrumentor, GenAIMetricsCollector
from aumai_otel_genai.models import GenAIMetrics, GenAISpanAttributes


@pytest.fixture()
def in_memory_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture()
def instrumentor(
    in_memory_exporter: InMemorySpanExporter,
) -> Generator[GenAIInstrumentor, None, None]:
    inst = GenAIInstrumentor(exporter=in_memory_exporter, use_batch=False)
    yield inst
    inst.shutdown()


@pytest.fixture()
def collector() -> GenAIMetricsCollector:
    return GenAIMetricsCollector()


@pytest.fixture()
def span_attrs() -> GenAISpanAttributes:
    return GenAISpanAttributes(
        model="gpt-4",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.003,
        temperature=0.7,
        max_tokens=512,
        finish_reason="stop",
        latency_ms=250.0,
    )


@pytest.fixture()
def minimal_span_attrs() -> GenAISpanAttributes:
    return GenAISpanAttributes(
        model="claude-3",
        provider="anthropic",
    )
