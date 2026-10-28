"""Explicit test-access boundary for Task 003B."""

from __future__ import annotations

from dataclasses import dataclass, field


class TestAccessError(PermissionError):
    pass


TEST_ACTIONS = {"parse_label", "build_feature", "count_class", "fit", "score", "emit_prediction"}


@dataclass
class AccessAudit:
    authorize_test: bool = False
    events: list[dict] = field(default_factory=list)

    def require(self, *, partition: str, action: str, sample_id: str | None = None) -> None:
        if action not in TEST_ACTIONS:
            raise TestAccessError(f"unknown access action: {action}")
        if partition == "test" and not self.authorize_test:
            raise TestAccessError(f"test {action} is not authorized")
        self.events.append({"partition": partition, "action": action, "sample_id": sample_id})

    @property
    def test_accessed(self) -> bool:
        return any(event["partition"] == "test" for event in self.events)
