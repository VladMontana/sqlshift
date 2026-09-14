```markdown
# AGENT EXECUTION PLAN: `sqlshift` (Python Library / SDK)

## 1. Project Goal
Develop an installable, standalone Python library (`sqlshift`) that provides an in-memory SQL router and AST transpiler (PostgreSQL -> ClickHouse) via `sqlglot`, alongside an optional async client wrapper for zero-overhead execution[cite: 1]. The library must follow standard packaging practices managed by `uv`.

## 2. Package Design & Architecture
The project follows a strict **Library-First** design:
- **Core Package (`sqlshift.core`)**: Zero network I/O. Depends only on `sqlglot`[cite: 1]. Parses queries into an AST, identifies analytical markers (OLAP vs OLTP), and transpiles dialects[cite: 1].
- **Client Layer (`sqlshift.client`)**: Optional async executor wrapping `asyncpg` and `clickhouse-connect` to execute decisions directly in Python runtimes.
- **Server Extension (`sqlshift.server`)**: Optional standalone HTTP gateway on FastAPI for external services[cite: 1].

```text
sqlshift/
├── pyproject.toml
├── README.md
├── src/
│   └── sqlshift/
│       ├── __init__.py          # Public API export: SQLRouter, RouteDecision, SmartClient
│       ├── py.typed             # PEP 561 typing marker
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py        # RouteDecision dataclass
│       │   ├── parser.py        # sqlglot parser wrapper
│       │   ├── analyzer.py      # AST heuristic evaluator (IS_ANALYTICAL)
│       │   └── transpiler.py    # PG -> ClickHouse transpiler
│       ├── client/
│       │   ├── __init__.py
│       │   └── async_client.py  # SmartClient pool manager (asyncpg + clickhouse)
│       └── server/
│           ├── __init__.py
│           └── app.py           # Optional FastAPI gateway implementation
├── examples/
│   ├── basic_usage.py           # In-memory SDK routing example
│   └── client_usage.py          # SmartClient dual-database dispatch example
└── tests/
    ├── test_router.py           # Unit tests for core AST logic (no DB needed)
    └── test_transpiler.py       # Dialect conversion unit tests

```

---

## 3. Dependency Specification (`pyproject.toml`)

```toml
[project]
name = "sqlshift"
version = "0.1.0"
description = "Cross-dialect SQL query router and transpiler for hybrid OLTP/OLAP systems"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "sqlglot>=25.0.0",
]

[project.optional-dependencies]
# Installed via: uv add --extra client ".[client]"
client = [
    "asyncpg>=0.29.0",
    "clickhouse-connect>=0.7.0",
]
# Installed via: uv add --extra server ".[server]"
server = [
    "fastapi>=0.110.0",
    "uvicorn>=0.30.0",
    "pydantic-settings>=2.0.0",
]
# All extras combined
all = [
    "sqlshift[client,server]",
]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.5.0",
    "mypy>=1.10.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

```

---

## 4. Step-by-Step Implementation Plan for Agent

### Phase 1: Environment & Project Scaffolding

* Initialize project with `uv`:
```bash
uv init --lib sqlshift

```


* Configure `pyproject.toml` with the dependency layout specified above.
* Add `src/sqlshift/py.typed` to support type hints for downstream consumers.

### Phase 2: Core In-Memory Engine (`src/sqlshift/core/`)

*Rule: Strictly no imports from `asyncpg`, `fastapi`, or `clickhouse_connect` in this directory.*

1. **`models.py`**:
* Define `RouteDecision`:
```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class RouteDecision:
    target: Literal["postgres", "clickhouse"]
    sql: str
    is_analytical: bool
    estimated_complexity: str  # e.g., "LOW", "HIGH"

```




2. **`parser.py`**:
* Wrap `sqlglot.parse_one(sql, read="postgres")`.


* Catch syntax errors and re-raise as a custom `SQLParsingError`.


3. **`analyzer.py`**:
* Implement `is_analytical(tree: exp.Expression) -> bool` by walking the AST:


* Match OLAP signals: `exp.AggFunc` (`COUNT`, `SUM`, `AVG`), `exp.Group`, `exp.Window`, `exp.Cube`, `exp.Rollup`.


* Match OLTP signals: Primary key/index single-row lookups, DML statements (`Insert`, `Update`, `Delete`).






4. **`transpiler.py`**:
* Implement `transpile_to_clickhouse(tree: exp.Expression) -> str` using `tree.sql(dialect="clickhouse")`.


* Add AST transformations for PostgreSQL-specific constructs where ClickHouse requires alternative syntax (e.g., date truncation mapping, type casts).


5. **`router.py`**:
* Create class `SQLRouter`:
```python
class SQLRouter:
    def route(self, sql: str) -> RouteDecision: ...

```





### Phase 3: Public Library Interface (`src/sqlshift/__init__.py`)

* Expose the public API at the package root:
```python
from sqlshift.core.models import RouteDecision
from sqlshift.core.router import SQLRouter

__all__ = ["SQLRouter", "RouteDecision"]

```



### Phase 4: Async Client Layer (`src/sqlshift/client/`)

* Implement `SmartClient` using dynamic imports so users without the `[client]` extra receive a clear `ImportError`:
```python
class SmartClient:
    def __init__(self, pg_dsn: str, ch_dsn: str): ...
    async def connect(self): ...
    async def close(self): ...
    async def fetch(self, sql: str) -> list[dict]:
        decision = self.router.route(sql)
        if decision.target == "clickhouse":
            return await self._execute_clickhouse(decision.sql)
        return await self._execute_postgres(decision.sql)

```



### Phase 5: Optional Server / Demo Layer (`src/sqlshift/server/`)

* Provide a minimal FastAPI application exposing `POST /v1/query` and `POST /v1/route` to showcase HTTP proxy usage.


* Provide `examples/basic_usage.py` for standalone in-memory routing and `examples/client_usage.py` for dual-DB execution.

### Phase 6: Unit Testing & Packaging Validation

1. **Engine Tests (`tests/test_router.py`)**:
* Verify OLTP queries (`SELECT * FROM users WHERE id = 1`) route to `postgres` with unchanged SQL.


* Verify OLAP queries (`SELECT date_trunc('month', created_at), COUNT(*) FROM events GROUP BY 1`) route to `clickhouse` with transpiled SQL.


* Verify that DML queries (`INSERT INTO users ...`) always route to `postgres`.




2. **Build Validation**:
* Run `uv run pytest` (must pass 100% without external DB containers running).
* Run `uv build` and verify that both `.whl` and `.tar.gz` artifacts build cleanly.
* Run `uv run ruff check .` and `uv run mypy src`.



---

## 5. Definition of Done

1. Package installs in editable mode via `uv pip install -e .`.
2. Pure library usage works out of the box with zero runtime database requirements:
```python
from sqlshift import SQLRouter
router = SQLRouter()
result = router.route("SELECT count(*) FROM table")
assert result.target == "clickhouse"

```


3. Dialect transpilation produces valid ClickHouse syntax from standard PostgreSQL syntax.


4. Package builds successfully via `uv build`.

```

```