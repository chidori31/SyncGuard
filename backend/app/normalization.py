from decimal import Decimal
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


def identifier(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("Invalid external identifier")
    return str(value)


class Attributes(BaseModel):
    status: str = ""
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False)
    currency: str = Field(default="RUB", pattern=r"^[A-Z]{3}$")
    customer_id: str = Field(min_length=1, max_length=100)
    external_reference: str | None = None
    status_changed_at: AwareDatetime | None = None
    model_config = ConfigDict(frozen=True, extra="forbid")


class NormalizedEntity(BaseModel):
    source: str
    entity_type: str
    external_id: str = Field(min_length=1, max_length=100)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    attributes: Attributes
    model_config = ConfigDict(frozen=True)


def normalize_bitrix(raw: dict[str, Any]) -> NormalizedEntity:
    return NormalizedEntity(
        source="bitrix24",
        entity_type="deal",
        external_id=identifier(raw["ID"]),
        created_at=raw["DATE_CREATE"],
        updated_at=raw["DATE_MODIFY"],
        attributes=Attributes(
            status=raw["STAGE_ID"],
            amount=str(raw["OPPORTUNITY"]),
            currency=raw["CURRENCY_ID"],
            customer_id=identifier(raw["CONTACT_ID"]),
            status_changed_at=raw["WON_AT"],
        ),
    )


def normalize_1c(raw: dict[str, Any]) -> NormalizedEntity:
    return NormalizedEntity(
        source="1c",
        entity_type="customer_order",
        external_id=identifier(raw["Ref_Key"]),
        created_at=raw["Date"],
        updated_at=raw["UpdatedAt"],
        attributes=Attributes(
            amount=str(raw["Total"]),
            currency=raw["Currency"],
            customer_id=identifier(raw["Customer"]),
            external_reference=identifier(raw["CRMDealID"]) if raw.get("CRMDealID") not in (None, "") else None,
        ),
    )
