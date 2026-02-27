# aumai-otel-genai

**Standard GenAI telemetry instrumentation via OpenTelemetry.**

Part of the [AumAI](https://github.com/aumai) open-source agentic AI infrastructure suite.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-compatible-orange.svg)](https://opentelemetry.io/)
[![AumAI Suite](https://img.shields.io/badge/AumAI-suite-blueviolet.svg)](https://github.com/aumai)

---

## What Is This?

Think of your LLM calls as phone calls made by your application. You already measure how many
calls your API endpoints receive, how fast they respond, and how often they fail. But most teams
have no equivalent visibility into their AI calls: which model was invoked, how many tokens were
consumed, what the latency was, and whether it errored.

`aumai-otel-genai` is the instrumentation layer that fills this gap. It wraps your LLM calls in
standard OpenTelemetry spans, attaches the GenAI semantic convention attributes that the OTel
community has standardized, and collects aggregated Prometheus-compatible metrics — all without
requiring you to change your model provider SDK.

The result: your AI calls appear in your existing observability stack (Jaeger, Grafana, Datadog,
Honeycomb) alongside every other service, with no custom dashboards required.

---

## Why Does This Matter?

### Cost Without Visibility Is Risk

LLM API costs scale with token consumption, which scales with usage patterns that are hard to
predict. A single poorly-constrained prompt can consume 10x the expected tokens. Without
per-model, per-provider token metrics, you are flying blind on a cost center that can easily
become your largest infrastructure expense.

### LLM Observability Is Not Optional in Production

Traditional application monitoring tells you that a request took 500ms. GenAI observability
tells you *why*: the model streamed 1,200 output tokens at $0.06 per thousand, finished with
reason `length` (meaning you hit `max_tokens`), and the p99 latency for this model is 3.2s.
That context is essential for capacity planning, prompt optimization, and SLA enforcement.

### Standards Prevent Lock-In

The OpenTelemetry GenAI semantic conventions (`gen_ai.*`) are a vendor-neutral standard. By
emitting spans and attributes in this format, you can switch between any OTel-compatible backend
— Jaeger today, Grafana Tempo tomorrow — without rewriting your instrumentation.

---

## Architecture

```mermaid
flowchart TD
    A[Your Agent Code] -->|create_span context manager| B[GenAIInstrumentor]
    B --> C[OTel TracerProvider]
    C --> D{SpanProcessor}
    D -->|SimpleSpanProcessor| E[ConsoleSpanExporter]
    D -->|BatchSpanProcessor| F[OTLP / Jaeger / Zipkin]
    B --> G[GenAISpanProcessor]
    G -->|enriches span with schema_version| D

    H[GenAIMetricsCollector] -->|record()| I[(In-Memory Metrics\nprovider/model)]
    I -->|render_prometheus()| J[Prometheus Text Format]
    I -->|all_metrics() / get_metrics()| K[JSON / Custom Export]

    style B fill:#E87722,color:#fff
    style H fill:#2E8B57,color:#fff
    style C fill:#4A90D9,color:#fff
```

---

## Features

- **OTel semantic conventions** — Spans carry all standard `gen_ai.*` attributes as defined by
  the OpenTelemetry GenAI working group.
- **Provider-agnostic** — Instrument `openai`, `anthropic`, `cohere`, `google`, `mistral`, or
  any custom provider with a single `instrument(provider)` call.
- **Automatic latency measurement** — `create_span()` records wall-clock latency in milliseconds
  on every span, even if the call raises an exception.
- **Error propagation** — Exceptions inside a span are caught, the span status is set to
  `ERROR`, and the exception is re-raised so your error handling is unaffected.
- **Prometheus metrics** — `GenAIMetricsCollector` aggregates request count, token count, error
  count, and a latency histogram, exportable as Prometheus exposition format.
- **Pluggable exporters** — Pass any `SpanExporter` (console, OTLP, Jaeger, Zipkin) to
  `GenAIInstrumentor`.
- **Batch or simple processing** — Choose `use_batch=True` for production throughput or the
  default simple processor for development.
- **`GenAISpanProcessor` enrichment** — Automatically injects the OTel GenAI schema version
  (`1.25.0`) into every span before export.

---

## Quick Start

### Installation

```bash
pip install aumai-otel-genai
```

For OTLP export (Jaeger, collector):

```bash
pip install aumai-otel-genai opentelemetry-exporter-otlp
```

### Python — 60-second example

```python
from aumai_otel_genai.core import GenAIInstrumentor, GenAIMetricsCollector
from aumai_otel_genai.models import GenAISpanAttributes

# 1. Create and configure the instrumentor
instrumentor = GenAIInstrumentor()
instrumentor.instrument("openai")

# 2. Define span attributes for the call
attrs = GenAISpanAttributes(
    model="gpt-4o",
    provider="openai",
    input_tokens=512,
    output_tokens=128,
    cost_usd=0.0038,
    temperature=0.7,
    max_tokens=256,
    finish_reason="stop",
)

# 3. Wrap your LLM call in a span
with instrumentor.create_span("chat.completions", attrs) as span:
    # Replace with your actual LLM SDK call:
    response_text = "The capital of France is Paris."
    span.set_attribute("gen_ai.usage.output_tokens", 7)

print("Span emitted to configured exporter.")

# 4. Collect and print Prometheus metrics
collector = GenAIMetricsCollector()
collector.record(
    provider="openai",
    model="gpt-4o",
    input_tokens=512,
    output_tokens=128,
    latency_ms=340.5,
)
print(collector.render_prometheus())

instrumentor.shutdown()
```

---

## CLI Reference

The CLI is installed as `aumai-otel-genai`.

### `instrument` — Set up and verify instrumentation

```bash
aumai-otel-genai instrument --provider openai
aumai-otel-genai instrument --provider anthropic --exporter console --demo
```

| Flag | Default | Description |
|------|---------|-------------|
| `--provider` | required | LLM provider: `openai`, `anthropic`, `cohere`, `google`, `mistral`, `custom` |
| `--exporter` | `console` | Span exporter: `console` or `memory` |
| `--demo` | false | Emit a demo span to verify instrumentation is working |

When `--demo` is specified, the command emits a single test span with dummy attributes and
prints the result to the configured exporter, making it easy to confirm the setup works before
integrating into your application.

Example output:

```
Instrumented provider: openai
Exporter             : console
Demo span emitted.
```

---

### `metrics` — Collect and display GenAI metrics

```bash
# Display empty metrics in Prometheus format
aumai-otel-genai metrics

# Load usage events from a JSONL file and display metrics
aumai-otel-genai metrics --usage ./usage_events.jsonl --format prometheus

# Display as JSON
aumai-otel-genai metrics --usage ./usage_events.jsonl --format json
```

| Flag | Default | Description |
|------|---------|-------------|
| `--usage` | None | Path to a JSONL file of usage events to load |
| `--format` | `prometheus` | Output format: `prometheus` or `json` |

**JSONL usage event format:**

Each line must be a JSON object with these optional fields:

```json
{"provider": "openai", "model": "gpt-4o", "input_tokens": 500, "output_tokens": 120, "latency_ms": 310.0, "error": false}
```

Example `usage_events.jsonl`:

```jsonl
{"provider": "openai", "model": "gpt-4o", "input_tokens": 500, "output_tokens": 120, "latency_ms": 310.0}
{"provider": "anthropic", "model": "claude-3-5-sonnet", "input_tokens": 800, "output_tokens": 250, "latency_ms": 520.0}
{"provider": "openai", "model": "gpt-4o", "input_tokens": 200, "output_tokens": 80, "latency_ms": 180.0, "error": true}
```

Example Prometheus output:

```
# HELP genai_requests_total Total GenAI requests
# TYPE genai_requests_total counter
genai_requests_total{provider="openai",model="gpt-4o"} 2
genai_requests_total{provider="anthropic",model="claude-3-5-sonnet"} 1
# HELP genai_tokens_total Total tokens consumed
# TYPE genai_tokens_total counter
genai_tokens_total{provider="openai",model="gpt-4o"} 900
genai_tokens_total{provider="anthropic",model="claude-3-5-sonnet"} 1050
# HELP genai_errors_total Total GenAI errors
# TYPE genai_errors_total counter
genai_errors_total{provider="openai",model="gpt-4o"} 1
genai_errors_total{provider="anthropic",model="claude-3-5-sonnet"} 0
```

---

## Python API Examples

### Integrating with a Real LLM SDK

```python
import openai
from aumai_otel_genai.core import GenAIInstrumentor, GenAIMetricsCollector
from aumai_otel_genai.models import GenAISpanAttributes

instrumentor = GenAIInstrumentor()
instrumentor.instrument("openai")
collector = GenAIMetricsCollector()

client = openai.OpenAI()

def instrumented_chat(prompt: str) -> str:
    attrs = GenAISpanAttributes(
        model="gpt-4o",
        provider="openai",
        temperature=0.7,
        max_tokens=512,
    )
    with instrumentor.create_span("chat.completions", attrs) as span:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.7,
        )
        usage = response.usage
        span.set_attribute("gen_ai.usage.input_tokens", usage.prompt_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", usage.completion_tokens)

        collector.record(
            provider="openai",
            model="gpt-4o",
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_ms=0.0,  # measured by create_span automatically
        )
        return response.choices[0].message.content

result = instrumented_chat("Explain photosynthesis in one sentence.")
print(result)
```

### Exporting to an OTLP Collector

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from aumai_otel_genai.core import GenAIInstrumentor
from aumai_otel_genai.models import GenAISpanAttributes

otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
instrumentor = GenAIInstrumentor(exporter=otlp_exporter, use_batch=True)
instrumentor.instrument("anthropic")
```

### Using `GenAISpanProcessor` for Custom Enrichment

```python
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from aumai_otel_genai.core import GenAIInstrumentor, GenAISpanProcessor

base_processor = SimpleSpanProcessor(ConsoleSpanExporter())
enriching_processor = GenAISpanProcessor(inner=base_processor)
# Attach enriching_processor to your TracerProvider manually for advanced pipelines
```

### Scraping Metrics into a Dict

```python
import json
from aumai_otel_genai.core import GenAIMetricsCollector

collector = GenAIMetricsCollector()
# ... record calls ...

all_metrics = collector.all_metrics()
for key, metrics in all_metrics.items():
    print(f"{key}: {metrics.request_count} requests, {metrics.token_count} tokens")

# Serialize to JSON
print(json.dumps({k: v.model_dump() for k, v in all_metrics.items()}, indent=2))
```

---

## Configuration

`aumai-otel-genai` uses constructor arguments rather than environment variables, keeping
configuration explicit and testable.

| Constructor Arg | Type | Default | Description |
|----------------|------|---------|-------------|
| `exporter` | `SpanExporter \| None` | `ConsoleSpanExporter()` | OTel span exporter |
| `use_batch` | `bool` | `False` | Use `BatchSpanProcessor` (recommended for production) |

For production deployments, pass an OTLP exporter and enable batching:

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from aumai_otel_genai.core import GenAIInstrumentor

instrumentor = GenAIInstrumentor(
    exporter=OTLPSpanExporter(endpoint="https://otel-collector.internal/v1/traces"),
    use_batch=True,
)
```

---

## How It Works — Deep Dive

### Span Lifecycle

`create_span()` is a `@contextmanager`. When the `with` block is entered:

1. A new OTel span is started with name `gen_ai.{operation}`.
2. All `GenAISpanAttributes` fields are attached as OTel attributes via `to_otel_dict()`.
3. A `time.monotonic()` start time is recorded.

When the `with` block exits:
- If no exception: elapsed time is computed and set as `aumai.genai.latency_ms`.
- If an exception: the span status is set to `ERROR` with the exception message, then the
  exception is re-raised.

### OTel Attribute Mapping

`GenAISpanAttributes.to_otel_dict()` maps model fields to OTel semantic convention names:

| Model Field | OTel Attribute |
|-------------|---------------|
| `provider` | `gen_ai.system` |
| `model` | `gen_ai.request.model` |
| `input_tokens` | `gen_ai.usage.input_tokens` |
| `output_tokens` | `gen_ai.usage.output_tokens` |
| `finish_reason` | `gen_ai.response.finish_reason` |
| `cost_usd` | `aumai.genai.cost_usd` |
| `temperature` | `gen_ai.request.temperature` (if set) |
| `max_tokens` | `gen_ai.request.max_tokens` (if set) |

### Prometheus Latency Histogram

`GenAIMetrics._record_latency()` uses fixed exponential buckets:
`[10, 50, 100, 250, 500, 1000, 2500, 5000, +Inf]` ms. Each request increments the count of
the first bucket whose upper bound is >= the measured latency.

---

## Integration with Other AumAI Projects

| Project | Integration Pattern |
|---------|-------------------|
| **aumai-transparency** | Attach the OTel `trace_id` and `span_id` to `AuditEvent.metadata` when logging events, creating a bidirectional link between audit records and distributed traces. |
| **aumai-proofserve** | Include `span_id` in `ComputationProof.metadata` so that a proof can be traced back to the exact OTel span that recorded its inputs and outputs. |

---

## Contributing

Please read `CONTRIBUTING.md` before opening a pull request. All new public APIs must be
accompanied by tests and docstrings.

```bash
git checkout -b feature/my-change
make test
make lint
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for full text.

Copyright 2025 AumAI Contributors.
