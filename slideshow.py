"""slideshow.py — trình chiếu nhiều slide cho video sách nói (dùng bởi factory/audiobook.py).

Mỗi slide trong gói JSON (đặt trong `parts[i].slides`):
  {
    "id": "s03",                          # duy nhất trong gói
    "title": "Ông thanh tra xuống hầm ngục", # tiêu đề tiếng Việt hiện trên slide (để trống = không hiện)
    "image_url": "https://commons.wikimedia.org/wiki/File:....jpg",   # ảnh tư liệu (tuỳ chọn)
    "candidates": ["https://commons.wikimedia.org/wiki/File:...", ...], # ảnh dự phòng (tuỳ chọn)
    "category": {"name": "The Count of Monte-Cristo 1887 Volume 1", "prefix": "COMC V1 D175"},  # tuỳ chọn
    "image": "art_03.png",                # tranh minh họa trong thư mục assets — dùng khi không có/không
                                          # tải được/không đúng giấy phép ảnh tư liệu (nên luôn có)
    "credit": "Minh họa: Sách nói Monte Cristo",  # credit khi dùng `image`; ảnh Commons tự lấy credit
    "anchor": "Một năm sau khi vua",      # slide bắt đầu khi lời đọc tới đoạn chữ này (khớp gần đúng)
    "at": 0.35,                           # hoặc: vị trí 0–1 trong phần (khi không có anchor)
    "motion": "zoom_in",                  # tuỳ chọn: zoom_in, zoom_out, pan_left, pan_right, tilt_up, tilt_down
    "prompt": "Mô tả cảnh bằng tiếng Anh…", # tuỳ chọn: máy chủ gọi Kling AI tạo ảnh điện ảnh (cần GitHub Secret
                                          # KLING_API_KEY hoặc KLING_ACCESS_KEY + KLING_SECRET_KEY). Có prompt thì
                                          # Kling được ưu tiên trước ảnh Commons, trừ khi "prefer": "commons".
    "negative_prompt": "…",               # tuỳ chọn
    "same_as": "c14d", "crop": "left"     # tuỳ chọn: dùng lại ảnh của slide khác nhưng cắt cận một vùng
                                          # (left/right/center/top/bottom) → thêm slide mà không tốn ảnh Kling
  }
Hạn mức Kling: mỗi tập chỉ tạo tối đa 7–10 ảnh Kling (gồm thumbnail) tuỳ độ dài — xem kling.budget().
Slide có prompt nhưng vượt hạn mức → dùng ảnh Commons / tranh dự phòng `image`.
Ảnh Kling đã tạo được lưu vào thư mục assets (tên kling_<id>_<mã prompt>.jpg) → dựng lại không tốn credit lần hai.
Ảnh Commons chỉ được dùng khi giấy phép là Public domain / CC0 / CC BY / CC BY-SA (không NC, không ND)
và rộng ≥ 900 px; nếu không đạt → dùng `image`. Mọi quyết định ghi vào `image_report.txt`.
"""
from __future__ import annotations
import json, math, random, re, shutil, unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import video_pipeline as vp
from . import kling
import hashlib

W, H, FPS = 1920, 1080, 25
LOOP_SEC = 36            # độ dài 1 vòng chuyển động (vòng lặp liền mạch, chậm, kiểu điện ảnh)
XF = 1.2                 # giây chuyển cảnh giữa hai slide
MIN_SLIDE = 18.0         # slide ngắn hơn thì gộp vào slide trước
MOTIONS = ["zoom_in", "zoom_out", "pan_right", "pan_left", "tilt_down", "tilt_up", "diag"]
GOLD, CREAM = (214, 174, 96), (243, 233, 210)
BAD_LIC = ("nc", "nd", "fair use", "non-free", "all rights reserved", "copyrighted")


def has_slides(pkg: dict) -> bool:
    return any(p.get("slides") for p in pkg.get("parts", []))


