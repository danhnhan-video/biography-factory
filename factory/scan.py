"""Bước 1 của máy chủ: quét DanhNhan/_inbox, nhận việc, chia thành các job dựng video.

Mỗi file JSON = 1 job (1 ngôn ngữ). Bản Việt chạy trước, bản dịch chạy sau.
File được chuyển sang _dang_lam để không bị nhận 2 lần.
"""
from __future__ import annotations
import json, os, sys, traceback
from .drive import Drive
from .common import CONF, LANG_NAMES
from . import notify
from . import video_pipeline as vp


def out(name, value):
    line = f"{name}={value}"
    print("  ->", line)
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def main():
    d = Drive(); ids = d.init_root(CONF["drive_root"])
    jobs = [f for f in d.ls(ids["_inbox"], folder=False) if f["name"].lower().endswith(".json")]
    print(f"_inbox có {len(jobs)} file JSON")
    vi, other, names = [], [], []
    for i, f in enumerate(jobs):
        path = f"/tmp/scan_job_{i}.json"
        try:
            d.download(f["id"], path)
            pkg = json.load(open(path, encoding="utf-8"))
            slug, lang = pkg["slug"], vp.norm_lang(pkg.get("lang"))
            if not pkg.get("slides") and not pkg.get("only_short"):
                raise ValueError("gói không có slides")
            if not (CONF.get("voices") or {}).get(lang):
                raise ValueError(f"config.json chưa có giọng đọc cho '{lang}'")
        except BaseException as e:
            msg = f"{type(e).__name__}: {e}"
            print("❌", f["name"], msg)
            d.write_text(f["name"] + ".loi.txt", f"File JSON không hợp lệ:\n{msg}\n\n{traceback.format_exc()}", ids["_loi"])
            d.move(f["id"], ids["_inbox"], ids["_loi"])
            notify.send("❌ File JSON lỗi", f"{f['name']}: {msg}", tags=("warning",), priority=4)
            continue
        # tạo sẵn thư mục kết quả (tránh tạo trùng khi nhiều job chạy song song)
        slug_id = d.folder(slug, ids["output"]); d.folder(vp.LANGS[lang]["folder"], slug_id); d.folder("images", slug_id)
        d.move(f["id"], ids["_inbox"], ids["_dang_lam"])
        job = {"id": f["id"], "name": f["name"], "slug": slug, "lang": lang}
        (vi if lang == "vi" else other).append(job)
        names.append(f"{pkg.get('figure', slug)} – {LANG_NAMES[lang]}")
    out("vi", json.dumps(vi, ensure_ascii=False))
    out("other", json.dumps(other, ensure_ascii=False))
    out("has_vi", "true" if vi else "false")
    out("has_other", "true" if other else "false")
    if names:
        notify.send("🎬 Bắt đầu dựng video", f"{len(names)} việc: " + "; ".join(names))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        notify.send("❌ Máy chủ lỗi khi quét _inbox", f"{type(e).__name__}: {e}", tags=("warning",), priority=4)
        raise
