# sqlshift

Cross-dialect SQL query router and transpiler for hybrid OLTP/OLAP systems.

## Overview

`sqlshift` is an installable Python library providing:
- **Core Engine (`sqlshift.core`)**: Zero-I/O in-memory SQL router and AST transpiler (PostgreSQL → ClickHouse) using `sqlglot`.
- **Async Client (`sqlshift.client`)**: Optional high-level executor (`SmartClient`) automatically dispatching queries to PostgreSQL or ClickHouse.
- **Server Extension (`sqlshift.server`)**: Optional standalone FastAPI HTTP gateway.

## Installation

```bash
# Core in-memory engine only (minimal dependencies)
pip install sqlshift

# With async database execution support
pip install "sqlshift[client]"

# With FastAPI gateway server
pip install "sqlshift[server]"

# Everything included
pip install "sqlshift[all]"
```

## Quick Start (Core Router)

```python
from sqlshift import SQLRouter

router = SQLRouter()
decision = router.route("SELECT count(*) FROM analytics_events")
print(decision.target)  # "clickhouse"
print(decision.sql)     # Transpiled SQL for ClickHouse
```

## License

MIT
