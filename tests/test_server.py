from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from sqlshift.server import create_app


def test_health_check() -> None:
    """Проверяем эндпоинт healthcheck."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["postgres_conf"] is False
    assert data["clickhouse_conf"] is False


def test_route_oltp_query() -> None:
    """Транзакционный запрос отправляется в PostgreSQL без изменений."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/v1/route", json={"sql": "SELECT id, name FROM users WHERE id = 42"})
    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "postgresql"
    assert data["is_analytical"] is False
    assert "users WHERE id = 42" in data["sql"]


def test_route_olap_query() -> None:
    """Аналитический запрос маршрутизируется в ClickHouse с транспайлингом."""
    app = create_app()
    client = TestClient(app)

    sql = "SELECT date_trunc('month', created_at), count(*) FROM events GROUP BY 1"
    response = client.post("/v1/route", json={"sql": sql})
    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "clickhouse"
    assert data["is_analytical"] is True
    # Проверяем, что в ClickHouse попал соответствующий диалект
    assert "toStartOfMonth" in data["sql"] or "dateTrunc" in data["sql"]


def test_route_invalid_sql_returns_400() -> None:
    """Синтаксическая ошибка в SQL возвращает HTTP 400 и структурированный JSON."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/v1/route", json={"sql": "SELECT FROM WHERE"})
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "SQLParsingError"
    assert "message" in data


def test_query_without_db_returns_503() -> None:
    """Попытка выполнить запрос без настроенных БД возвращает 503."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/v1/query", json={"sql": "SELECT 1"})
    assert response.status_code == 503
    assert "Database client not configured" in response.json()["detail"]


def test_query_with_mock_client() -> None:
    """Исполнение запроса с внедрением mock-клиента (Dependency Injection)."""
    mock_client = AsyncMock()
    mock_client.fetch.return_value = [{"id": 1, "username": "alex"}]

    # Передаем мок в фабрику!
    app = create_app(client=mock_client)
    client = TestClient(app)

    response = client.post("/v1/query", json={"sql": "SELECT id, username FROM users WHERE id = 1"})
    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "postgresql"
    assert data["row_count"] == 1
    assert data["data"] == [{"id": 1, "username": "alex"}]
    assert data["exec_time_ms"] >= 0.0

    # Проверяем, что мок был вызван с нужным запросом
    mock_client.fetch.assert_awaited_once_with("SELECT id, username FROM users WHERE id = 1")


def test_route_response_schema_fields() -> None:
    """Проверяет наличие новых полей reason_code, physical_tables, catalog_checked в ответе."""
    app = create_app()
    client = TestClient(app)

    sql = "SELECT count(*) FROM events GROUP BY user_id"
    response = client.post("/v1/route", json={"sql": sql})
    assert response.status_code == 200
    data = response.json()

    assert "reason_code" in data
    assert data["reason_code"] == "ANALYTICAL_CLICKHOUSE"
    assert "physical_tables" in data
    assert data["physical_tables"] == ["events"]
    assert "catalog_checked" in data
    assert data["catalog_checked"] is False


def test_server_with_catalog_parameter() -> None:
    """Проверяет передачу каталога через аргумент create_app(catalog=...)."""
    from sqlshift.core.catalog import TableCatalog

    catalog = TableCatalog(
        allowed_tables=["orders"],
        pg_only_tables=["returns"],
    )
    app = create_app(catalog=catalog)
    client = TestClient(app)

    # 1. orders -> ClickHouse
    sql1 = "SELECT status, count(*) FROM orders GROUP BY status"
    r1 = client.post("/v1/route", json={"sql": sql1})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["target"] == "clickhouse"
    assert d1["catalog_checked"] is True
    assert d1["reason_code"] == "ANALYTICAL_CLICKHOUSE"
    assert d1["physical_tables"] == ["orders"]

    # 2. returns -> PostgreSQL (pinned)
    sql2 = "SELECT status, count(*) FROM returns GROUP BY status"
    r2 = client.post("/v1/route", json={"sql": sql2})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["target"] == "postgresql"
    assert d2["catalog_checked"] is True
    assert d2["reason_code"] == "TABLE_PG_PINNED"

    # 3. payments -> PostgreSQL (not in catalog)
    sql3 = "SELECT status, count(*) FROM payments GROUP BY status"
    r3 = client.post("/v1/route", json={"sql": sql3})
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["target"] == "postgresql"
    assert d3["catalog_checked"] is True
    assert d3["reason_code"] == "TABLE_NOT_IN_CATALOG"


def test_server_with_settings_catalog() -> None:
    """Проверяет создание каталога на основе ServerSettings(allowed_tables=...)."""
    from sqlshift.server.config import ServerSettings

    settings = ServerSettings(
        allowed_tables=["orders", "order_items"],
        postgres_only_tables=["returns"],
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    sql_orders = "SELECT status, count(*) FROM orders GROUP BY status"
    r = client.post("/v1/route", json={"sql": sql_orders})
    assert r.status_code == 200
    data = r.json()
    assert data["target"] == "clickhouse"
    assert data["catalog_checked"] is True

    r_pinned = client.post(
        "/v1/route", json={"sql": "SELECT reason, count(*) FROM returns GROUP BY reason"}
    )
    assert r_pinned.status_code == 200
    d_pinned = r_pinned.json()
    assert d_pinned["target"] == "postgresql"
    assert d_pinned["reason_code"] == "TABLE_PG_PINNED"


def test_server_with_empty_catalog() -> None:
    """Проверяет, что пустой список allowed_tables в настройках блокирует ClickHouse."""
    from sqlshift.server.config import ServerSettings

    settings = ServerSettings(allowed_tables=[])
    app = create_app(settings=settings)
    client = TestClient(app)

    r = client.post("/v1/route", json={"sql": "SELECT count(*) FROM orders GROUP BY status"})
    assert r.status_code == 200
    data = r.json()
    assert data["target"] == "postgresql"
    assert data["catalog_checked"] is True
    assert data["reason_code"] == "TABLE_NOT_IN_CATALOG"
