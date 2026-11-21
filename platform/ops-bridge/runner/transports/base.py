from __future__ import annotations

from typing import Protocol


class TransportError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class CloudTransport(Protocol):
    def read_diagnose(self, task: dict) -> dict: ...
    def verify_artifact(self, task: dict) -> dict: ...


class TATInvoker(Protocol):
    def invoke_fixed_runner(self, *, command_id: str, instance_ids: tuple[str, ...], parameters: dict) -> dict: ...


class COSBucket(Protocol):
    def put_object(self, *, key: str, body: bytes, private: bool, encryption: str,
                   forbid_overwrite: bool) -> None: ...
    def get_object(self, *, key: str) -> bytes: ...
