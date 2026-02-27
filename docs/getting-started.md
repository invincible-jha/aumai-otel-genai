# Getting Started with aumai-otel-genai

This guide takes you from installation to emitting your first instrumented LLM span in under
fifteen minutes.

---

## Prerequisites

- Python 3.11 or later
- An understanding of what OpenTelemetry is (traces, spans, exporters) is helpful but not required
- An LLM provider API key if you want to instrument real calls (not required for the CLI demo)

### What is OpenTelemetry?

OpenTelemetry (OTel) is a vendor-neutral observability framework. You emit *spans* (units of
work with a start time, end time, and attributes) from your code. An *exporter* ships those
spans to a backend — Jaeger, Grafana Tempo, Datadog, Honeycomb, etc. The key insight: you write
instrumentation once, and it works with any backend.

`aumai-otel-genai` does this specifically for LLM calls, following the OTel GenAI semantic
conventions.

---

## Installation

### From PyPI

```bash
pip install aumai-otel-genai
```

### With OTLP Exporter (for production backends)

```bash
pip install aumai-otel-genai opentelemetry-exporter-otlp
```

### From Source

```bash
git clone https://github.com/aumai/aumai-otel-genai.git
cd aumai-otel-genai
pip install -e ".[dev]"
```

### Verify

```bash
aumai-otel-genai --version
# aumai-otel-genai, version 0.1.0

python -c "from aumai_otel_genai.core import GenAIInstrumentor; print('OK')"
# OK
```

---

## Step-by-Step Tutorial

### Step 1 — Create an Instrumentor

The `GenAIInstrumentor` manages the OTel `TracerProvider` and handles span creation. For
development, the default `ConsoleSpanExporter` prints spans to stdout so you can see them
immediately without any backend.

```python
from aumai_otel_genai.core import GenAIInstrumentor

instrumentor = GenAIInstrumentor()
```

---

### Step 2 — Instrument a Provider

Call `instrument(provider)` with the name of the LLM provider you are using. This registers
the `TracerProvider` and records the provider name in the OTel resource attributes.

```python
instrumentor.instrument("openai")
```

Supported provider strings: `"openai"`, `"anthropic"`, `"cohere"`, `"google"`, `"mistral"`,
`"custom"`.

You only need to call `instrument()` once per process. Subsequent calls for the same provider
are idempotent.

---

### Step 3 — Define Span Attributes

`GenAISpanAttributes` is a Pydantic model that holds all the metadata for one LLM call. You
create an instance before the call with the parameters you know upfront (model name, provider,
temperature) and update dynamic fields (token counts, finish reason) inside the span context.

```python
from aumai_otel_genai.models import GenAISpanAttributes

attrs = GenAISpanAttributes(
    model="gpt-4o",
    provider="openai",
    temperature=0.7,
    max_tokens=512,
)
```

---

### Step 4 — Wrap Your LLM Call in a Span

Use `create_span()` as a context manager. The operation name becomes the span name prefix
(`gen_ai.{operation}`).

```python
with instrumentor.create_span("chat.completions", attrs) as span:
    # Make your real LLM SDK call here.
    # For this tutorial, we simulate a response:
    response_text = "Photosynthesis converts light energy into chemical energy."
    output_tokens = 9

    # Update the span with values known only after the call:
    span.set_attribute("gen_ai.usage.input_tokens", 15)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    span.set_attribute("gen_ai.response.finish_reason", "stop")
```

When the `with` block exits, `aumai.genai.latency_ms` is automatically set on the span.
If an exception is raised inside the block, the span status is set to `ERROR` and the
exception propagates normally.

---

### Step 5 — Shut Down Cleanly

Always call `shutdown()` before your process exits. This flushes any buffered spans to the
exporter.

```python
instrumentor.shutdown()
```

---

### Step 6 — Record and Export Metrics

`GenAIMetricsCollector` is independent of the tracer. Use it to accumulate aggregated counters
and render Prometheus metrics.

```python
from aumai_otel_genai.core import GenAIMetricsCollector

collector = GenAIMetricsCollector()

# Record a completed request
collector.record(
    provider="openai",
    model="gpt-4o",
    input_tokens=500,
    output_tokens=120,
    latency_ms=310.5,
    error=False,
)

# Render as Prometheus exposition format
print(collector.render_prometheus())
```

Example output:

```
# HELP genai_requests_total Total GenAI requests
# TYPE genai_requests_total counter
genai_requests_total{provider="openai",model="gpt-4o"} 1
# HELP genai_tokens_total Total tokens consumed
# TYPE genai_tokens_total counter
genai_tokens_total{provider="openai",model="gpt-4o"} 620
# HELP genai_errors_total Total GenAI errors
# TYPE genai_errors_total counter
genai_errors_total{provider="openai",model="gpt-4o"} 0
```

---

### Step 7 — Use the CLI to Verify Setup

The `instrument --demo` command emits a test span so you can confirm instrumentation works
before writing application code:

```bash
aumai-otel-genai instrument --provider openai --demo
```

To test metrics with a sample JSONL file:

```bash
cat > /tmp/usage.jsonl << 'EOF'
{"provider": "openai", "model": "gpt-4o", "input_tokens": 400, "output_tokens": 100, "latency_ms": 280.0}
{"provider": "openai", "model": "gpt-4o", "input_tokens": 600, "output_tokens": 150, "latency_ms": 340.0, "error": false}
EOF

aumai-otel-genai metrics --usage /tmp/usage.jsonl --format prometheus
```

