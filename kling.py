"""kling.py — tạo ảnh minh họa bằng Kling AI (text-to-image) cho slide sách nói.

Cấu hình bằng GitHub Secrets (KHÔNG ghi khóa vào code hay JSON):
  KLING_API_KEY                         — khóa API mới (Authorization: Bearer <API Key>), HOẶC
  KLING_ACCESS_KEY + KLING_SECRET_KEY   — cặp khóa kiểu cũ (tự ký JWT HS256, hạn 30 phút)
Tuỳ chọn (Variables/Secrets): KLING_BASE (mặc định https://api-singapore.klingai.com),
  KLING_MODEL (mặc định kling-v2-1 = Kling Image 2.1, ~0,014 USD/ảnh; đổi sang kling-v3 nếu cần đẹp hơn), KLING_RESOLUTION (mặc định 2k).
Tài liệu: https://kling.ai/document-api/api/image/3-0-omni/image-generation.md
"""
from __future__ import annotations
import base64, hashlib, hmac, json, os, time
from pathlib import Path

import requests

BASE = os.environ.get("KLING_BASE", "https://api-singapore.klingai.com").rstrip("/")
MODEL = (os.environ.get("KLING_MODEL") or "kling-v2-1").strip()
RES = (os.environ.get("KLING_RESOLUTION") or "2k").strip()

STYLE = ("cinematic film still, historical drama set in 1815–1830 France, muted natural colour palette with warm "
         "amber highlights and cool teal shadows, soft directional light, subtle volumetric haze, 35mm film grain, "
         "shallow depth of field, realistic textures, moderate sharpness, painterly composition")
NEGATIVE = ("text, letters, caption, subtitles, watermark, logo, signature, modern clothing, modern objects, cartoon, "
            "anime, 3d render, cgi, plastic skin, oversaturated, neon, deformed hands, extra fingers, extra limbs, "
            "disfigured face, gore, blood, nudity, celebrity likeness, film actor likeness")


def budget(minutes: float, override=None) -> int:
    """Số ảnh Kling tối đa cho 1 tập (gồm cả thumbnail): 7–10 tuỳ độ dài (~1 ảnh / 7 phút).
    50 phút → 7, 55 → 8, 60–65 → 9, ≥ 67 → 10. Gói có thể ghi đè bằng "kling_max"."""
    if override:
        return max(0, int(override))
    return max(7, min(10, round(minutes / 7)))


def available() -> bool:
    return bool(os.environ.get("KLING_API_KEY") or (os.environ.get("KLING_ACCESS_KEY") and os.environ.get("KLING_SECRET_KEY")))


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _token() -> str:
    if os.environ.get("KLING_API_KEY"):
        return os.environ["KLING_API_KEY"].strip()
    ak, sk = os.environ["KLING_ACCESS_KEY"].strip(), os.environ["KLING_SECRET_KEY"].strip()
    now = int(time.time())
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"iss": ak, "exp": now + 1800, "nbf": now - 5}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(sk.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def _hdr():
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def generate(prompt: str, out: Path, negative: str = "", aspect: str = "16:9", style: bool = True,
             log=print, timeout_s: int = 600) -> Path:
    """Tạo 1 ảnh, tải về `out` (jpg/png). Lỗi thì raise RuntimeError."""
    full = f"{prompt.strip().rstrip('.')}. {STYLE}" if style else prompt
    body = {"model_name": MODEL, "prompt": full[:2500], "negative_prompt": (negative or NEGATIVE)[:2500],
            "n": 1, "aspect_ratio": aspect, "resolution": RES}
    delay = 2
    for attempt in range(8):                               # tạo task (chờ khi vượt giới hạn song song)
        r = requests.post(f"{BASE}/v1/images/generations", headers=_hdr(), json=body, timeout=60)
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 200 and j.get("code") == 0:
            tid = j["data"]["task_id"]; break
        if j.get("code") == 1303 or r.status_code == 429:
            log(f"    Kling bận (song song) — chờ {delay}s"); time.sleep(delay); delay = min(delay * 2, 60); continue
        if r.status_code == 400 and "resolution" in body:   # model không nhận tham số resolution → bỏ đi, thử lại
            log(f"    Kling từ chối tham số ({str(j or r.text)[:120]}) — thử lại không có resolution")
            body.pop("resolution"); continue
        raise RuntimeError(f"Kling tạo task lỗi HTTP {r.status_code}: {str(j or r.text)[:200]}")
    else:
        raise RuntimeError("Kling: vượt giới hạn song song quá lâu")
    t0 = time.time()
    while time.time() - t0 < timeout_s:                     # chờ kết quả
        time.sleep(6)
        g = requests.get(f"{BASE}/v1/images/generations/{tid}", headers=_hdr(), timeout=60).json()
        d = g.get("data") or {}
        st = d.get("task_status")
        if st == "succeed":
            imgs = (d.get("task_result") or {}).get("images") or []
            if not imgs:
                raise RuntimeError("Kling: task xong nhưng không có ảnh")
            a = requests.get(imgs[0]["url"], timeout=120); a.raise_for_status()
            out.write_bytes(a.content)
            return out
        if st == "failed":
            raise RuntimeError(f"Kling: task thất bại — {d.get('task_status_msg', '')[:200]}")
    raise RuntimeError("Kling: quá thời gian chờ")
