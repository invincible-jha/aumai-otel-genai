"""Tests for aumai-otel-genai core module.

NOTE: Only standard OTel GenAI semantic conventions are tested here.
No governance signals or proprietary telemetry are covered.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aumai_otel_genai.core import GenAIInstrumentor, GenAIMetricsCollector, GenAISpanProcessor
from aumai_otel_genai.models import GenAIMetrics, GenAISpanAttributes


# ---------------------------------------------------------------------------
# GenAISpanAttributes model tests
# ---------------------------------------------------------------------------


class TestGenAISpanAttributes:
    def test_to_otel_dict_standard_keys(
        self, span_attrs: GenAISpanAttributes
    ) -> None:
        d = span_attrs.to_otel_dict()
        # Standard OTel GenAI semantic convention keys
        assert "gen_ai.system" in d
        assert "gen_ai.request.model" in d
        assert "gen_ai.usage.input_tokens" in d
        assert "gen_ai.usage.output_tokens" in d
        assert "gen_ai.response.finish_reason" in d

    def test_to_otel_dict_values(
        self, span_attrs: GenAISpanAttributes
    ) -> None:
        d = span_attrs.to_otel_dict()
        assert d["gen_ai.system"] == "openai"
        assert d["gen_ai.request.model"] == "gpt-4"
        assert d["gen_ai.usage.input_tokens"] == 100
        assert d["gen_ai.usage.output_tokens"] == 50
        assert d["gen_ai.response.finish_reason"] == "stop"

    def test_to_otel_dict_includes_temperature_when_set(
        self, span_attrs: GenAISpanAttributes
    ) -> None:
        d = span_attrs.to_otel_dict()
        assert "gen_ai.request.temperature" in d
        assert d["gen_ai.request.temperature"] == pytest.approx(0.7)

    def test_to_otel_dict_omits_temperature_when_none(
        self, minimal_span_attrs: GenAISpanAttributes
    ) -> None:
        d = minimal_span_attrs.to_otel_dict()
        assert "gen_ai.request.temperature" not in d

    def test_to_otel_dict_includes_max_tokens_when_set(
        self, span_attrs: GenAISpanAttributes
    ) -> None:
        d = span_attrs.to_otel_dict()
        assert "gen_ai.request.max_tokens" in d
        assert d["gen_ai.request.max_tokens"] == 512

    def test_to_otel_dict_omits_max_tokens_when_none(
        self, minimal_span_attrs: GenAISpanAttributes
    ) -> None:
        d = minimal_span_attrs.to_otel_dict()
        assert "gen_ai.request.max_tokens" not in d

    def test_to_otel_dict_merges_extra(self) -> None:
        attrs = GenAISpanAttributes(
            model="m",
            provider="p",
            extra={"custom.key": "custom_value"},
        )
        d = attrs.to_otel_dict()
        assert d["custom.key"] == "custom_value"

    def test_default_finish_reason_is_stop(self) -> None:
        attrs = GenAISpanAttributes(model="m", provider="p")
        assert attrs.finish_reason == "stop"

    def test_default_token_counts_are_zero(self) -> None:
        attrs = GenAISpanAttributes(model="m", provider="p")
        assert attrs.input_tokens == 0
        assert attrs.output_tokens == 0


# ---------------------------------------------------------------------------
# GenAIMetrics tests
# ---------------------------------------------------------------------------


class TestGenAIMetrics:
    def test_initial_state(self) -> None:
        m = GenAIMetrics()
        assert m.request_count == 0
        assert m.token_count == 0
        assert m.error_count == 0
        assert m.latency_histogram == []

    def test_record_request_increments_counts(self) -> None:
        m = GenAIMetrics()
        m.record_request(input_tokens=100, output_tokens=50, latency_ms=200)
        assert m.request_count == 1
        assert m.token_count == 150
        assert m.error_count == 0

    def test_record_request_with_error(self) -> None:
        m = GenAIMetrics()
        m.record_request(input_tokens=10, output_tokens=5, latency_ms=100, error=True)
        assert m.error_count == 1
        assert m.request_count == 1

    def test_record_request_accumulates(self) -> None:
        m = GenAIMetrics()
        for _ in range(5):
            m.record_request(input_tokens=10, output_tokens=10, latency_ms=50)
        assert m.request_count == 5
        assert m.token_count == 100

    def test_latency_histogram_populated(self) -> None:
        m = GenAIMetrics()
        m.record_request(input_tokens=0, output_tokens=0, latency_ms=75)
        assert len(m.latency_histogram) == 1
        bucket_upper, count = m.latency_histogram[0]
        assert count == 1
        assert bucket_upper == 100.0  # 75ms falls in <=100ms bucket

    def test_latency_histogram_accumulates_same_bucket(self) -> None:
        m = GenAIMetrics()
        m.record_request(0, 0, latency_ms=10)
        m.record_request(0, 0, latency_ms=5)
        # Both in <=10ms bucket
        assert len(m.latency_histogram) == 1
        assert m.latency_histogram[0][1] == 2

    def test_latency_histogram_different_buckets(self) -> None:
        m = GenAIMetrics()
        m.record_request(0, 0, latency_ms=10)    # <=10ms bucket
        m.record_request(0, 0, latency_ms=200)   # <=250ms bucket
        assert len(m.latency_histogram) == 2

    def test_latency_inf_bucket(self) -> None:
        m = GenAIMetrics()
        m.record_request(0, 0, latency_ms=9999)
        bucket_upper, count = m.latency_histogram[0]
        assert bucket_upper == float("inf")
        assert count == 1

    @pytest.mark.parametrize(
        "latency_ms, expected_bucket",
        [
            (5.0, 10.0),
            (10.0, 10.0),
            (11.0, 50.0),
            (50.0, 50.0),
            (51.0, 100.0),
            (100.0, 100.0),
            (101.0, 250.0),
            (250.0, 250.0),
            (251.0, 500.0),
            (500.0, 500.0),
            (501.0, 1000.0),
            (1000.0, 1000.0),
            (1001.0, 2500.0),
            (2500.0, 2500.0),
            (2501.0, 5000.0),
            (5000.0, 5000.0),
            (5001.0, float("inf")),
        ],
    )
    def test_latency_bucket_boundaries(
        self, latency_ms: float, expected_bucket: float
    ) -> None:
        m = GenAIMetrics()
        m.record_request(0, 0, latency_ms=latency_ms)
        assert m.latency_histogram[0][0] == expected_bucket


# ---------------------------------------------------------------------------
# GenAIMetricsCollector tests
# ---------------------------------------------------------------------------


class TestGenAIMetricsCollector:
    def test_record_creates_entry(
        self, collector: GenAIMetricsCollector
    ) -> None:
        collector.record(
            provider="openai",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
        )
        m = collector.get_metrics("openai", "gpt-4")
        assert m.request_count == 1
        assert m.token_count == 150

    def test_record_accumulates_multiple_calls(
        self, collector: GenAIMetricsCollector
    ) -> None:
        for _ in range(3):
            collector.record("openai", "gpt-4", 10, 10, 100)
        m = collector.get_metrics("openai", "gpt-4")
        assert m.request_count == 3
        assert m.token_count == 60

    def test_record_with_error(
        self, collector: GenAIMetricsCollector
    ) -> None:
        collector.record("openai", "gpt-4", 0, 0, 50, error=True)
        m = collector.get_metrics("openai", "gpt-4")
        assert m.error_count == 1

    def test_get_metrics_returns_empty_for_unknown(
        self, collector: GenAIMetricsCollector
    ) -> None:
        m = collector.get_metrics("unknown", "model")
        assert m.request_count == 0

    def test_all_metrics_returns_all_keys(
        self, collector: GenAIMetricsCollector
    ) -> None:
        collector.record("openai", "gpt-4", 0, 0, 0)
        collector.record("anthropic", "claude-3", 0, 0, 0)
        all_m = collector.all_metrics()
        assert "openai/gpt-4" in all_m
        assert "anthropic/claude-3" in all_m

    def test_render_prometheus_format(
        self, collector: GenAIMetricsCollector
    ) -> None:
        collector.record("openai", "gpt-4", 100, 50, 200)
        prometheus = collector.render_prometheus()
        assert "genai_requests_total" in prometheus
        assert "genai_tokens_total" in prometheus
        assert "genai_errors_total" in prometheus
        assert 'provider="openai"' in prometheus
        assert 'model="gpt-4"' in prometheus

    def test_render_prometheus_counter_values(
        self, collector: GenAIMetricsCollector
    ) -> None:
        collector.record("openai", "gpt-4", 100, 50, 200)
        prometheus = collector.render_prometheus()
        lines = prometheus.splitlines()
        req_lines = [l for l in lines if l.startswith("genai_requests_total{")]
        assert len(req_lines) == 1
        assert req_lines[0].endswith("1")

    def test_render_prometheus_multiple_providers(
        self, collector: GenAIMetricsCollector
    ) -> None:
        collector.record("openai", "gpt-4", 10, 10, 100)
        collector.record("anthropic", "claude-3", 20, 20, 200)
        prometheus = collector.render_prometheus()
        assert 'provider="openai"' in prometheus
        assert 'provider="anthropic"' in prometheus

    def test_render_prometheus_ends_with_newline(
        self, collector: GenAIMetricsCollector
    ) -> None:
        prometheus = collector.render_prometheus()
        assert prometheus.endswith("\n")

    def test_render_prometheus_empty_collector(
        self, collector: GenAIMetricsCollector
    ) -> None:
        prometheus = collector.render_prometheus()
        assert "HELP" in prometheus
        assert "TYPE" in prometheus


# ---------------------------------------------------------------------------
# GenAIInstrumentor tests
# ---------------------------------------------------------------------------


class TestGenAIInstrumentor:
    def test_instrument_registers_provider(
        self, instrumentor: GenAIInstrumentor
    ) -> None:
        instrumentor.instrument("openai")
        assert "openai" in instrumentor._instrumented_providers

    def test_instrument_is_idempotent(
        self, instrumentor: GenAIInstrumentor
    ) -> None:
        instrumentor.instrument("openai")
        instrumentor.instrument("openai")
        assert len(instrumentor._instrumented_providers) == 1

    def test_instrument_multiple_providers(
        self, instrumentor: GenAIInstrumentor
    ) -> None:
        instrumentor.instrument("openai")
        instrumentor.instrument("anthropic")
        assert "openai" in instrumentor._instrumented_providers
        assert "anthropic" in instrumentor._instrumented_providers

    def test_create_span_emits_span(
        self,
        instrumentor: GenAIInstrumentor,
        in_memory_exporter: InMemorySpanExporter,
        span_attrs: GenAISpanAttributes,
    ) -> None:
        instrumentor.instrument("openai")
        with instrumentor.create_span("chat.completions", span_attrs):
            pass
        spans = in_memory_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "gen_ai.chat.completions"

    def test_create_span_sets_otel_attributes(
        self,
        instrumentor: GenAIInstrumentor,
        in_memory_exporter: InMemorySpanExporter,
        span_attrs: GenAISpanAttributes,
    ) -> None:
        instrumentor.instrument("openai")
        with instrumentor.create_span("chat", span_attrs):
            pass
        spans = in_memory_exporter.get_finished_spans()
        attrs = spans[0].attributes
        assert attrs.get("gen_ai.system") == "openai"
        assert attrs.get("gen_ai.request.model") == "gpt-4"
        assert attrs.get("gen_ai.usage.input_tokens") == 100

    def test_create_span_sets_latency_attribute(
        self,
        instrumentor: GenAIInstrumentor,
        in_memory_exporter: InMemorySpanExporter,
        span_attrs: GenAISpanAttributes,
    ) -> None:
        instrumentor.instrument("openai")
        with instrumentor.create_span("chat", span_attrs):
            pass
        spans = in_memory_exporter.get_finished_spans()
        attrs = spans[0].attributes
        assert "aumai.genai.latency_ms" in attrs

    def test_create_span_records_error_status_on_exception(
        self,
        instrumentor: GenAIInstrumentor,
        in_memory_exporter: InMemorySpanExporter,
        span_attrs: GenAISpanAttributes,
    ) -> None:
        instrumentor.instrument("openai")
        with pytest.raises(RuntimeError):
            with instrumentor.create_span("chat", span_attrs):
                raise RuntimeError("LLM call failed")
        spans = in_memory_exporter.get_finished_spans()
        from opentelemetry.trace import StatusCode
        assert spans[0].status.status_code == StatusCode.ERROR

    def test_create_span_auto_instruments_if_not_set(
        self,
        in_memory_exporter: InMemorySpanExporter,
        span_attrs: GenAISpanAttributes,
    ) -> None:
        # New instrumentor, no instrument() call
        inst = GenAIInstrumentor(exporter=in_memory_exporter, use_batch=False)
        try:
            with inst.create_span("completion", span_attrs):
                pass
            # Should not raise
        finally:
            inst.shutdown()

    def test_shutdown_does_not_raise(
        self, in_memory_exporter: InMemorySpanExporter
    ) -> None:
        # Use a standalone instrumentor to avoid double-shutdown with the fixture
        inst = GenAIInstrumentor(exporter=in_memory_exporter, use_batch=False)
        inst.instrument("openai")
        inst.shutdown()  # Should be safe and not raise


# ---------------------------------------------------------------------------
# GenAISpanProcessor tests
# ---------------------------------------------------------------------------


class TestGenAISpanProcessor:
    def _make_mock_inner(self) -> object:
        """Return a minimal mock inner processor."""
        class MockInner:
            started: list = []
            ended: list = []
            flushed: list = []
            shut_down: bool = False

            def on_start(self, span, parent_context=None):
                self.started.append(span)

            def on_end(self, span):
                self.ended.append(span)

            def shutdown(self):
                self.shut_down = True

            def force_flush(self, timeout_millis=30000):
                self.flushed.append(timeout_millis)
                return True

        return MockInner()

    def test_on_start_delegates_to_inner(self) -> None:
        inner = self._make_mock_inner()
        processor = GenAISpanProcessor(inner)
        processor.on_start("span-obj", parent_context=None)
        assert "span-obj" in inner.started

    def test_on_end_enriches_span_with_schema_version(self) -> None:
        attrs_set = {}

        class FakeSpan:
            def set_attribute(self, key, value):
                attrs_set[key] = value

        inner = self._make_mock_inner()
        processor = GenAISpanProcessor(inner)
        span = FakeSpan()
        processor.on_end(span)
        assert attrs_set.get("gen_ai.opentelemetry.schema_version") == "1.25.0"

    def test_on_end_delegates_to_inner(self) -> None:
        inner = self._make_mock_inner()
        processor = GenAISpanProcessor(inner)

        class FakeSpan:
            def set_attribute(self, key, value):
                pass

        span = FakeSpan()
        processor.on_end(span)
        assert span in inner.ended

    def test_on_end_handles_span_set_attribute_exception_gracefully(self) -> None:
        class BrokenSpan:
            def set_attribute(self, key, value):
                raise AttributeError("span already ended")

        inner = self._make_mock_inner()
        processor = GenAISpanProcessor(inner)
        # Should not raise even if set_attribute fails
        processor.on_end(BrokenSpan())

    def test_shutdown_delegates(self) -> None:
        inner = self._make_mock_inner()
        processor = GenAISpanProcessor(inner)
        processor.shutdown()
        assert inner.shut_down is True

    def test_force_flush_delegates(self) -> None:
        inner = self._make_mock_inner()
        processor = GenAISpanProcessor(inner)
        result = processor.force_flush(5000)
        assert result is True
        assert 5000 in inner.flushed
