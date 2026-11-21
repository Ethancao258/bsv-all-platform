#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "platform/lighthouse/internal-stage"))
import ops003_release as release
import ops003_publish_cos as publish


def run_evidence():
    return {"url": release.CI_RUN_URL, "headSha": release.TARGET_SHA, "event": "pull_request",
            "status": "completed", "conclusion": "success", "workflowName": "validate-architecture"}


def jobs():
    return [{"name": name, "status": "completed", "conclusion": "success"}
            for name in sorted(release.REQUIRED_JOBS)]


class Response:
    def __init__(self, payload): self.payload = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit): return self.payload[:limit]


class FakeCOS:
    def __init__(self): self.call = None
    def put_object(self, **kwargs):
        body = kwargs["Body"].read()
        self.call = {**{key: value for key, value in kwargs.items() if key != "Body"},
                     "body_sha256": hashlib.sha256(body).hexdigest(), "body_size": len(body)}
        return {"ETag": '"synthetic-etag"'}


class PublishTests(unittest.TestCase):
    def test_oidc_to_sts_to_private_immutable_cos_happy_path(self):
        with tempfile.TemporaryDirectory(prefix="bsv-ops003-publish-") as temporary:
            output = Path(temporary) / "release"
            packaged = release.build(run_evidence(), jobs(), output)
            bundle = Path(packaged["bundle"])
            checksum = bundle.with_name(bundle.name + ".sha256")
            expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            credentials = {"TmpSecretId": "AKID12345678", "TmpSecretKey": "s" * 48,
                           "Token": "t" * 64}
            calls = []
            def opener(request, timeout):
                calls.append(request)
                if request.full_url.startswith("https://pipelines.actions.githubusercontent.com/"):
                    self.assertIn("audience=sts.cloud.tencent.com", request.full_url)
                    self.assertTrue(request.get_header("Authorization").startswith("Bearer "))
                    return Response({"value": "a" * 100 + "." + "b" * 100 + "." + "c" * 100})
                self.assertEqual(request.full_url, "https://sts.tencentcloudapi.com/")
                self.assertEqual(request.get_header("Authorization"), "SKIP")
                body = json.loads(request.data)
                self.assertEqual(body["RoleArn"], "qcs::cam::uin/1234567890:roleName/bsv-ops003-cos")
                self.assertEqual(body["ProviderId"], "github-ops003")
                self.assertEqual(body["DurationSeconds"], 900)
                return Response({"Response": {"Credentials": credentials, "Expiration": expires}})

            cos = FakeCOS()
            result = publish.publish(
                bundle_path=bundle, checksum_path=checksum, bucket="bsv-artifacts-1250000000",
                region="ap-shanghai", role_arn="qcs::cam::uin/1234567890:roleName/bsv-ops003-cos",
                provider_id="github-ops003",
                environ={"ACTIONS_ID_TOKEN_REQUEST_URL": "https://pipelines.actions.githubusercontent.com/run/token",
                         "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "masked-github-token"},
                oidc_opener=opener, sts_opener=opener, client_factory=lambda got, region: cos)
            self.assertEqual(len(calls), 2)
            self.assertEqual(cos.call["Key"], f"bsv-ops-003/{release.TARGET_SHA}/{packaged['sha256']}.tar")
            self.assertEqual(cos.call["IfNoneMatch"], "*")
            self.assertEqual(cos.call["ACL"], "private")
            self.assertEqual(cos.call["ServerSideEncryption"], "AES256")
            self.assertEqual(cos.call["Metadata"]["sha256"], packaged["sha256"])
            self.assertEqual(cos.call["body_sha256"], packaged["sha256"])
            self.assertFalse(result["host_contacted"])
            self.assertNotIn("s" * 20, json.dumps(result))
            self.assertNotIn("t" * 20, json.dumps(result))

    def test_rejects_non_github_oidc_endpoint_and_wrong_region_before_network(self):
        with self.assertRaisesRegex(publish.PublishError, "OIDC token endpoint"):
            publish._read_oidc_token({"ACTIONS_ID_TOKEN_REQUEST_URL": "https://attacker.invalid/token",
                                      "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "x"})
        with self.assertRaisesRegex(publish.PublishError, "region"):
            publish._assume_role(token="a.b.c", role_arn="qcs::cam::uin/1234567890:roleName/x",
                                 provider_id="idp", region="us-west-1")


if __name__ == "__main__":
    unittest.main()
