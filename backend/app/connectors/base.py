from typing import Protocol

from app.normalization import NormalizedEntity


class ConnectorError(RuntimeError):
    """Safe, payload-free error for unavailable or incomplete connector reads."""


class ConnectorProtocol(Protocol):
    def healthcheck(self) -> bool: ...
    def fetch_entities(self) -> list[NormalizedEntity]: ...
    def get_entity(self, external_id: str) -> NormalizedEntity | None: ...
    def search_entities(self, **attributes: str) -> list[NormalizedEntity]: ...


class MemoryConnector:
    def __init__(self, entities: list[NormalizedEntity]):
        self.entities = entities

    def healthcheck(self):
        return True

    def fetch_entities(self):
        return list(self.entities)

    def get_entity(self, external_id):
        return next((entity for entity in self.entities if entity.external_id == external_id), None)

    def search_entities(self, **attributes):
        return [
            e
            for e in self.entities
            if all(getattr(e.attributes, key, None) == value for key, value in attributes.items())
        ]
