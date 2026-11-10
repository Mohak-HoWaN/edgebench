# ADR 0004: How latency results and differences are reported

Status: accepted (Phase 0, 2026-11-09). Written before any real multi-repeat data exists; revisit after Phase 4 has real runs.

## Context
The brief asks for 95% confidence intervals across repeats and for "not statistically significant" labels. The default is 3 repeats, which
gives a very wide interval. Phase 0 showed laptop latencies are noisy (p95 up to 17% above the mean, for ncnn FP32) and that thread count
interacts with hybrid cores.

## Decision
Unit of analysis: one **repeat** = one run of N timed iterations after W warm-up iterations (defaults 200 and 20). A repeat is summarised by
its mean, p50, p95, p99 and standard deviation of per-iteration latency.
- **Headline value:** the mean of the repeats' p50 values. Latency is right-skewed, so the median is more stable than the mean.
- **95% CI:** a Student t interval over the repeat values, `mean +/- t(0.975, r-1) * s / sqrt(r)`. For r = 3 the multiplier is 4.30; the UI states
  that the interval is wide at r < 5 and offers 5 or more.
- **Percentiles (p95, p99)** are computed on the pooled iterations of all repeats and shown without a CI.
- **Comparing two variants:** Welch's t-test on the repeat values at alpha = 0.05. If the test is not significant, or the intervals overlap, the UI
  and the report say "no significant difference". The report never describes a speed-up as a fact without this test.
- **Accuracy** (mAP and drift) is deterministic for a fixed input set, so no CI: it is reported as a single value and a delta to the baseline.
- **Invalid runs:** any repeat during which a throttle flag was raised, or the clock dropped more than 10% below its starting value, is flagged
  and excluded from latency statistics by default (still stored and listed).
- The environment manifest records core layout, governor or power plan, and the number of threads and pinned cores for every run.

## Consequences
- Every number in the report traces to stored repeats, so it can be recomputed.
- With 3 repeats many differences will be "not significant"; that is an honest result, not a bug.