---

## Common Patterns and Recipes

### Pattern 1 — Instrumenting Every LLM Call with a Wrapper

Centralizing instrumentation in a single wrapper function prevents scatter across the codebase:

```python
from typing import Any
from aumai_otel_genai.core import GenAIInstrumentor, GenAIMetricsCollector
from aumai_otel_genai.models import GenAISpanAttributes

_instrumentor = GenAIInstrumentor()
_instrumentor.instrument("openai")
_collector = GenAIMetricsCollector()


def call_llm(
    prompt: str,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 512,
) -> str:
    """Instrumented wrapper around the OpenAI chat completion API."""
    import openai
    client = openai.OpenAI()

    attrs = GenAISpanAttributes(
        model=model,
        provider="openai",
        temperature=temperature,
        max_tokens=max_tokens,
    )
    with _instrumentor.create_span("chat.completions", attrs) as span:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = response.usage
        span.set_attribute("gen_ai.usage.input_tokens", usage.prompt_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", usage.completion_tokens)

        _collector.record(
            provider="openai",
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_ms=0.0,
        )
        return response.choices[0].message.content
```

---

### Pattern 2 — Exporting to Jaeger via OTLP

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from aumai_otel_genai.core import GenAIInstrumentor

exporter = OTLPSpanExporter(
    endpoint="http://jaeger:4317",
    insecure=True,
)
instrumentor = GenAIInstrumentor(exporter=exporter, use_batch=True)
instrumentor.instrument("anthropic")
```

Spans will appear in Jaeger UI under the service name `aumai-otel-genai`.

---

### Pattern 3 — Serving Prometheus Metrics via HTTP

Expose the Prometheus metrics on a `/metrics` endpoint using Python's built-in HTTP server:

```python
from http.server import BaseHTTPRequestHandler, HTTPServer
from aumai_otel_genai.core import GenAIMetricsCollector

_collector = GenAIMetricsCollector()


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/metrics":
            body = _collector.render_prometheus().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:
        pass  # suppress default request logging


server = HTTPServer(("0.0.0.0", 9090), MetricsHandler)
print("Metrics available at http://localhost:9090/metrics")
server.serve_forever()
```

---

### Pattern 4 — Querying Metrics Programmatically

```python
from aumai_otel_genai.core import GenAIMetricsCollector

collector = GenAIMetricsCollector()
# ... record calls ...

# Get metrics for one specific model
m = collector.get_metrics(provider="openai", model="gpt-4o")
print(f"Requests: {m.request_count}")
print(f"Tokens  : {m.token_count}")
print(f"Errors  : {m.error_count}")
print(f"Histogram: {m.latency_histogram}")

# Compute error rate
if m.request_count > 0:
    error_rate = m.error_count / m.request_count
    print(f"Error rate: {error_rate:.1%}")
```

---

### Pattern 5 — Using extra Span Attributes

Pass arbitrary extra attributes via the `extra` field on `GenAISpanAttributes`. These are
forwarded verbatim to the OTel span:

```python
from aumai_otel_genai.models import GenAISpanAttributes

attrs = GenAISpanAttributes(
    model="claude-3-5-sonnet-20241022",
    provider="anthropic",
    temperature=1.0,
    extra={
        "user.id": "user_8821",
        "session.id": "sess-abc123",
        "app.feature": "summarization",
    },
)
```

---

## Troubleshooting FAQ

**Q: No spans appear in my OTel backend.**

Ensure `instrumentor.shutdown()` is called before the process exits. Without it, spans buffered
by `BatchSpanProcessor` may not be flushed. In development, switch to `use_batch=False` (the
default) to confirm spans are emitted synchronously.

---

**Q: `create_span()` emits spans with `latency_ms=0.0`.**

`latency_ms` is set automatically at span exit. If you see 0.0 in your exporter, check that
the span was not created with a pre-constructed `GenAISpanAttributes` that had `latency_ms`
set to 0.0 and that the span context manager exited normally (not via `force_flush()` before
the `with` block ended).

---

**Q: I see `RuntimeError: No TracerProvider set`.**

Call `instrumentor.instrument(provider)` before using `create_span()`. If you pass a provider
string that is not in the allowed list for the CLI but use the Python API directly, any non-empty
string is accepted.

---

**Q: Prometheus metrics show `0` for all providers.**

`GenAIMetricsCollector` is a plain Python object with in-process state. If you create a new
instance in a different process or request context, it starts empty. Use a module-level singleton
or dependency-inject the same instance everywhere.

---

**Q: `get_metrics()` returns a `GenAIMetrics` with all zeros for a key I recorded.**

Check the exact `provider` and `model` strings. The internal key is `f"{provider}/{model}"`,
so `"openai"` + `"gpt-4o"` and `"OpenAI"` + `"GPT-4o"` are different keys. Normalize case
before recording.

---

**Q: How do I disable instrumentation in tests?**

Use `InMemorySpanExporter` from `opentelemetry.sdk.trace.export.in_memory_span_exporter` so
spans are captured in memory without I/O:

```python
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from aumai_otel_genai.core import GenAIInstrumentor

exporter = InMemorySpanExporter()
instrumentor = GenAIInstrumentor(exporter=exporter)
```

Inspect captured spans with `exporter.get_finished_spans()`.
