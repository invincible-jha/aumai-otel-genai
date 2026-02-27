"""Core logic for aumai-otel-genai."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Span, StatusCode

from .models import GenAIMetrics, GenAISpanAttributes

__all__ = [
    "GenAIInstrumentor",
    "GenAISpanProcessor",
    "GenAIMetricsCollector",
]

_LIBRARY_NAME = "aumai.otel-genai"
_LIBRARY_VERSION = "0.1.0"


class GenAIMetricsCollector:
    """
    Collects and exposes Prometheus-compatible metrics for GenAI calls.

    Metrics are accumulated in a ``GenAIMetrics`` instance and can be
    rendered as Prometheus text format via ``render_prometheus()``.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, GenAIMetrics] = {}

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        error: bool = False,
    ) -> None:
        """Record metrics for a single GenAI request."""
        key = f"{provider}/{model}"
        if key not in self._metrics:
            self._metrics[key] = GenAIMetrics()
        self._metrics[key].record_request(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            error=error,
        )

    def get_metrics(self, provider: str, model: str) -> GenAIMetrics:
        """Return the accumulated metrics for a provider/model pair."""
        key = f"{provider}/{model}"
        return self._metrics.get(key, GenAIMetrics())

    def all_metrics(self) -> dict[str, GenAIMetrics]:
        """Return all collected metrics keyed by 'provider/model'."""
        return dict(self._metrics)

    def render_prometheus(self) -> str:
        """
        Render metrics in Prometheus text format (exposition format v0.0.4).

        Example output::

            # HELP genai_requests_total Total GenAI requests
            # TYPE genai_requests_total counter
            genai_requests_total{provider="openai",model="gpt-4"} 42
        """
        lines: list[str] = []

        def _label(key: str) -> str:
            provider, model = key.split("/", 1)
            return f'provider="{provider}",model="{model}"'

        lines += [
            "# HELP genai_requests_total Total GenAI requests",
            "# TYPE genai_requests_total counter",
        ]
        for key, m in self._metrics.items():
            lines.append(f"genai_requests_total{{{_label(key)}}} {m.request_count}")

        lines += [
            "# HELP genai_tokens_total Total tokens consumed",
            "# TYPE genai_tokens_total counter",
        ]
        for key, m in self._metrics.items():
            lines.append(f"genai_tokens_total{{{_label(key)}}} {m.token_count}")

        lines += [
            "# HELP genai_errors_total Total GenAI errors",
            "# TYPE genai_errors_total counter",
        ]
        for key, m in self._metrics.items():
            lines.append(f"genai_errors_total{{{_label(key)}}} {m.error_count}")

        return "\n".join(lines) + "\n"


class GenAIInstrumentor:
    """
    Auto-instruments LLM provider calls with OpenTelemetry tracing.

    Usage::

        instrumentor = GenAIInstrumentor()
        instrumentor.instrument("openai")

        with instrumentor.create_span("chat", attrs) as span:
            # perform LLM call
            pass
    """

    def __init__(
        self,
        exporter: SpanExporter | None = None,
        use_batch: bool = False,
    ) -> None:
        self._provider: TracerProvider | None = None
        self._exporter = exporter or ConsoleSpanExporter()
        self._use_batch = use_batch
        self._instrumented_providers: set[str] = set()

    def instrument(self, provider: str) -> None:
        """
        Set up an OTel TracerProvider for the given LLM *provider*.

        Multiple providers may be registered; each call is idempotent.
        """
        if self._provider is None:
            resource = Resource.create(
                {
                    "service.name": "aumai-otel-genai",
                    "gen_ai.system": provider,
                }
            )
            self._provider = TracerProvider(resource=resource)
            processor = (
                BatchSpanProcessor(self._exporter)
                if self._use_batch
                else SimpleSpanProcessor(self._exporter)
            )
            self._provider.add_span_processor(processor)
            trace.set_tracer_provider(self._provider)

        self._instrumented_providers.add(provider)

    def shutdown(self) -> None:
        """Flush and shut down the underlying TracerProvider."""
        if self._provider:
            self._provider.shutdown()

    @contextmanager
    def create_span(
        self,
        operation: str,
        attributes: GenAISpanAttributes,
    ) -> Generator[Span, None, None]:
        """
        Context manager that creates an OTel span with GenAI attributes.

        Usage::

            with instrumentor.create_span("chat.completions", attrs) as span:
                response = call_llm()
                span.set_attribute("gen_ai.usage.output_tokens", response.tokens)
        """
        if self._provider is None:
            self.instrument(attributes.provider)
        assert self._provider is not None

        tracer = self._provider.get_tracer(_LIBRARY_NAME, _LIBRARY_VERSION)
        otel_attrs = attributes.to_otel_dict()

        with tracer.start_as_current_span(
            f"gen_ai.{operation}",
            attributes=otel_attrs,
        ) as span:
            start = time.monotonic()
            try:
                yield span
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                raise
            finally:
                elapsed_ms = (time.monotonic() - start) * 1000
                span.set_attribute("aumai.genai.latency_ms", round(elapsed_ms, 2))


class GenAISpanProcessor:
    """
    A simple OTel SpanProcessor wrapper that enriches GenAI spans.

    Wraps an existing ``SpanProcessor`` and injects additional GenAI
    semantic convention attributes before the span ends.
    """

    def __init__(self, inner: Any) -> None:  # inner: SpanProcessor
        self._inner = inner

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        """Delegate to the inner processor."""
        self._inner.on_start(span, parent_context)

    def on_end(self, span: Any) -> None:
        """Enrich span with GenAI schema version before forwarding."""
        try:
            span.set_attribute(
                "gen_ai.opentelemetry.schema_version", "1.25.0"
            )
        except Exception:
            pass
        self._inner.on_end(span)

    def shutdown(self) -> None:
        """Shut down the inner processor."""
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush the inner processor."""
        return bool(self._inner.force_flush(timeout_millis))
