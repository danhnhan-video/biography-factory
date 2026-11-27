"""Luồng dựng SÁCH NÓI (audiobook) — dự án "Dịch tiểu thuyết tự động".

Mỗi gói `Tap_XX.audiobook.json` trong My Drive/SachNoi/_inbox = 1 tập video 50–70 phút:
  hook + câu giới thiệu → các chương trọn vẹn → lời kết CTA,
  hình là poster tĩnh (đổi theo chương đang đọc), kèm Shorts dọc, thumbnail, mô tả có mục lục.

  python -m factory.audiobook                       # quét SachNoi/_inbox, dựng lần lượt
  python -m factory.audiobook --local goi.json --assets thu_muc_anh --out ket_qua --fake-tts   # thử trên máy

Ảnh (thumbnail, poster, nền Shorts) do Claude thiết kế sẵn và để trong thư mục `assets_folder_id`.
Kết quả được tải lên `output_folder_id`. Audio đã đọc được lưu lại → chạy lại không tốn credit Vbee lần hai.
"""
from __future__ import annotations
import argparse, json, os, random, re, shutil, subprocess, sys, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import video_pipeline as vp

ROOT_NAME = "SachNoi"
WORK = Path(os.environ.get("FACTORY_WORK", "/tmp/sachnoi"))
VW, VH, VFPS = 1920, 1080, 6               # video tĩnh: 6 khung/giây là đủ, dựng nhanh, nhẹ
GAP_CHAPTER, GAP_BLOCK, MAX_CHARS = 2.0, 1.2, 1500


