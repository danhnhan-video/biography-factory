from __future__ import annotations
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
LANG_NAMES = {"vi": "Tiếng Việt", "en": "Tiếng Anh", "fr": "Tiếng Pháp", "es": "Tiếng Tây Ban Nha",
              "ar": "Tiếng Ả Rập", "zh": "Tiếng Trung"}


def pipeline_cfg() -> dict:
    """Cấu hình cho video_pipeline từ config.json + GitHub Secrets."""
    for k in ("VBEE_TOKEN", "VBEE_APP_ID"):
        if not os.environ.get(k):
            raise SystemExit(f"❌ Thiếu GitHub Secret {k}")
    voices = CONF.get("voices", {})
    return {
        "VBEE_TOKEN": os.environ["VBEE_TOKEN"], "VBEE_APP_ID": os.environ["VBEE_APP_ID"],
        "VOICE_CODE": voices.get("vi"), "VOICES": voices,
        "SPEED": CONF.get("speed", 1.0), "SPEEDS": CONF.get("speeds", {}),
        "VBEE_WEBHOOK": CONF.get("vbee_webhook", "https://example.com/vbee-callback"),
        "CONTACT": CONF.get("contact", ""),
    }


def folder_link(fid: str) -> str:
    return f"https://drive.google.com/drive/folders/{fid}"