# ----------------------------------------------------------------------------- 1. ảnh
def _free(lic: str) -> bool:
    low = (lic or "").lower()
    if not low:
        return False
    toks = re.split(r"[^a-z0-9]+", low)
    if any(b in toks for b in ("nc", "nd")) or any(b in low for b in BAD_LIC[2:]):
        return False
    return any(k in low for k in vp.FREE_LICENSES) or "pdm" in low or "licence ouverte" in low


def _category_find(cat: str, prefix: str) -> str | None:
    """Tìm file trong một Category Commons có tên bắt đầu bằng `prefix` (vd 'COMC V1 D175')."""
    cont, pre = None, _norm(prefix)
    for _ in range(20):
        params = {"action": "query", "format": "json", "list": "categorymembers", "cmtype": "file",
                  "cmtitle": "Category:" + cat.replace("Category:", ""), "cmlimit": 500}
        if cont:
            params["cmcontinue"] = cont
        j = vp.polite_get(vp.COMMONS_API, params).json()
        for m in j.get("query", {}).get("categorymembers", []):
            name = m["title"].split(":", 1)[1]
            if _norm(name).startswith(pre):
                return name
        cont = j.get("continue", {}).get("cmcontinue")
        if not cont:
            return None
    return None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[\s_]+", " ", s).strip()