# ----------------------------------------------------------------------------- tiện ích
def split_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Chia lời đọc thành đoạn ≤ limit ký tự: ưu tiên ranh giới đoạn văn, rồi câu, cuối cùng dấu phẩy."""
    units = []                                          # (câu, có phải đầu đoạn văn)
    for p in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        sents = [p] if len(p) <= limit else [x for x in re.split(r"(?<=[.!?…”])\s+", p) if x]
        for j, s in enumerate(sents):
            while len(s) > limit:
                k = s.rfind(",", 0, limit); k = k if k > limit // 2 else limit
                units.append((s[:k + 1].strip(), j == 0)); s = s[k + 1:].strip(); j = 1
            units.append((s, j == 0))
    out, cur = [], ""
    for s, new_para in units:
        sep = "\n\n" if new_para else " "
        if cur and len(cur) + len(sep) + len(s) > limit:
            out.append(cur); cur = s
        else:
            cur = f"{cur}{sep}{s}" if cur else s
    if cur:
        out.append(cur)
    return out


def silence(sec: float, out: Path) -> Path:
    if not out.exists():
        vp.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{sec:.2f}",
                "-c:a", "libmp3lame", "-b:a", "128k", str(out)])
    return out


def fake_tts(text: str, out: Path, cfg: dict):
    """Thử trên máy không có Vbee: tiếng 'bíp' nhỏ, độ dài ≈ tốc độ đọc thật (~15 ký tự/giây)."""
    if out.exists():
        return out
    sec = max(1.0, len(text) / 15.0)
    vp.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=330:duration={sec:.2f}",
            "-af", "volume=0.05", "-ar", "48000", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k", str(out)])
    return out


def concat_audio(files: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".list.txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in files), encoding="utf-8")
    vp.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)])
    return out


# ----------------------------------------------------------------------------- dựng 1 tập
def build_episode(pkg: dict, assets: Path, out: Path, cfg: dict, music: Path | None, fake=False) -> dict:
    vp.CUR["lang"] = "vi"
    work = out / "_work"; audio_dir = work / "audio"
    for d in (out, work, audio_dir):
        d.mkdir(parents=True, exist_ok=True)
    vcfg = dict(cfg, VOICE_CODE=pkg.get("voice") or cfg.get("VOICE_CODE"), SPEED=pkg.get("speed", cfg.get("SPEED", 1.0)))
    tts = (lambda t, o: fake_tts(t, o, vcfg)) if fake else (lambda t, o: vp.vbee_tts(t, o, vcfg))

    # 1. lời đọc → danh sách đoạn
    jobs = []                                          # (part_index, file, text)
    for i, part in enumerate(pkg["parts"]):
        texts = part.get("segments") or split_text(part["text"])
        part["_files"] = []
        for k, t in enumerate(texts):
            f = audio_dir / f"{i:02d}_{part['id']}_{k:03d}.mp3"
            part["_files"].append(f); jobs.append((f, t))
    total = sum(len(t) for _, t in jobs)
    vp.log(f"1/5 Vbee đọc {len(jobs)} đoạn ({total:,} ký tự), giọng {vcfg['VOICE_CODE']}…")
    done = [0]
    def one(job):
        f, t = job; tts(t, f); done[0] += 1
        if done[0] % 10 == 0 or done[0] == len(jobs):
            vp.log(f"  audio {done[0]}/{len(jobs)}")
    with ThreadPoolExecutor(max_workers=1 if fake else 4) as ex:
        list(ex.map(one, jobs))

    # 2. ghép audio theo phần, tính mốc thời gian
    vp.log("2/5 Ghép audio…")
    gap_c = silence(GAP_CHAPTER, work / "gap_chapter.mp3"); gap_b = silence(GAP_BLOCK, work / "gap_block.mp3")
    seq, timeline, t = [], [], 0.0                     # timeline: (start, end, poster, label)
    for i, part in enumerate(pkg["parts"]):
        if i:
            g = gap_c if part.get("kind") == "chapter" else gap_b
            seq.append(g); t += vp.duration(g)
            if timeline:                                # khoảng nghỉ thuộc về hình của phần trước
                s0, _, p0, l0 = timeline[-1]; timeline[-1] = (s0, t, p0, l0)
        start = t
        for f in part["_files"]:
            seq.append(f); t += vp.duration(f)
        timeline.append((start, t, part.get("poster") or pkg["images"]["poster_intro"], part.get("label")))
    narration = concat_audio(seq, work / "narration.wav")
    D = vp.duration(narration)

    # 3. nhạc nền nhẹ chỉ dưới phần mở đầu và lời kết (không đè lên chương)
    vp.log("3/5 Trộn nhạc nền mở đầu/kết…")
    mixed = work / "mixed.m4a"
    first_ch = next((s for s, _, _, l in timeline if l), timeline[0][1])
    last_ch_end = [e for s, e, _, l in timeline if l][-1] if any(l for *_, l in timeline) else D
    if music and music.exists():
        vol = (f"volume='if(lt(t,{first_ch:.2f}),0.10,if(gt(t,{last_ch_end:.2f}),0.10,0))':eval=frame")
        fc = (f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{D:.2f},{vol},afade=t=in:d=2,"
              f"afade=t=out:st={max(D - 4, 0):.2f}:d=4[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]")
        vp.run(["ffmpeg", "-y", "-i", str(narration), "-i", str(music), "-filter_complex", fc,
                "-map", "[a]", "-c:a", "aac", "-b:a", "160k", str(mixed)])
    else:
        vp.run(["ffmpeg", "-y", "-i", str(narration), "-c:a", "aac", "-b:a", "160k", str(mixed)])

    # 4. video: poster tĩnh đổi theo phần
    vp.log("4/5 Dựng video chính…")
    lst = work / "images.list.txt"; lines = []
    for s, e, poster, _ in timeline:
        lines += [f"file '{(assets / poster).resolve()}'", f"duration {e - s:.3f}"]
    lines.append(f"file '{(assets / timeline[-1][2]).resolve()}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    video = out / f"{pkg['slug']}.mp4"
    vp.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(mixed),
            "-vf", f"scale={VW}:{VH}:force_original_aspect_ratio=decrease,pad={VW}:{VH}:(ow-iw)/2:(oh-ih)/2,"
                   f"fps={VFPS},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "23", "-r", str(VFPS),
            "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(video)])
    vp.log(f"   video ✓ {vp.fmt_ts(vp.duration(video))}")

    # 5. mô tả, mục lục, thumbnail, Shorts
    vp.log("5/5 Mô tả, mục lục, Shorts…")
    chapters = [(0.0, pkg["youtube"].get("intro_label", "Mở đầu"))]
    chapters += [(s, l) for s, _, _, l in timeline if l]
    outro_start = timeline[-1][0]
    if pkg["parts"][-1].get("kind") == "outro":
        chapters.append((outro_start, pkg["youtube"].get("outro_label", "Lời kết")))
    write_meta(pkg, chapters, out)
    shutil.copy(assets / pkg["images"]["thumbnail"], out / "thumbnail.jpg")
    build_short(pkg, assets, out, work, vcfg, music, tts)
    (out / "script_audiobook.txt").write_text(
        "\n\n".join(f"[{p.get('label') or p['id']}]\n" + (p.get("text") or "\n\n".join(p.get("segments", [])))
                    for p in pkg["parts"]), encoding="utf-8")
    return {"video": video, "duration": vp.duration(video)}


def write_meta(pkg: dict, chapters: list[tuple[float, str]], d: Path):
    m = pkg["youtube"]
    chap = "\n".join(f"{vp.fmt_ts(t)} {name}" for t, name in chapters)
    tags = vp.hashtags(m.get("hashtags", []))
    desc = m["description"].strip().replace("{CHAPTERS}", chap)
    if "{CHAPTERS}" not in m["description"]:
        desc += f"\n\n⏱️ MỤC LỤC\n{chap}"
    desc = f"{desc}\n\n{tags}\n"
    (d / "youtube_description.txt").write_text(desc[:4990], encoding="utf-8")
    (d / "youtube_title.txt").write_text("\n".join([m["title"]] + m.get("alt_titles", [])), encoding="utf-8")
    tag_list, total = [], 0
    for t in vp.clean_tags(m.get("tags", [])):
        if total + len(t) + 2 > 480: break
        tag_list.append(t); total += len(t) + 2
    (d / "tags.txt").write_text(", ".join(tag_list), encoding="utf-8")
    (d / "facebook_post.txt").write_text(m.get("facebook_post", "") + "\n\n" + tags, encoding="utf-8")
    (d / "chapters.txt").write_text(chap, encoding="utf-8")


def build_short(pkg: dict, assets: Path, out: Path, work: Path, vcfg: dict, music: Path | None, tts):
    sh = pkg.get("short")
    if not sh or not sh.get("scenes"):
        return None
    d = work / "short"; d.mkdir(parents=True, exist_ok=True)
    sp = round(vcfg.get("SPEED", 1.0) * 0.95, 3)
    rnd = random.Random(pkg["slug"] + "-short")
    trans_pool = [t for t in vp.available_transitions()
                  if t in ("fade", "smoothleft", "smoothright", "slideleft", "slideright", "zoomin", "hblur")] or ["fade"]
    scenes, transitions, prev = [], [], None
    for i, sc in enumerate(sh["scenes"], 1):
        bgsrc = assets / (sc.get("background") or sh.get("background") or pkg["images"]["short_bg"])
        bg = d / f"s{i:02d}_bg.png"
        shutil.copy(bgsrc, bg)                           # nền dọc 1080x1920 do Claude thiết kế
        chunks = vp.split_chunks(sc.get("subtitle") or sc["narration"], max_words=6)
        hook, subs = vp.short_text_layers(sc.get("hook_text", ""), chunks, d, i)
        audio = work / "audio" / f"short_{i:02d}.mp3"
        _tts_speed(tts, sc["narration"], audio, sp, vcfg)
        motion = rnd.choice([m for m in ["zoom_in", "zoom_out", "tilt_up", "tilt_down"] if m != prev]); prev = motion
        scenes.append(vp.make_short_scene(bg, hook, subs, chunks, audio, d / f"scene_{i:02d}.mp4", motion, None))
        if i > 1:
            transitions.append(rnd.choice([t for t in trans_pool if not transitions or t != transitions[-1]] or trans_pool))
    video = out / f"{pkg['slug']}_short.mp4"
    vp.assemble(scenes, transitions, music, video, work=d, xd=vp.S_XFADE, music_vol=0.14, fade_in=0.2, fade_out=0.6)
    tags = vp.hashtags(["#Shorts"] + list(sh.get("hashtags") or []))
    (out / "short_title.txt").write_text(sh.get("title", "")[:95], encoding="utf-8")
    (out / "short_description.txt").write_text(f"{sh.get('description', '').strip()}\n\n{tags}\n", encoding="utf-8")
    vp.log(f"   short ✓ {vp.duration(video):.1f} giây")
    return video


def _tts_speed(tts, text, out, speed, vcfg):
    old = vcfg.get("SPEED"); vcfg["SPEED"] = speed
    try:
        tts(text, out)
    finally:
        vcfg["SPEED"] = old


# ----------------------------------------------------------------------------- máy chủ (Google Drive)
def server():
    from .drive import Drive
    from .common import CONF, folder_link
    from . import notify
    for k in ("VBEE_TOKEN", "VBEE_APP_ID"):
        if not os.environ.get(k):
            raise SystemExit(f"❌ Thiếu GitHub Secret {k}")
    cfg = {"VBEE_TOKEN": os.environ["VBEE_TOKEN"], "VBEE_APP_ID": os.environ["VBEE_APP_ID"],
           "VOICE_CODE": CONF.get("voices", {}).get("vi"), "SPEED": 1.0,
           "VBEE_WEBHOOK": CONF.get("vbee_webhook", "https://example.com/vbee-callback")}
    d = Drive(); ids = d.init_root(ROOT_NAME)
    jobs = [f for f in d.ls(ids["_inbox"], folder=False) if f["name"].lower().endswith(".json")]
    print(f"SachNoi/_inbox có {len(jobs)} gói")
    if not jobs:
        return
    music = None
    for root in (ids["music"],):
        mp3s = [f for f in d.ls(root, folder=False) if f["name"].lower().endswith(".mp3")]
        if mp3s:
            music = WORK / "music.mp3"; WORK.mkdir(parents=True, exist_ok=True); d.download(mp3s[0]["id"], str(music)); break
    f = jobs[0]                                         # mỗi lần chạy dựng 1 tập (tập dài ~1 giờ)
    d.move(f["id"], ids["_inbox"], ids["_dang_lam"])
    job = WORK / f["name"]; job.parent.mkdir(parents=True, exist_ok=True); d.download(f["id"], str(job))
    pkg = json.loads(job.read_text(encoding="utf-8"))
    notify.send("🎧 Bắt đầu dựng sách nói", f"{pkg.get('book')} – Tập {pkg.get('episode')}")
    assets, out = WORK / "assets" / pkg["slug"], WORK / "out" / pkg["slug"]
    assets.mkdir(parents=True, exist_ok=True); (out / "_work" / "audio").mkdir(parents=True, exist_ok=True)
    for a in d.ls(pkg["assets_folder_id"], folder=False):
        d.download(a["id"], str(assets / a["name"]))
    dst = pkg["output_folder_id"]
    au = d.ls(dst, "audio", folder=True)
    if au:                                               # audio của lần chạy trước → không đọc lại
        for a in d.ls(au[0]["id"], folder=False):
            d.download(a["id"], str(out / "_work" / "audio" / a["name"]))
    try:
        r = build_episode(pkg, assets, out, cfg, music)
        vp.log("Tải kết quả lên Google Drive…")
        for p in sorted(out.glob("*")):
            if p.is_file():
                d.upload(str(p), dst)
        aid = d.folder("audio", dst)
        for p in sorted((out / "_work" / "audio").glob("*")):
            d.upload(str(p), aid)
        d.move(f["id"], ids["_dang_lam"], ids["_done"])
        notify.send(f"✅ Xong sách nói: {pkg.get('book')} – Tập {pkg.get('episode')}",
                    f"Video {vp.fmt_ts(r['duration'])} + Shorts", link=folder_link(dst))
    except BaseException as e:
        msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        print("❌", msg)
        try:
            aid = d.folder("audio", dst)
            for p in sorted((out / "_work" / "audio").glob("*")):
                d.upload(str(p), aid)
        except Exception:
            pass
        d.move(f["id"], ids["_dang_lam"], ids["_loi"]); d.write_text(f["name"] + ".loi.txt", msg, ids["_loi"])
        notify.send("❌ Dựng sách nói thất bại", f"{f['name']}\n{msg.splitlines()[0]}", link=folder_link(ids["_loi"]),
                    tags=("warning",), priority=4)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local"); ap.add_argument("--assets"); ap.add_argument("--out")
    ap.add_argument("--fake-tts", action="store_true"); ap.add_argument("--music")
    a = ap.parse_args()
    if a.local:
        pkg = json.loads(Path(a.local).read_text(encoding="utf-8"))
        cfg = {"VOICE_CODE": pkg.get("voice"), "SPEED": 1.0}
        if not a.fake_tts:
            cfg.update(VBEE_TOKEN=os.environ["VBEE_TOKEN"], VBEE_APP_ID=os.environ["VBEE_APP_ID"])
        r = build_episode(pkg, Path(a.assets), Path(a.out), cfg, Path(a.music) if a.music else None, fake=a.fake_tts)
        print("XONG", r)
    else:
        server()


if __name__ == "__main__":
    main()
