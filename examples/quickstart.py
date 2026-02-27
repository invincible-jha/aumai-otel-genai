"""Quickstart examples for aumai-otel-genai.

Demonstrates the core features of the library:
  1. Setting up instrumentation and emitting a span
  2. Attaching dynamic attributes inside a span
  3. Collecting and rendering Prometheus metrics
  4. Multi-provider metrics aggregation
  5. Error handling within instrumented calls

Run this file directly to see all demos in action:

    python examples/quickstart.py

Note: These demos use in-memory exporters and simulated LLM responses so
they run without any LLM API credentials.
"""

from __future__ import annotations

import time

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aumai_otel_genai.core import GenAIInstrumentor, GenAIMetricsCollector
from aumai_otel_genai.models import GenAIMetrics, GenAISpanAttributes


# ---------------------------------------------------------------------------
# Demo 1 — Basic span creation and attribute inspection
# ---------------------------------------------------------------------------


def demo_basic_span() -> None:
    """Create a span for a simulated OpenAI chat completion and inspect it."""
    print("=" * 60)
    print("Demo 1: Basic span creation")
    print("=" * 60)

    # Use an in-memory exporter so we can inspect finished spans programmatically
    exporter = InMemorySpanExporter()
    instrumentor = GenAIInstrumentor(exporter=exporter, use_batch=False)
    instrumentor.instrument("openai")

    attrs = GenAISpanAttributes(
        model="gpt-4o",
        provider="openai",
        input_tokens=512,
        output_tokens=128,
        cost_usd=0.0048,
        temperature=0.7,
        max_tokens=256,
        finish_reason="stop",
    )

    with instrumentor.create_span("chat.completions", attrs) as span:
        # Simulate an LLM call taking ~10ms
        time.sleep(0.01)
        span.set_attribute("gen_ai.usage.input_tokens", 512)
        span.set_attribute("gen_ai.usage.output_tokens", 128)

    finished = exporter.get_finished_spans()
    assert len(finished) == 1, "Expected exactly one span"

    otel_span = finished[0]
    otel_attrs = dict(otel_span.attributes or {})

    print(f"Span name          : {otel_span.name}")
    print(f"Provider           : {otel_attrs.get('gen_ai.system')}")
    print(f"Model              : {otel_attrs.get('gen_ai.request.model')}")
    print(f"Input tokens       : {otel_attrs.get('gen_ai.usage.input_tokens')}")
    print(f"Output tokens      : {otel_attrs.get('gen_ai.usage.output_tokens')}")
    print(f"Cost (USD)         : {otel_attrs.get('aumai.genai.cost_usd')}")
    latency_ms = otel_attrs.get("aumai.genai.latency_ms", 0.0)
    print(f"Latency (ms)       : {latency_ms:.2f}")
    print(f"Status             : {otel_span.status.status_code}")

    instrumentor.shutdown()
    print()


# ---------------------------------------------------------------------------
# Demo 2 — Dynamic attributes: updating span mid-flight
# ---------------------------------------------------------------------------


