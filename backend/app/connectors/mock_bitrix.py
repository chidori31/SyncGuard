from datetime import timedelta

from app.connectors.base import MemoryConnector
from app.normalization import normalize_bitrix


class MockBitrix(MemoryConnector):
    def __init__(self, anchor):
        super().__init__(
            [
                normalize_bitrix(
                    {
                        "ID": str(external_id),
                        "STAGE_ID": "WON",
                        "OPPORTUNITY": amount,
                        "CONTACT_ID": "1004",
                        "CURRENCY_ID": "RUB",
                        "WON_AT": anchor,
                        "DATE_CREATE": anchor - timedelta(hours=1),
                        "DATE_MODIFY": anchor,
                    }
                )
                for external_id, amount in [(5821, "184000.00"), (5822, "50000.00"), (5823, "100000.00")]
            ]
        )
