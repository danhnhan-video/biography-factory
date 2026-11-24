"""Bước 2 của máy chủ: dựng 1 gói (1 ngôn ngữ) → lưu kết quả lên Google Drive.

  python -m factory.render --id <file_id> --name <tên file>
  python -m factory.render --id <file_id> --name <tên file> --fail   (đánh dấu lỗi khi job bị huỷ/quá giờ)
"""
from __future__ import annotations
import argparse, glob, json, os, sys, traceback
from pathlib import Path
from .drive import Drive
from .common import CONF, LANG_NAMES, pipeline_cfg, folder_link
from . import notify
from . import video_pipeline as vp

WORK = Path(os.environ.get("FACTORY_WORK", "/tmp/factory"))


def pull(d: Drive, parent, local, overwrite=True):
    os.makedirs(local, exist_ok=True)
    for a in d.ls(parent, folder=False):
        p = f"{local}/{a['name']}"
        if overwrite or not os.path.exists(p):
            d.download(a["id"], p)


def push(d: Drive, ids, root: Path, out: Path, slug: str, lang_dir: str, lang: str) -> str:
    slug_id = d.folder(slug, ids["output"]); dst = d.folder(lang_dir, slug_id)
    for p in sorted(glob.glob(f"{out}/*")):
        if os.path.isfile(p):
            d.upload(p, dst)
    for sub, src in [("slides", out / "slides"), ("audio", out / "_work" / "audio")]:
        files = sorted(glob.glob(f"{src}/*"))
        if files:
            sid = d.folder(sub, dst)
            for p in files:
                d.upload(p, sid)
    # ảnh dùng chung: bản Việt đẩy lên; bản dịch chỉ đẩy ảnh mới (tránh ghi đè lẫn nhau khi chạy song song)
    iid = d.folder("images", slug_id)
    have = {x["name"] for x in d.ls(iid, folder=False)}
    for p in sorted(glob.glob(f"{root}/images/*")):
        if lang == "vi" or os.path.basename(p) not in have:
            d.upload(p, iid)
    if lang == "vi" and (root / "image_report.txt").exists():
        d.upload(str(root / "image_report.txt"), slug_id)
    return dst


def mark_failed(d: Drive, ids, fid: str, name: str, msg: str):
    for src in ("_dang_lam", "_inbox"):
        if any(x["id"] == fid for x in d.ls(ids[src], folder=False)):
            d.move(fid, ids[src], ids["_loi"]); break
    d.write_text(name + ".loi.txt", msg, ids["_loi"])
    notify.send("❌ Dựng video thất bại", f"{name}\n{msg.splitlines()[0] if msg else ''}\n"
                "Sửa xong, kéo file từ _loi về _inbox để chạy lại (audio đã đọc được giữ lại).",
                link=folder_link(ids["_loi"]), tags=("warning",), priority=4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True); ap.add_argument("--name", required=True)
    ap.add_argument("--fail", action="store_true")
    a = ap.parse_args()
    d = Drive(); ids = d.init_root(CONF["drive_root"])
    if a.fail:      # chỉ xử lý khi job bị huỷ/quá giờ mà file vẫn nằm trong _dang_lam
        if any(x["id"] == a.id for x in d.ls(ids["_dang_lam"], folder=False)):
            mark_failed(d, ids, a.id, a.name, "Job bị huỷ hoặc chạy quá thời gian cho phép (xem tab Actions trên GitHub).")
        return

    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "inbox" / a.name; path.parent.mkdir(parents=True, exist_ok=True)
    d.download(a.id, str(path))
    pkg = json.load(open(path, encoding="utf-8"))
    slug, lang = pkg["slug"], vp.norm_lang(pkg.get("lang"))
    lang_dir = vp.LANGS[lang]["folder"]
    root, out = WORK / "output" / slug, WORK / "output" / slug / lang_dir
    print(f"━━━━ {a.name} → output/{slug}/{lang_dir}")

    slug_id = d.folder(slug, ids["output"])
    img = d.ls(slug_id, "images", folder=True)
    if img:
        pull(d, img[0]["id"], f"{root}/images")
    ldir = d.ls(slug_id, lang_dir, folder=True)
    if ldir:
        au = d.ls(ldir[0]["id"], "audio", folder=True)
        if au:
            pull(d, au[0]["id"], f"{out}/_work/audio", overwrite=False)
    if lang != "vi":
        v = d.ls(slug_id, "Viet", folder=True)
        pj = d.ls(v[0]["id"], "production.json", folder=False) if v else []
        if pj:
            os.makedirs(f"{root}/Viet", exist_ok=True); d.download(pj[0]["id"], f"{root}/Viet/production.json")
    music = None
    mp3s = [f for f in d.ls(ids["music"], folder=False) if f["name"].lower().endswith(".mp3")]
    if mp3s:
        music = str(WORK / "music.mp3"); d.download(mp3s[0]["id"], music)

    try:
        vp.build(str(path), str(WORK / "output"), pipeline_cfg(), music_path=music)
        vp.log("Đang tải kết quả lên Google Drive…")
        dst = push(d, ids, root, out, slug, lang_dir, lang)
        d.move(a.id, ids["_dang_lam"], ids["_done"])
        mp4 = out / f"{slug}.mp4"
        dur = vp.fmt_ts(vp.duration(mp4)) if mp4.exists() else "chỉ Shorts"
        notify.send(f"✅ Xong: {pkg.get('figure', slug)} – {LANG_NAMES[lang]}",
                    f"Video {dur} + Shorts đã lưu ở output/{slug}/{lang_dir}", link=folder_link(dst))
        print(f"🎉 XONG: {folder_link(dst)}")
    except BaseException as e:
        msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        print("❌", msg)
        try:
            push(d, ids, root, out, slug, lang_dir, lang)          # giữ phần đã làm được (audio, ảnh)
        except Exception:
            pass
        mark_failed(d, ids, a.id, a.name, msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
