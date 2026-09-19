"""System randomness implementation kept outside the domain layer."""

import secrets


class SystemRandomSource:
    def randbelow(self, upper_bound: int) -> int:
        return secrets.randbelow(upper_bound)