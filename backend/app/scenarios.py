"""Synthetic scenario catalogue shared by in-memory demo and HTTP contract simulator."""

from datetime import timedelta
from decimal import Decimal
from typing import Literal

from app.connectors.base import MemoryConnector
from app.connectors.mock_1c import Mock1C
from app.connectors.mock_bitrix import MockBitrix

Scenario = Literal["baseline", "healthy", "duplicate", "wrong_amount", "delay", "pending", "outage"]
SCENARIOS = [
    {"id": "baseline", "name": "Исходное демо", "description": "Нет заказа #5821; сумма #5823 отличается."},
    {"id": "healthy", "name": "Восстановление", "description": "Все заказы существуют, суммы и сроки совпадают."},
    {"id": "duplicate", "name": "Дубль заказа", "description": "Два разных заказа ссылаются на сделку #5821."},
    {"id": "wrong_amount", "name": "Разная сумма", "description": "По сделке #5823 заказ на 10 000 ₽ меньше."},
    {"id": "delay", "name": "Поздний заказ", "description": "Заказ #5821 появился через 6 минут вместо 5."},
    {
        "id": "pending",
        "name": "В пределах срока",
        "description": "Сделка #5821 завершена 2 минуты назад; заказ ещё ожидается.",
    },
    {
        "id": "outage",
        "name": "1С недоступна",
        "description": "HTTP 503: результат неизвестен, старые инциденты сохраняются.",
    },
]


def fixture(scenario: Scenario, anchor, now):
    sources = MockBitrix(anchor).entities
    targets = Mock1C(anchor).entities
    if scenario not in {"baseline", "outage"}:
        targets[1] = targets[1].model_copy(
            update={"attributes": targets[1].attributes.model_copy(update={"amount": Decimal("100000")})}
        )
        template = targets[0]
        order = template.model_copy(
            update={
                "external_id": "order-5821",
                "attributes": template.attributes.model_copy(
                    update={"external_reference": "5821", "amount": Decimal("184000")}
                ),
            }
        )
        if scenario != "pending":
            targets.append(order)
        if scenario == "duplicate":
            targets.append(order.model_copy(update={"external_id": "order-5821-duplicate"}))
        elif scenario == "wrong_amount":
            targets[1] = targets[1].model_copy(
                update={"attributes": targets[1].attributes.model_copy(update={"amount": Decimal("90000")})}
            )
        elif scenario == "delay":
            late = anchor + timedelta(minutes=6)
            targets[-1] = order.model_copy(update={"created_at": late, "updated_at": late})
        elif scenario == "pending":
            sources[0] = sources[0].model_copy(
                update={
                    "updated_at": now,
                    "attributes": sources[0].attributes.model_copy(
                        update={"status_changed_at": now - timedelta(minutes=2)}
                    ),
                }
            )

    class Offline(MemoryConnector):
        def healthcheck(self):
            return False

    return MemoryConnector(sources), Offline(targets) if scenario == "outage" else MemoryConnector(targets)
