# SQLShift Reproducible Benchmark Report

- **Run ID**: `20261111_195132`
- **Timestamp (UTC)**: `2026-11-11T19:51:32.032327+00:00`
- **OS**: Windows 10 (AMD64)
- **CPU**: AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD (12 logical cores)
- **Python**: 3.13.5 (CPython)
- **SQLGlot**: 30.18.0
- **Git Commit**: `a18846f4dfb8f6bd1b513c57fce9e69cbd580337`

## Measurement Methodology
- **Clock**: `time.perf_counter_ns()`
- **Warmup**: 50 iterations per query
- **Samples**: 1000 / query / mode (Total: 16000)
- **Isolation**: Router instantiation and all I/O strictly excluded from timing loop.

## Latency Summary & Catalog Overhead Comparison

| Query ID | Description | No-Cat Med (µs) | Cat Med (µs) | Overhead Δ | Overhead % | Cat p95 (µs) |
|---|---|---|---|---|---|---|
| `Q1_OLTP_LOOKUP` | OLTP PK Lookup | 257.7 | 261.7 | +4.0 | +1.6% | 445.3 |
| `Q2_OLTP_FILTER` | OLTP Multi-Filter | 311.4 | 312.6 | +1.2 | +0.4% | 389.0 |
| `Q3_OLAP_GROUP_BY` | OLAP Group By Agg | 417.7 | 430.1 | +12.3 | +3.0% | 627.6 |
| `Q4_OLAP_WINDOW` | OLAP Window Function | 374.5 | 384.4 | +9.9 | +2.6% | 506.3 |
| `Q5_MULTI_JOIN` | Multi-table Join (3 tables) | 786.6 | 801.3 | +14.7 | +1.9% | 1001.7 |
| `Q6_CTE_AGG` | Scope CTE Aggregation | 585.4 | 591.6 | +6.2 | +1.1% | 830.3 |
| `Q7_DASHBOARD_COMPLEX` | Complex Dashboard | 772.3 | 774.2 | +1.9 | +0.2% | 1020.6 |
| `Q8_SCALAR_NO_TABLES` | Scalar Without Tables | 204.4 | 205.5 | +1.1 | +0.5% | 273.8 |

## Key Findings
1. **Target Latency SLA**: All 8 query templates exhibit median and p95 latency below 1.5 ms (1500 µs) on the test platform. Medians range from 205.5 to 801.3 µs, and maximum p95 across templates is 1020.6 µs (6 of 8 templates have p95 < 850 µs). Individual outliers may exceed this bound, so 1.5 ms cannot be guaranteed for every single arbitrary query invocation.
2. **Catalog Overhead**: Adding table catalog checks increases median latency by 0.25% to 2.96% (+1.1 to +14.7 µs). Note that both modes execute `extract_physical_tables()`; thus, this delta reflects the incremental cost of catalog lookup, not the full cost of AST scope analysis.
3. **Reproducibility**: Complete raw timing records are archived in `benchmark_raw.csv`.
