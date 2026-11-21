#!/usr/bin/env python3
"""Publish the pinned, signed OPS-003 bundle to one immutable COS key via GitHub OIDC."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import ops003_release


class PublishError(ValueError):
    pass


def _read_oidc_token(environ=None, opener=urllib.request.urlopen) -> str:
    env = os.environ if environ is None else environ
    url = env.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    request_token = env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "pipelines.actions.githubusercontent.com"
            or not request_token or parsed.username or parsed.password):
        raise PublishError("GitHub OIDC token endpoint is unavailable")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "audience"]
    query.append(("audience", "sts.cloud.tencent.com"))
    token_url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(token_url, headers={"Authorization": f"Bearer {request_token}",
                                                         "Accept": "application/json"})
    try:
        with opener(request, timeout=10) as response:
            payload = json.loads(response.read(64 * 1024))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise PublishError("GitHub OIDC token request failed") from error
    token = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not 100 <= len(token) <= 20_000 or token.count(".") != 2:
        raise PublishError("GitHub OIDC response did not contain a valid JWT")
    return token


def _assume_role(*, token: str, role_arn: str, provider_id: str, region: str,
                 opener=urllib.request.urlopen) -> tuple[dict, str]:
    if not re.fullmatch(r"qcs::cam::uin/[0-9]{5,20}:roleName/[A-Za-z0-9_-]{1,64}", role_arn):
        raise PublishError("Tencent role ARN is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", provider_id):
        raise PublishError("Tencent OIDC provider ID is invalid")
    if not re.fullmatch(r"ap-[a-z0-9-]{3,24}", region):
        raise PublishError("Tencent STS region is invalid")
    request_body = {"RoleArn": role_arn, "ProviderId": provider_id,
                    "WebIdentityToken": token, "RoleSessionName": "bsv-ops-003-gha",
                    "DurationSeconds": 900}
    request = urllib.request.Request(
        "https://sts.tencentcloudapi.com/",
        data=json.dumps(request_body, separators=(",", ":")).encode(),
        headers={"Authorization": "SKIP", "Content-Type": "application/json; charset=utf-8",
                 "X-TC-Action": "AssumeRoleWithWebIdentity", "X-TC-Version": "2018-08-13",
                 "X-TC-Region": region}, method="POST")
    try:
        with opener(request, timeout=15) as response:
            payload = json.loads(response.read(64 * 1024))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise PublishError("Tencent STS did not issue the short-lived role session") from error
    result = payload.get("Response", {}) if isinstance(payload, dict) else {}
    credentials = result.get("Credentials", {})
    expires_at = result.get("Expiration")
    if (not isinstance(credentials, dict) or not re.fullmatch(r"AKID[A-Za-z0-9]{8,64}", credentials.get("TmpSecretId", ""))
            or len(credentials.get("TmpSecretKey", "")) < 32 or len(credentials.get("Token", "")) < 16
            or not isinstance(expires_at, str)):
        raise PublishError("Tencent STS response is incomplete")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise PublishError("Tencent STS expiration is invalid") from error
    if expiry.tzinfo is None or (expiry - datetime.now(timezone.utc)).total_seconds() < 60:
        raise PublishError("Tencent STS credentials are too close to expiry")
    return credentials, expires_at


def _cos_client(credentials: dict, region: str):
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as error:
        raise PublishError("Pinned Tencent COS SDK is unavailable") from error
    config = CosConfig(Region=region, SecretId=credentials["TmpSecretId"],
                       SecretKey=credentials["TmpSecretKey"], Token=credentials["Token"],
                       Scheme="https")
    return CosS3Client(config)


def publish(*, bundle_path: Path, checksum_path: Path, bucket: str, region: str,
            role_arn: str, provider_id: str, environ=None, oidc_opener=urllib.request.urlopen,
            sts_opener=urllib.request.urlopen, client_factory=_cos_client) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}-[0-9]{6,16}", bucket):
        raise PublishError("COS bucket name is invalid")
    if not re.fullmatch(r"ap-[a-z0-9-]{3,24}", region):
        raise PublishError("COS region is invalid")
    verified = ops003_release.verify(bundle_path, checksum_path)
    token = _read_oidc_token(environ, oidc_opener)
    credentials, expires_at = _assume_role(token=token, role_arn=role_arn,
                                            provider_id=provider_id, region=region,
                                            opener=sts_opener)
    client = client_factory(credentials, region)
    object_key = (f"bsv-ops-003/{ops003_release.TARGET_SHA}/"
                  f"{verified['bundle_sha256']}.tar")
    bundle_size = bundle_path.stat().st_size
    with bundle_path.open("rb") as source:
        response = client.put_object(
            Bucket=bucket, Key=object_key, Body=source, ContentLength=bundle_size,
            ContentType="application/x-tar", ACL="private", ServerSideEncryption="AES256",
            IfNoneMatch="*", Metadata={"sha256": verified["bundle_sha256"],
                                       "target-sha": ops003_release.TARGET_SHA})
    if not isinstance(response, dict) or not response.get("ETag"):
        raise PublishError("COS did not confirm creation of the immutable object")
    return {"state": "UPLOADED", "target_sha": ops003_release.TARGET_SHA,
            "object_key": object_key, "sha256": verified["bundle_sha256"],
            "size_bytes": bundle_size, "credential_expires_at": expires_at,
            "host_contacted": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--sha256", required=True, type=Path)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--provider-id", required=True)
    args = parser.parse_args(argv)
    result = publish(bundle_path=args.bundle, checksum_path=args.sha256, bucket=args.bucket,
                     region=args.region, role_arn=args.role_arn, provider_id=args.provider_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PublishError, OSError, urllib.error.URLError) as error:
        # Never echo SDK errors, HTTP bodies, OIDC tokens, or temporary credentials.
        raise SystemExit("BSV-OPS-003 COS publish failed; inspect the private Tencent audit trail") from None
