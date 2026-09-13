from datetime import timedelta

from app.connectors.base import MemoryConnector
from app.normalization import normalize_1c


class Mock1C(MemoryConnector):
    def __init__(self, anchor):
        super().__init__(
            [
                normalize_1c(
                    {
                        "Ref_Key": f"order-{external_id}",
                        "CRMDealID": str(external_id),
                        "Total": amount,
                        "Customer": "1004",
                        "Currency": "RUB",
                        "Date": anchor + timedelta(minutes=2),
                        "UpdatedAt": anchor + timedelta(minutes=2),
                    }
                )
                for external_id, amount in [(5822, "50000.00"), (5823, "90000.00")]
            ]
        )
