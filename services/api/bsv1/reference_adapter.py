"""Reference-read port for the future primary and verified snapshot readers."""
from typing import Protocol

from bsv_data_router import Route, select_source


class ReferenceReader(Protocol):
    def read(self, domain: str, key: str) -> object: ...


def read_reference(
    domain: str, key: str, primary: ReferenceReader, snapshot: ReferenceReader,
    *, primary_healthy: bool, snapshot_valid: bool,
) -> tuple[Route, object]:
    """The caller supplies trusted health and snapshot verification results."""
    route = select_source(operation="READ_REFERENCE", domain=domain,
                          primary_healthy=primary_healthy, snapshot_valid=snapshot_valid)
    reader = primary if route.source == "DB_A" else snapshot
    return route, reader.read(domain, key)
