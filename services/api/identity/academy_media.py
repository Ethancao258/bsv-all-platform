"""Private draft media admission. The isolated path never simulates a clean scan."""
import base64
import binascii
import fcntl
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import UUID

from fastapi import Request
from fastapi.responses import FileResponse
from pydantic import Field

from domains.learning.academy_models import Course, CourseVersion, Media
from domains.workforce.identity.core import has_action
from domains.workforce.identity.models import uid
from . import api as identity
from .academy_api import Slug, TextRef, academy_router, actor, audited, course_and_version, error, isolated, manager, training_access
from .academy_policy import LEGAL, assets_for, media_path

MAX_BYTES = 2_800_000
MAX_STORAGE = 256 * 1024 * 1024
MAX_ASSETS = 8


class Upload(identity.StrictModel):
    filename: str = Field(min_length=1, max_length=120)
    mime: str = Field(max_length=40)
    content_base64: str = Field(max_length=3_733_336)
    rights_ref: TextRef


def controlled_paths():
    root = os.environ.get("BSV_ACADEMY_MEDIA_ROOT", "")
    binary = os.environ.get("BSV_ACADEMY_CLAMDSCAN", "")
    if not root or not binary:
        return None
    root, binary = Path(root), Path(binary)
    try:
        if (root.is_absolute() and root.is_dir() and not root.is_symlink()
                and not root.stat().st_mode & 0o077 and os.access(root, os.W_OK)
                and binary.is_absolute() and binary.name == "clamdscan" and binary.is_file() and os.access(binary, os.X_OK)):
            return root, binary
    except OSError:
        pass
    return None


def media_ready():
    return controlled_paths() is not None


def match_media(mime, blob):
    if mime == "application/pdf":
        return blob.startswith(b"%PDF-") and b"%%EOF" in blob[-1024:]
    if mime == "image/png":
        return blob.startswith(bytes.fromhex("89504e470d0a1a0a")) and blob[12:16] == b"IHDR" and b"IEND" in blob[-16:]
    if mime == "image/jpeg":
        return blob.startswith(bytes.fromhex("ffd8ff")) and blob.endswith(bytes.fromhex("ffd9"))
    if mime == "video/mp4":
        size = int.from_bytes(blob[:4], "big")
        return 16 <= size <= len(blob) and blob[4:8] == b"ftyp" and blob[8:12] in (b"isom", b"mp41", b"mp42", b"iso2", b"avc1")
    return False


def checked_upload(body):
    if "/" in body.filename or "\\" in body.filename or re.search(r"[\x00-\x1f\x7f]", body.filename):
        error("MEDIA_NAME_INVALID", 422, "请选择文件名规范的课件。")
    try:
        blob = base64.b64decode(body.content_base64, validate=True)
    except (ValueError, binascii.Error):
        error("MEDIA_INVALID", 422, "课件内容格式有误。")
    if len(blob) > MAX_BYTES:
        error("MEDIA_TOO_LARGE", 413, "请将课件控制在 2.8 MB 以内。")
    if not match_media(body.mime, blob):
        error("MEDIA_TYPE_INVALID", 422, "只接受与文件内容相符的 MP4、PNG、JPEG 或 PDF。")
    return blob


def scan(binary, path):
    try:
        result = subprocess.run([str(binary), "--fdpass", "--no-summary", "--infected", str(path)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        error("MEDIA_SCAN_UNAVAILABLE", 503, "暂时无法扫描课件，请稍后重试。")
    if result.returncode == 1:
        error("MEDIA_SCAN_REJECTED", 422, "课件安全检查未通过。")
    if result.returncode != 0:
        error("MEDIA_SCAN_UNAVAILABLE", 503, "未取得扫描结果，文件未发布。")


def asset_ref(asset):
    return {"asset_id": asset.asset_id, "filename": asset.filename, "mime": asset.mime,
            "size": asset.size, "sha256": asset.digest, "url": "/api/v1/academy/media/" + asset.asset_id}


@academy_router.post("/courses/{course_id}/{version}/media", status_code=201)
def upload(course_id: Slug, version: int, body: Upload, request: Request):
    isolated()
    final = None
    try:
        with identity.router.session(write=True) as db:
            subject, person = manager(db, request, "qualification.attest")
            family, revision = course_and_version(db, course_id, version, lock=True)
            if revision.status != "draft" or revision.author != person.tr_code:
                error("MEDIA_DRAFT_ONLY", 403, "只能为自己创建的草稿添加课件。")
            blob = checked_upload(body)
            configured = controlled_paths()
            if configured is None:
                error("MEDIA_SCAN_UNAVAILABLE", 503, "课件存储或安全扫描尚未启用。")
            root, binary = configured
            digest = hashlib.sha256(blob).hexdigest()
            assets = assets_for(db, course_id, version)
            for asset in assets:
                if asset.digest == digest:
                    if asset.rights_ref == body.rights_ref and asset.filename == body.filename and asset.mime == body.mime:
                        if media_path(asset) is None:
                            error("MEDIA_UNAVAILABLE", 503, "暂时无法核验已登记课件。")
                        return asset_ref(asset)
                    error("MEDIA_CONFLICT", 409, "同一课件已登记了其他来源或名称。")
            if len(assets) >= MAX_ASSETS:
                error("MEDIA_QUOTA", 409, "该版本的课件数量已满。")
            asset = Media(asset_id=uid(), course_id=course_id, version=version, filename=body.filename, mime=body.mime,
                          rights_ref=body.rights_ref, digest=digest, size=len(blob))
            fd = os.open(root / ".upload.lock", os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, 0o600)
            with os.fdopen(fd, "wb") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                size = sum(path.lstat().st_size for path in root.glob("*.bin"))
                if size + len(blob) > MAX_STORAGE:
                    error("MEDIA_QUOTA", 409, "私有课件存储已达上限。")
                with tempfile.NamedTemporaryFile(dir=root, prefix=".scan-", delete=False) as upload_temp:
                    temp = Path(upload_temp.name)
                try:
                    temp.write_bytes(blob)
                    scan(binary, temp)
                    final = root / (asset.asset_id + ".bin")
                    os.replace(temp, final)
                finally:
                    temp.unlink(missing_ok=True)
            db.add(asset)
            audited(db, "media.accepted", person, subject, course_id=course_id, version=version, asset_id=asset.asset_id)
            db.flush()
            return asset_ref(asset)
    except BaseException:
        if final:
            final.unlink(missing_ok=True)
        raise


@academy_router.get("/media/{asset_id}")
def private_media(asset_id: UUID, request: Request):
    isolated()
    with identity.router.session() as db:
        subject, person = actor(db, request)
        item = db.get(Media, str(asset_id))
        family = db.get(Course, item.course_id) if item else None
        row = db.get(CourseVersion, (item.course_id, item.version)) if item else None
        if not family or not row or family.legal_entity_id != LEGAL:
            error("MEDIA_NOT_FOUND", 404, "未找到课件。")
        staff = (has_action(db, subject, "qualification.attest", legal_entity_id=LEGAL)
                 or has_action(db, subject, "stage.issue", legal_entity_id=LEGAL))
        if not staff and (row.status != "published" or not training_access(db, subject, person, family.store_id)):
            error("MEDIA_NOT_FOUND", 404, "未找到课件。")
        path = media_path(item)
        if not path:
            error("MEDIA_UNAVAILABLE", 503, "课件暂不可用，请联系培训负责人。")
        disposition = "attachment" if item.mime == "application/pdf" else "inline"
        return FileResponse(path, media_type=item.mime, filename=item.filename, content_disposition_type=disposition,
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