def demo_dynamic_attributes() -> None:
    """Show how to update span attributes with values known only after the call."""
    print("=" * 60)
    print("Demo 2: Dynamic span attributes")
    print("=" * 60)

    exporter = InMemorySpanExporter()
    instrumentor = GenAIInstrumentor(exporter=exporter)
    instrumentor.instrument("anthropic")

    # We know model and provider upfront; tokens and finish_reason come from the response
    attrs = GenAISpanAttributes(
        model="claude-3-5-sonnet-20241022",
        provider="anthropic",
        temperature=1.0,
    )

    with instrumentor.create_span("messages.create", attrs) as span:
        # Simulate the Anthropic SDK returning a response
        simulated_input_tokens = 800
        simulated_output_tokens = 300
        simulated_finish_reason = "end_turn"

        span.set_attribute("gen_ai.usage.input_tokens", simulated_input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", simulated_output_tokens)
        span.set_attribute("gen_ai.response.finish_reason", simulated_finish_reason)
        span.set_attribute("user.id", "user_8821")  # custom attribute

    finished = exporter.get_finished_spans()
    otel_attrs = dict(finished[0].attributes or {})

    print(f"Model              : {otel_attrs.get('gen_ai.request.model')}")
    print(f"Input tokens       : {otel_attrs.get('gen_ai.usage.input_tokens')}")
    print(f"Output tokens      : {otel_attrs.get('gen_ai.usage.output_tokens')}")
    print(f"Finish reason      : {otel_attrs.get('gen_ai.response.finish_reason')}")
    print(f"User ID            : {otel_attrs.get('user.id')}")

    instrumentor.shutdown()
    print()


# ---------------------------------------------------------------------------
# Demo 3 — Prometheus metrics collection
# ---------------------------------------------------------------------------


def demo_prometheus_metrics() -> None:
    """Collect usage events and render Prometheus exposition format."""
    print("=" * 60)
    print("Demo 3: Prometheus metrics")
    print("=" * 60)

    collector = GenAIMetricsCollector()

    # Simulate a mix of successful and failed requests across two models
    usage_events = [
        ("openai", "gpt-4o", 500, 120, 310.0, False),
        ("openai", "gpt-4o", 450, 95, 280.0, False),
        ("openai", "gpt-4o", 600, 0, 50.0, True),   # error: empty output
        ("anthropic", "claude-3-5-sonnet-20241022", 800, 250, 520.0, False),
        ("anthropic", "claude-3-5-sonnet-20241022", 1200, 400, 710.0, False),
    ]

    for provider, model, in_tok, out_tok, lat_ms, error in usage_events:
        collector.record(
            provider=provider,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=lat_ms,
            error=error,
        )

    prometheus_text = collector.render_prometheus()
    print(prometheus_text)

    # Also show structured access
    gpt4_metrics: GenAIMetrics = collector.get_metrics("openai", "gpt-4o")
    print(f"GPT-4o requests : {gpt4_metrics.request_count}")
    print(f"GPT-4o tokens   : {gpt4_metrics.token_count}")
    print(f"GPT-4o errors   : {gpt4_metrics.error_count}")
    print(f"GPT-4o histogram: {gpt4_metrics.latency_histogram}")
    print()


# ---------------------------------------------------------------------------
# Demo 4 — Multi-provider aggregation
# ---------------------------------------------------------------------------


def demo_multi_provider() -> None:
    """Aggregate metrics from three providers and compare by request volume."""
    print("=" * 60)
    print("Demo 4: Multi-provider aggregation")
    print("=" * 60)

    collector = GenAIMetricsCollector()

    # Simulate a 24-hour window of mixed provider usage
    provider_events = {
        ("openai", "gpt-4o"): [(400, 100, 280.0)] * 15,
        ("anthropic", "claude-3-5-sonnet-20241022"): [(700, 200, 480.0)] * 8,
        ("cohere", "command-r-plus"): [(300, 90, 210.0)] * 4,
    }

    for (provider, model), events in provider_events.items():
        for in_tok, out_tok, lat_ms in events:
            collector.record(
                provider=provider,
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=lat_ms,
            )

    print(f"{'Provider/Model':<45} {'Requests':>8} {'Tokens':>10} {'Errors':>7}")
    print("-" * 73)
    for key, metrics in sorted(collector.all_metrics().items()):
        print(
            f"{key:<45} {metrics.request_count:>8} "
            f"{metrics.token_count:>10} {metrics.error_count:>7}"
        )
    print()


# ---------------------------------------------------------------------------
# Demo 5 — Error handling in instrumented calls
# ---------------------------------------------------------------------------


def demo_error_handling() -> None:
    """Demonstrate that exceptions inside a span are properly recorded."""
    print("=" * 60)
    print("Demo 5: Error handling")
    print("=" * 60)

    exporter = InMemorySpanExporter()
    instrumentor = GenAIInstrumentor(exporter=exporter)
    instrumentor.instrument("openai")

    attrs = GenAISpanAttributes(
        model="gpt-4o",
        provider="openai",
    )

    try:
        with instrumentor.create_span("chat.completions", attrs):
            # Simulate a rate-limit error from the LLM provider
            raise RuntimeError("429 Too Many Requests: rate limit exceeded")
    except RuntimeError as exc:
        print(f"Caught expected error: {exc}")

    finished = exporter.get_finished_spans()
    span = finished[0]

    from opentelemetry.trace import StatusCode

    print(f"Span status  : {span.status.status_code}")
    print(f"Status match : {span.status.status_code == StatusCode.ERROR}")
    print(f"Status desc  : {span.status.description}")

    instrumentor.shutdown()
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run all quickstart demos."""
    demo_basic_span()
    demo_dynamic_attributes()
    demo_prometheus_metrics()
    demo_multi_provider()
    demo_error_handling()
    print("All demos completed successfully.")


if __name__ == "__main__":
    main()
