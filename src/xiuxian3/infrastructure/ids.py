"""System identifier implementation kept outside the domain layer."""

from uuid import uuid4


class UuidIdGenerator:
    def new_id(self) -> str:
        return str(uuid4())