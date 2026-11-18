"""Local QR decoding and explicitly consented external candidate recognition."""
import httpx
from cv2 import QRCodeDetector, IMREAD_COLOR, imdecode, error as CVError
import numpy as np

from services.api.supply.config import auth_header


def preview_candidates(blob, source, *, allow_external=False):
    recognized = []
    try:
        image = imdecode(np.frombuffer(blob, dtype=np.uint8), IMREAD_COLOR)
        if image is not None:
            detector = QRCodeDetector()
            ok, values, _, _ = detector.detectAndDecodeMulti(image)
            if ok:
                recognized = list(dict.fromkeys(value for value in values if value))
            if not recognized:
                value, _, _ = detector.detectAndDecode(image)
                if value:
                    recognized = [value]
    except CVError:
        pass
    result = dict(mode="LOCAL_QR_ONLY", recognized_package_ids=recognized,
                  item_candidates=[], unknown_regions=["仅本地二维码候选；尚未确认商品"],
                  requires_human_confirmation=True, posted=False)
    if not allow_external or not source.primary:
        return result
    try:
        with httpx.Client(timeout=12, follow_redirects=False) as client:
            response = client.post(source.primary + "/extract", files={"file": ("photo", blob)},
                                   headers=auth_header(source))
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            return result
        codes = data.get("recognized_package_ids", [])
        candidates = data.get("item_candidates", [])
        unknown = data.get("unknown_regions", [])
        if (isinstance(codes, list) and all(isinstance(code, str) and 0 < len(code) <= 128 for code in codes)
                and isinstance(candidates, list) and isinstance(unknown, list)):
            result.update(mode="EXTERNAL_VISION_CANDIDATES",
                          recognized_package_ids=list(dict.fromkeys(recognized + codes)),
                          item_candidates=candidates, unknown_regions=unknown)
    except (httpx.HTTPError, ValueError):
        pass
    return result
