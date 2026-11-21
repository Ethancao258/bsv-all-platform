from transports.base import TransportError


class NoOpCloudTransport:
    """Safe default when one-time cloud authorization is absent; never opens a socket."""
    host_contacted = False

    def read_diagnose(self, task: dict) -> dict:
        raise TransportError("CLOUD_AUTH_NOT_CONFIGURED", "Tencent cloud authorization is not configured")

    def verify_artifact(self, task: dict) -> dict:
        raise TransportError("CLOUD_AUTH_NOT_CONFIGURED", "Tencent cloud authorization is not configured")
