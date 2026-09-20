"""Пример программной работы с FastAPI Gateway сервером SQLShift.

Демонстрирует:
1. Создание экземпляра сервера через фабрику create_app().
2. Отправку запросов к /v1/route и /v1/health через тестовый HTTP-клиент.
3. Интеграцию шлюза в другие веб-приложения или микросервисы.
"""

import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8") # ty: ignore[call-non-callable]
    except Exception:
        pass

from fastapi.testclient import TestClient

from sqlshift.server import ServerSettings, create_app


def main() -> None:
    print("=" * 70)
    print(">>> SQLShift -- Демонстрация HTTP Gateway API")
    print("=" * 70)

    # 1. Программное создание инстанса шлюза с кастомными настройками
    settings = ServerSettings(
        title="My Custom SQL Gateway",
        version="1.0.0",
    )
    app = create_app(settings=settings)

    # 2. Создание HTTP-клиента
    client = TestClient(app)

    # 3. Запрос статуса /health
    print("\n[*] 1. Проверка состояния шлюза (GET /v1/health):")
    health_resp = client.get("/v1/health")
    print(f"  HTTP Status: {health_resp.status_code}")
    print(f"  Response:    {health_resp.json()}")

    # 4. Запрос маршрутизации (POST /v1/route)
    print("\n[*] 2. Маршрутизация запроса через HTTP (POST /v1/route):")
    query_payload = {
        "sql": "SELECT date_trunc('month', created_at), sum(amount) FROM payments GROUP BY 1"
    }
    route_resp = client.post("/v1/route", json=query_payload)
    print(f"  HTTP Status: {route_resp.status_code}")
    route_data = route_resp.json()
    print(f"  Целевая база:       {route_data['target'].upper()}")
    print(f"  Сложность:          {route_data['estimated_complexity']}")
    print(f"  Транспайленный SQL: {route_data['sql']}")

    # 5. Демонстрация обработки ошибок (400 Bad Request)
    print("\n[*] 3. Обработка синтаксической ошибки SQL (POST /v1/route):")
    bad_payload = {"sql": "SELECT FROM;"}
    bad_resp = client.post("/v1/route", json=bad_payload)
    print(f"  HTTP Status: {bad_resp.status_code}")
    print(f"  Error Body:  {bad_resp.json()}")

    print("\n[i] Для запуска живого HTTP-сервера выполните команду в терминале:")
    print("     uv run sqlshift serve --port 8000")
    print("   Интерактивная документация Swagger будет доступна по адресу:")
    print("     http://127.0.0.1:8000/docs")

    print("\n[OK] Демонстрация работы сервера успешно завершена!")


if __name__ == "__main__":
    main()