def _crop(src: Path, out: Path, where: str, zoom: float = 1.45) -> Path:
    im = Image.open(src).convert("RGB")
    w, h = im.size; cw, ch = int(w / zoom), int(h / zoom)
    x = {"left": 0, "right": w - cw}.get(where, (w - cw) // 2)
    y = {"top": 0, "bottom": h - ch}.get(where, (h - ch) // 2)
    im.crop((x, y, x + cw, y + ch)).resize((w, h), Image.LANCZOS).save(out, quality=92)
    return out


def resolve_images(slides: list[dict], assets: Path, d: Path, kling_budget: int | None = None) -> list[str]:
    """Gắn `_img` (đường dẫn ảnh) + `_credit` cho từng slide. Trả về báo cáo.
    kling_budget: số ảnh Kling tối đa được dùng cho các slide (None = không giới hạn)."""
    d.mkdir(parents=True, exist_ok=True)
    report = []
    used_kling = 0
    for s in slides:
        sid = s["id"]
        if s.get("same_as"):
            continue                                     # xử lý ở vòng sau
        out = d / f"{sid}.jpg"
        side = d / f"{sid}.src.json"
        if out.exists() and side.exists():               # đã tải lần trước → dùng lại
            meta = json.loads(side.read_text(encoding="utf-8"))
            s["_img"], s["_credit"] = out, meta.get("credit", "")
            if meta.get("license") == "Kling AI":
                used_kling += 1
            report.append(f"{sid}: ✓ dùng lại {meta.get('src')}"); continue
        urls = [u for u in [s.get("image_url")] + list(s.get("candidates") or []) if u]
        cat = s.get("category")
        ok = False
        tries = [("url", u) for u in urls] + ([("cat", cat)] if cat else [])
        if s.get("prompt") and kling_budget is not None and used_kling >= kling_budget:
            report.append(f"{sid}: – bỏ Kling (đã dùng đủ hạn mức {kling_budget} ảnh của tập)")
        elif s.get("prompt"):
            kt = ("kling", s["prompt"])
            tries = tries + [kt] if s.get("prefer") == "commons" else [kt] + tries
        for kind, u in tries:
            try:
                if kind == "kling":
                    h = hashlib.sha1((u + "|" + (s.get("negative_prompt") or "") + kling.MODEL).encode()).hexdigest()[:8]
                    name = f"kling_{sid}_{h}.jpg"
                    cached = assets / name
                    if cached.exists():
                        vp.save_image(cached.read_bytes(), out)
                        src, lic = f"{name} (đã tạo trước)", "Kling AI"
                    else:
                        if not kling.available():
                            raise RuntimeError("chưa cấu hình KLING_API_KEY / KLING_ACCESS_KEY + KLING_SECRET_KEY")
                        vp.log(f"  ảnh {sid}: Kling đang tạo…")
                        raw = d / f"{sid}.kling.raw"
                        kling.generate(u, raw, negative=s.get("negative_prompt", ""), log=vp.log)
                        vp.save_image(raw.read_bytes(), out); raw.unlink()
                        new = d / name; new.write_bytes(out.read_bytes())
                        s["_kling_new"] = new
                        src, lic = f"Kling AI ({kling.MODEL})", "Kling AI"
                    credit = s.get("ai_credit", "Minh họa AI: Kling · Sách nói Monte Cristo")
                    s["_img"], s["_credit"] = out, credit
                    side.write_text(json.dumps({"src": src, "credit": credit, "license": lic}, ensure_ascii=False), encoding="utf-8")
                    report.append(f"{sid}: ✓ {src}"); ok = True; used_kling += 1
                    vp.log(f"  ảnh {sid} ✓ {src}")
                    break
                if kind == "cat":
                    name = _category_find(u["name"], u["prefix"])
                    if not name:
                        raise RuntimeError(f"không thấy '{u['prefix']}' trong Category:{u['name']}")
                else:
                    name = vp.commons_filename(u)
                if not name:                              # link ngoài Commons (bảo tàng…) → tải thẳng
                    vp.save_image(vp.polite_get(u).content, out)
                    credit, lic, src = s.get("source_credit", ""), s.get("license", ""), u
                    if not _free(lic):
                        raise RuntimeError(f"link ngoài Commons nhưng gói không ghi giấy phép tự do ({lic or 'trống'})")
                else:
                    info = vp.commons_info(name)
                    if not info:
                        raise RuntimeError("không có file này trên Commons")
                    if not _free(info["license"]):
                        raise RuntimeError(f"giấy phép không dùng được: {info['license'] or 'không rõ'}")
                    if info.get("width") and info["width"] < 900:
                        raise RuntimeError(f"ảnh quá nhỏ ({info['width']} px)")
                    size = vp.save_image(vp.polite_get(info["url"]).content, out)
                    credit = f"{info['credit']} · {info['license']}"[:120]
                    lic, src = info["license"], name
                s["_img"], s["_credit"] = out, credit
                side.write_text(json.dumps({"src": src, "credit": credit, "license": lic}, ensure_ascii=False),
                                encoding="utf-8")
                report.append(f"{sid}: ✓ {src} ({lic})"); ok = True
                vp.log(f"  ảnh {sid} ✓ {src}")
                break
            except Exception as e:
                lab = u if kind == "url" else ("Kling" if kind == "kling" else u.get("prefix"))
                report.append(f"{sid}: ✗ {lab} — {str(e)[:160]}")
                vp.log(f"  ảnh {sid}: bỏ qua ({str(e)[:100]})")
                if out.exists():
                    out.unlink()
        if not ok:
            img = s.get("image")
            if img and (assets / img).exists():
                s["_img"], s["_credit"] = assets / img, s.get("credit", "")
                report.append(f"{sid}: ↻ dùng tranh minh họa {img}")
            else:
                s["_img"], s["_credit"] = None, ""
                report.append(f"{sid}: ✗ THIẾU ẢNH — dùng poster của phần")
    byid = {s["id"]: s for s in slides}
    for s in slides:                                     # slide dùng lại ảnh của slide khác (cắt cận)
        if not s.get("same_as"):
            continue
        sid, src = s["id"], byid.get(s["same_as"], {})
        if src.get("_img"):
            s["_img"] = _crop(Path(src["_img"]), d / f"{sid}.jpg", s.get("crop", "center"))
            s["_credit"] = src.get("_credit", "")
            report.append(f"{sid}: ✓ cắt cận ({s.get('crop', 'center')}) từ ảnh slide {s['same_as']}")
        else:
            img = s.get("image")
            ok = bool(img and (assets / img).exists())
            s["_img"], s["_credit"] = (assets / img, s.get("credit", "")) if ok else (None, "")
            report.append(f"{sid}: {'↻ dùng tranh ' + img if ok else '✗ THIẾU ẢNH'} (slide {s['same_as']} không có ảnh)")
    report.append(f"Kling: dùng {used_kling} ảnh cho slide" + (f" / hạn mức {kling_budget}" if kling_budget is not None else ""))
    return report


# ----------------------------------------------------------------------------- 2. slide (2 lớp)
def _font(assets: Path, pkg: dict, key: str, size: int, text: str, bold=True):
    name = (pkg.get("fonts") or {}).get(key)
    if name and (assets / name).exists():
        try:
            return ImageFont.truetype(str(assets / name), size)
        except Exception:
            pass
    return vp.font(size, bold=bold, text=text)


def _wrap(dr, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if dr.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_layers(v: dict, assets: Path, pkg: dict, d: Path) -> tuple[Path, Path]:
    """Nền (ảnh, sẽ chuyển động) + lớp chữ (tiêu đề tiếng Việt, nhãn chương, credit)."""
    key = v["key"]
    bg_out, txt_out = d / f"{key}_bg.png", d / f"{key}_txt.png"
    sig = json.dumps([str(v["img"]), v.get("title"), v.get("label"), v.get("credit")], ensure_ascii=False)
    sigf = d / f"{key}.sig"
    if bg_out.exists() and txt_out.exists() and sigf.exists() and sigf.read_text(encoding="utf-8") == sig:
        return bg_out, txt_out
    img = Image.open(v["img"]).convert("RGB") if v["img"] and Path(v["img"]).exists() else Image.new("RGB", (W, H), (10, 14, 24))
    BW, BH = int(W * 1.5), int(H * 1.5)                   # nền lớn hơn khung → chuyển động mượt, không rung
    r = img.width / img.height
    if abs(r - W / H) / (W / H) < 0.18:                    # ảnh gần 16:9 → phủ kín khung
        bg = ImageOps.fit(img, (BW, BH), Image.LANCZOS)
    else:                                                  # ảnh dọc/vuông → nền mờ + ảnh giữa
        bg = ImageOps.fit(img, (BW, BH)).filter(ImageFilter.GaussianBlur(48))
        bg = Image.blend(bg, Image.new("RGB", (BW, BH), (0, 0, 0)), 0.5)
        fg = img.copy(); fg.thumbnail((int(BW * 0.9), int(BH * 0.86)), Image.LANCZOS)
        if fg.height < BH * 0.6:
            k = BH * 0.8 / fg.height; fg = fg.resize((int(fg.width * k), int(fg.height * k)), Image.LANCZOS)
            if fg.width > BW * 0.92:
                fg = ImageOps.fit(fg, (int(BW * 0.92), fg.height))
        sh = Image.new("RGBA", (fg.width + 80, fg.height + 80), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle([40, 40, fg.width + 40, fg.height + 40], fill=(0, 0, 0, 170))
        sh = sh.filter(ImageFilter.GaussianBlur(24))
        ox, oy = (BW - fg.width) // 2, (BH - fg.height) // 2
        bg.paste(sh, (ox - 40, oy - 30), sh); bg.paste(fg, (ox, oy))
    # màu điện ảnh: hơi ấm vùng sáng, lạnh vùng tối + vignette nhẹ
    bg = ImageOps.autocontrast(bg, cutoff=0.5)
    vig = Image.new("L", (BW, BH), 0); dv = ImageDraw.Draw(vig)
    for i in range(60):
        a = int(255 * (i / 60) ** 2)
        dv.ellipse([-BW * 0.25 + i * BW * 0.0042, -BH * 0.35 + i * BH * 0.0058,
                    BW * 1.25 - i * BW * 0.0042, BH * 1.35 - i * BH * 0.0058], fill=a)
    vig = vig.filter(ImageFilter.GaussianBlur(80))
    bg = Image.composite(bg, Image.blend(bg, Image.new("RGB", (BW, BH), (4, 6, 12)), 0.55), vig)
    bg.save(bg_out)

    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0)); dr = ImageDraw.Draw(txt)
    grad = Image.new("L", (1, 300)); [grad.putpixel((0, y), int(210 * (y / 299) ** 1.4)) for y in range(300)]
    txt.paste(Image.new("RGBA", (W, 300), (0, 0, 0, 255)), (0, H - 300), grad.resize((W, 300)))
    gtop = Image.new("L", (1, 140)); [gtop.putpixel((0, y), int(150 * (1 - y / 139))) for y in range(140)]
    txt.paste(Image.new("RGBA", (W, 140), (0, 0, 0, 255)), (0, 0), gtop.resize((W, 140)))
    if v.get("label"):
        f = _font(assets, pkg, "label", 30, v["label"])
        dr.text((84, 52), v["label"].upper(), font=f, fill=GOLD + (235,))
    if v.get("title"):
        f = _font(assets, pkg, "title", 60, v["title"])
        lines = _wrap(dr, v["title"], f, W - 520)[:2]
        step = int(f.size * 1.22); y = H - 96 - step * len(lines)
        dr.rectangle([70, y + 8, 78, y + step * len(lines) - 4], fill=GOLD + (255,))
        for ln in lines:
            dr.text((104, y), ln, font=f, fill=CREAM + (255,)); y += step
    if v.get("credit"):
        c = " ".join(str(v["credit"]).split())[:110]
        f2 = vp.font(20, bold=False, text=c)
        dr.text((W - 60 - dr.textlength(c, font=f2), 52), c, font=f2, fill=(255, 255, 255, 140))  # góc trên phải
    txt.save(txt_out)
    sigf.write_text(sig, encoding="utf-8")
    return bg_out, txt_out


# ----------------------------------------------------------------------------- 3. vòng chuyển động
def loop_expr(kind: str, n: int, amp: float = 0.10):
    """Chuyển động khép kín: đi rồi quay về đúng điểm đầu (cos) → lặp lại không bị giật."""
    p = f"(0.5-0.5*cos(2*PI*on/{n}))"
    base = 1 + amp
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == "zoom_in":   return f"1.02+{amp:.3f}*{p}", cx, cy
    if kind == "zoom_out":  return f"{base + 0.02:.3f}-{amp:.3f}*{p}", cx, cy
    if kind == "pan_right": return f"{base:.3f}", f"(iw-iw/zoom)*(0.15+0.7*{p})", cy
    if kind == "pan_left":  return f"{base:.3f}", f"(iw-iw/zoom)*(0.85-0.7*{p})", cy
    if kind == "tilt_down": return f"{base:.3f}", cx, f"(ih-ih/zoom)*(0.15+0.7*{p})"
    if kind == "tilt_up":   return f"{base:.3f}", cx, f"(ih-ih/zoom)*(0.85-0.7*{p})"
    if kind == "diag":      return (f"1.04+{amp * 0.8:.3f}*{p}", f"(iw-iw/zoom)*(0.3+0.4*{p})", f"(ih-ih/zoom)*(0.3+0.4*{p})")
    return loop_expr("zoom_in", n, amp)


def make_loop(bg: Path, txt: Path, out: Path, motion: str, sec: float) -> Path:
    tag = out.with_suffix(".tag")
    want = f"{motion}|{sec:.1f}"
    if out.exists() and tag.exists() and tag.read_text() == want and out.stat().st_mtime > max(bg.stat().st_mtime, txt.stat().st_mtime):
        return out
    n = int(round(sec * FPS))
    z, x, y = loop_expr(motion, n)
    fc = (f"[0:v]zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS}[kb];"
          f"[1:v]format=rgba[t];[kb][t]overlay=0:0,format=yuv420p[v]")
    vp.run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(bg), "-loop", "1", "-i", str(txt),
            "-filter_complex", fc, "-map", "[v]", "-frames:v", str(n), "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), "-g", str(FPS * 2), str(out)])
    tag.write_text(want)
    return out


# ----------------------------------------------------------------------------- 4. mốc thời gian
def _find(text: str, anchor: str) -> int:
    """Vị trí ký tự của anchor trong text (bỏ qua khác biệt khoảng trắng/dấu ngoặc); -1 nếu không thấy."""
    def norm(s):
        return re.sub(r"[\s“”\"'‘’]+", " ", s).strip().lower()
    t, a = norm(text), norm(anchor)
    for L in (len(a), 40, 25):
        k = t.find(a[:L])
        if k >= 0:
            return k
    return -1


def part_slide_times(part: dict, files: list[Path], start: float, end: float) -> list[tuple[float, dict]]:
    """Thời điểm bắt đầu (giây, tuyệt đối) của từng slide trong một phần."""
    slides = part.get("slides") or []
    if not slides:
        return []
    texts = part.get("_texts") or []
    durs = [vp.duration(f) for f in files]
    # bảng (char_start, char_len, t_start, t_dur) theo từng đoạn audio
    rows, c, t = [], 0, start
    for tx, du in zip(texts, durs):
        n = len(re.sub(r"[\s“”\"'‘’]+", " ", tx).strip())
        rows.append((c, n, t, du)); c += n + 1; t += du
    full = " ".join(texts)
    total_c = max(c, 1)
    out = []
    for i, s in enumerate(slides):
        ts = None
        if i == 0 and not s.get("anchor") and s.get("at") is None:
            ts = start
        elif s.get("anchor"):
            k = _find(full, s["anchor"])
            if k >= 0:
                for cs, cl, t0, du in rows:
                    if cs <= k < cs + cl + 1:
                        ts = t0 + du * (k - cs) / max(cl, 1); break
            else:
                vp.log(f"  ⚠ slide {s['id']}: không tìm thấy anchor → chia đều")
        if ts is None and s.get("at") is not None:
            ts = start + (end - start) * float(s["at"])
        out.append([ts, s])
    # slide không có mốc → chia đều giữa hai mốc kề
    known = [i for i, (ts, _) in enumerate(out) if ts is not None]
    for i, (ts, s) in enumerate(out):
        if ts is None:
            prev = max([k for k in known if k < i], default=None)
            nxt = min([k for k in known if k > i], default=None)
            a = out[prev][0] if prev is not None else start
            b = out[nxt][0] if nxt is not None else end
            ia = prev if prev is not None else -1
            ib = nxt if nxt is not None else len(out)
            out[i][0] = a + (b - a) * (i - ia) / (ib - ia)
    out[0][0] = start                                       # slide đầu luôn mở phần
    out.sort(key=lambda x: x[0])
    return [(ts, s) for ts, s in out]


# ----------------------------------------------------------------------------- 5. dựng video
def build_video(pkg: dict, parts_tl: list[dict], assets: Path, work: Path, mixed_audio: Path, out_video: Path,
                D: float) -> list[str]:
    """parts_tl: [{part, start, end, files}] (end gồm cả khoảng nghỉ sau phần). Trả về báo cáo ảnh."""
    sd = work / "slides"; sd.mkdir(parents=True, exist_ok=True)
    all_slides = [s for p in pkg["parts"] for s in (p.get("slides") or [])]
    seen = set()
    for s in all_slides:
        if s["id"] in seen:
            raise ValueError(f"trùng id slide: {s['id']}")
        seen.add(s["id"])
    total = kling.budget(D / 60, pkg.get("kling_max"))
    slide_budget = total - (1 if (pkg.get("thumbnail_kling") or {}).get("prompt") else 0)
    pkg["_kling_total"] = total
    vp.log(f"4a/5 Tải {len(all_slides)} ảnh slide (Kling tối đa {slide_budget} ảnh slide, tổng {total} ảnh/tập)…")
    report = resolve_images(all_slides, assets, work / "images", slide_budget)
    pkg["_kling_new"] = [s["_kling_new"] for s in all_slides if s.get("_kling_new")]

    # dòng thời gian hình: (t, ảnh, tiêu đề, nhãn, credit, motion)
    vis = []
    for pt in parts_tl:
        part, st, en = pt["part"], pt["start"], pt["end"]
        label = part.get("screen_label") or part.get("label") or ""
        poster = assets / (part.get("poster") or pkg["images"]["poster_intro"])
        if part.get("slides"):
            for ts, s in part_slide_times(part, pt["files"], st, pt["speech_end"]):
                img = s.get("_img") or poster
                vis.append(dict(t=ts, img=img, title=s.get("title", ""), label=label,
                                credit=s.get("_credit", ""), motion=s.get("motion"), id=s["id"]))
        else:
            vis.append(dict(t=st, img=poster, title="", label="", credit="", motion=part.get("motion"),
                            id=f"p_{part['id']}"))
    vis.sort(key=lambda v: v["t"])
    # gộp slide quá ngắn
    merged = []
    for v in vis:
        if merged and v["t"] - merged[-1]["t"] < MIN_SLIDE:
            prev = merged[-1]
            if prev["id"].startswith("p_") and not v["id"].startswith("p_"):
                v = dict(v, t=prev["t"]); merged[-1] = v       # poster ngắn (hook…) nhường chỗ cho slide thật
                report.append(f"{prev['id']}: thay bằng {v['id']} (phần quá ngắn)")
                continue
            vp.log(f"  slide {v['id']} cách slide trước < {MIN_SLIDE:.0f}s → bỏ qua")
            report.append(f"{v['id']}: bỏ (quá gần slide trước)")
            continue
        merged.append(v)
    vis = merged
    for i, v in enumerate(vis):
        v["end"] = vis[i + 1]["t"] if i + 1 < len(vis) else D
        v["key"] = f"{i:03d}_{v['id']}"

    # hiệu ứng: ngẫu nhiên nhưng cố định theo slug
    rnd = random.Random(pkg.get("slug", "sachnoi") + "-slides")
    pool = vp.available_transitions()
    prev = None
    for v in vis:
        if v.get("motion") not in MOTIONS:
            v["motion"] = rnd.choice([m for m in MOTIONS if m != prev])
        prev = v["motion"]
    trans = []
    for i in range(len(vis) - 1):
        trans.append(rnd.choice([t for t in pool if not trans or t != trans[-1]] or pool))

    vp.log(f"4b/5 Dựng {len(vis)} slide (vòng chuyển động {LOOP_SEC}s)…")
    for v in vis:
        bg, tx = render_layers(v, assets, pkg, sd)
        sec = min(LOOP_SEC, max(8.0, v["end"] - v["t"] + XF + 1))
        v["clip"] = make_loop(bg, tx, sd / f"{v['key']}.mp4", v["motion"], sec)

    vp.log("4c/5 Ghép slide + chuyển cảnh + âm thanh…")
    inputs, fc = [], []
    for i, v in enumerate(vis):
        ln = (v["end"] - v["t"]) + (XF if i + 1 < len(vis) else 0)
        inputs += ["-stream_loop", "-1", "-t", f"{ln:.3f}", "-i", str(v["clip"])]
        fc.append(f"[{i}:v]fps={FPS},settb=AVTB,setpts=PTS-STARTPTS[s{i}]")
    cur = "[s0]"
    for i in range(1, len(vis)):
        o = f"[x{i}]"
        fc.append(f"{cur}[s{i}]xfade=transition={trans[i - 1]}:duration={XF}:offset={vis[i]['t']:.3f}{o}")
        cur = o
    fc.append(f"{cur}fade=t=in:st=0:d=1.0,fade=t=out:st={max(D - 2.5, 0):.2f}:d=2.5,format=yuv420p[vout]")
    script = work / "slideshow.filter.txt"
    script.write_text(";\n".join(fc), encoding="utf-8")
    na = len(vis)
    vp.run(["ffmpeg", "-y", *inputs, "-i", str(mixed_audio), "-filter_complex_script", str(script),
            "-map", "[vout]", "-map", f"{na}:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-r", str(FPS), "-g", str(FPS * 4), "-c:a", "copy", "-t", f"{D:.3f}", "-movflags", "+faststart",
            str(out_video)])
    plan = [f"{vp.fmt_ts(v['t'])}  {v['id']:<8} {v['motion']:<9} {v.get('title') or ''} [{Path(str(v['img'])).name}]" for v in vis]
    (work / "slide_plan.txt").write_text("\n".join(plan), encoding="utf-8")
    pkg["_slide_imgs"] = {s["id"]: s.get("_img") for s in all_slides}
    pkg["_kling_new"] = [s["_kling_new"] for s in all_slides if s.get("_kling_new")]
    return report + ["", "KẾ HOẠCH SLIDE:"] + plan
