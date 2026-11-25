"""
video_pipeline.py — Biến 1 file production.json (do Claude viết) thành video hoàn chỉnh.

Các bước:  tải ảnh → làm 20 slide → Vbee đọc voice-over → ghép video (Ken Burns + nhạc nền)
           → thumbnail → description/hashtag/chapters → lưu toàn bộ vào thư mục output (Google Drive).

Chạy được trên Google Colab (khuyên dùng) hoặc máy tính có Python 3.10+ và ffmpeg.
Chạy lại nhiều lần an toàn: bước nào đã có file kết quả thì bỏ qua (không tốn tiền Vbee lần 2).
"""
from __future__ import annotations

import json, os, re, shutil, subprocess, time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1920, 1080, 25
# Wikimedia yêu cầu User-Agent mô tả rõ công cụ + cách liên hệ. Có thể ghi email vào CFG['CONTACT'].
UA = "BiographyVideoFactory/1.1 (personal educational video project; python-requests)"
VBEE_API = "https://api.vbee.vn/v1/tts"

# ----------------------------------------------------------------------------- tiện ích
def log(msg): print(time.strftime("%H:%M:%S"), msg, flush=True)

def run(cmd: list[str]):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg lỗi:\n" + r.stderr[-2000:])
    return r

def duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip())

# ----------------------------------------------------------------------------- ngôn ngữ
# Mỗi ngôn ngữ ra một thư mục con trong output/<tên-nhân-vật>/  (ảnh dùng chung: output/<tên>/images)
LANGS = {
    "vi": dict(folder="Viet",      rtl=False, cjk=False),
    "en": dict(folder="Anh",       rtl=False, cjk=False),
    "fr": dict(folder="Phap",      rtl=False, cjk=False),
    "es": dict(folder="TayBanNha", rtl=False, cjk=False),
    "ar": dict(folder="ARap",      rtl=True,  cjk=False),
    "zh": dict(folder="Trung",     rtl=False, cjk=True),     # chữ Phồn thể (zh-Hant)
}
LABELS = {
    "vi": dict(chap="⏱️ MỤC LỤC", src="📚 NGUỒN THAM KHẢO", img="🖼️ HÌNH ẢNH (ghi công theo giấy phép)",
               slide="Slide", watch="▶ Xem video đầy đủ:", src_full="NGUỒN THAM KHẢO", img_full="HÌNH ẢNH"),
    "en": dict(chap="⏱️ CHAPTERS", src="📚 SOURCES", img="🖼️ IMAGE CREDITS (per license)",
               slide="Slide", watch="▶ Watch the full video:", src_full="SOURCES", img_full="IMAGES"),
    "fr": dict(chap="⏱️ CHAPITRES", src="📚 SOURCES", img="🖼️ CRÉDITS DES IMAGES (selon licence)",
               slide="Diapo", watch="▶ Regardez la vidéo complète :", src_full="SOURCES", img_full="IMAGES"),
    "es": dict(chap="⏱️ CAPÍTULOS", src="📚 FUENTES", img="🖼️ CRÉDITOS DE LAS IMÁGENES (según licencia)",
               slide="Diapositiva", watch="▶ Mira el video completo:", src_full="FUENTES", img_full="IMÁGENES"),
    "ar": dict(chap="⏱️ الفصول", src="📚 المصادر", img="🖼️ حقوق الصور (حسب الترخيص)",
               slide="الشريحة", watch="▶ شاهد الفيديو الكامل:", src_full="المصادر", img_full="الصور"),
    "zh": dict(chap="⏱️ 章節", src="📚 參考資料", img="🖼️ 圖片來源（依授權標示）",
               slide="圖", watch="▶ 觀看完整影片：", src_full="參考資料", img_full="圖片"),
}
CUR = {"lang": "vi"}                                   # ngôn ngữ của gói đang dựng

def norm_lang(code: str | None) -> str:
    c = (code or "vi").lower().replace("_", "-").split("-")[0]
    if c not in LANGS:
        raise SystemExit(f"❌ Ngôn ngữ '{code}' chưa hỗ trợ. Dùng một trong: {', '.join(LANGS)}")
    return c

def lang_folder(pkg: dict) -> str:
    return LANGS[norm_lang(pkg.get("lang"))]["folder"]

def L(key: str) -> str:
    return LABELS[CUR["lang"]][key]

# ----------------------------------------------------------------------------- font
FONT_DIR = Path.home() / ".cache" / "fonts"
DEJAVU = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
FONT_URLS = {
    "BeVietnamPro-ExtraBold.ttf": "https://github.com/google/fonts/raw/main/ofl/bevietnampro/BeVietnamPro-ExtraBold.ttf",
    "BeVietnamPro-Medium.ttf":    "https://github.com/google/fonts/raw/main/ofl/bevietnampro/BeVietnamPro-Medium.ttf",
    "NotoSansArabic-Bold.ttf":    "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansArabic/hinted/ttf/NotoSansArabic-Bold.ttf",
    "NotoSansArabic-Medium.ttf":  "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansArabic/hinted/ttf/NotoSansArabic-Medium.ttf",
}

def _fetch(name: str) -> str | None:
    f = FONT_DIR / name
    if not f.exists() and name in FONT_URLS:
        try:
            FONT_DIR.mkdir(parents=True, exist_ok=True)
            r = requests.get(FONT_URLS[name], timeout=30); r.raise_for_status()
            if r.content[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                f.write_bytes(r.content)
        except Exception:
            pass
    return str(f) if f.exists() else None

def _candidates(bold: bool) -> list[tuple[str, int | None]]:
    """Danh sách font theo ngôn ngữ (font đẹp trước, DejaVu cuối cùng vì có cả chữ Latin, Việt, Ả Rập)."""
    lang, c = CUR["lang"], []
    if lang == "ar":
        c += [(_fetch("NotoSansArabic-Bold.ttf" if bold else "NotoSansArabic-Medium.ttf"), None)]
        c += [(p, None) for p in (["/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
                                   "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf"] if bold else
                                  ["/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"])]
    elif lang == "zh":
        names = (["Bold", "Black", "Medium"] if bold else ["Medium", "Regular"])
        for n in names:
            for d in ["/usr/share/fonts/opentype/noto", "/usr/share/fonts/noto-cjk"]:
                c.append((f"{d}/NotoSansCJK-{n}.ttc", "TC"))
        c += [("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", None)]
    else:
        c += [(_fetch("BeVietnamPro-ExtraBold.ttf" if bold else "BeVietnamPro-Medium.ttf"), None)]
    c += [(DEJAVU[0] if bold else DEJAVU[1], None)]
    return [(p, tag) for p, tag in c if p and Path(p).exists()]

_cmap_cache: dict = {}
def _covers(path: str, index: int, text: str) -> bool:
    """Font có đủ mọi ký tự của câu chữ không (tránh hiện ô vuông)."""
    try:
        from fontTools.ttLib import TTFont, TTCollection
    except Exception:
        return True                                    # không có fontTools → tin vào thứ tự ưu tiên
    key = (path, index)
    if key not in _cmap_cache:
        try:
            tt = TTCollection(path).fonts[index] if path.endswith(".ttc") else TTFont(path, lazy=True)
            _cmap_cache[key] = set(tt.getBestCmap() or {})
        except Exception:
            _cmap_cache[key] = None
    cmap = _cmap_cache[key]
    return cmap is None or all(ord(ch) in cmap for ch in set(text) if not ch.isspace())

def _ttc_index(path: str, tag: str | None) -> int:
    if not tag:
        return 0
    for i in range(12):
        try:
            if tag in ImageFont.truetype(path, 10, index=i).getname()[0]:
                return i
        except Exception:
            break
    return 0

def font(size: int, bold=True, text: str = "") -> ImageFont.FreeTypeFont:
    """Font đúng ngôn ngữ đang dựng; nếu có `text` thì chọn font có đủ mọi ký tự của câu đó."""
    for path, tag in _candidates(bold):
        idx = _ttc_index(path, tag)
        if not text or _covers(path, idx, text):
            return ImageFont.truetype(path, size, index=idx)
    return ImageFont.load_default(size)

# ----------------------------------------------------------------------------- chữ: phải→trái, chữ Hán
try:
    from PIL import features as _pf
    RAQM = bool(_pf.check("raqm"))                     # Pillow tự nối chữ Ả Rập + đảo chiều
except Exception:
    RAQM = False

def vis(text: str) -> str:
    """Chuỗi để VẼ: tiếng Ả Rập khi Pillow thiếu raqm thì nối chữ + đảo chiều bằng arabic_reshaper/bidi."""
    if not LANGS[CUR["lang"]]["rtl"] or RAQM:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text

def tlen(draw, text: str, f) -> float:
    return draw.textlength(vis(text), font=f)

def dtext(draw, xy, text: str, f, **kw):
    draw.text(xy, vis(text), font=f, **kw)

CJK_TAIL = "，。！？、：；」』）》,.!?:;)…"
def tokens(text: str) -> tuple[list[str], str]:
    """Tách câu thành các 'từ' để xuống dòng. Chữ Hán: từng chữ (dấu câu dính vào chữ trước)."""
    if LANGS[CUR["lang"]]["cjk"]:
        toks = re.findall(rf"[A-Za-z0-9'’\-.]+[{CJK_TAIL}]*|\S[{CJK_TAIL}]*", text)
        return toks, ""
    return text.split(), " "

def upper(text: str) -> str:
    return text.upper() if CUR["lang"] in ("vi", "en", "fr", "es") else text

def fmt_ts(sec: float) -> str:
    sec = int(sec); h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _x(s: dict, key: str) -> str:
    """Đọc trường theo ngôn ngữ: 'narration' / 'caption' / 'subtitle'; gói tiếng Việt cũ dùng *_vi / *_en."""
    if key == "narration":
        return s.get("narration") or s.get("narration_vi", "")
    if key == "caption":
        return (s.get("caption") or s.get("caption_en", "")).strip()
    return ""

# ----------------------------------------------------------------------------- 1. ảnh
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_last_req = [0.0]

def polite_get(url: str, params: dict | None = None, tries: int = 5) -> requests.Response:
    """GET có giãn cách (≥1,2 s/lượt) và tự chờ rồi thử lại khi bị 429/5xx."""
    for i in range(tries):
        wait = 1.2 - (time.time() - _last_req[0])
        if wait > 0:
            time.sleep(wait)
        _last_req[0] = time.time()
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            delay = int(r.headers.get("Retry-After", 0) or 0) or [5, 15, 30, 60, 90][i]
            log(f"    máy chủ bận ({r.status_code}) — chờ {delay}s rồi thử lại")
            time.sleep(delay); continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"vẫn bị từ chối sau {tries} lần thử")

def commons_filename(url: str) -> str | None:
    """Lấy tên file Commons từ link upload.wikimedia.org hoặc link trang File:."""
    from urllib.parse import unquote, urlparse
    u = urlparse(url)
    if "upload.wikimedia.org" in u.netloc:
        parts = u.path.split("/")
        name = parts[-2] if "/thumb/" in u.path else parts[-1]
        return unquote(name)
    if "wikimedia.org" in u.netloc or "wikipedia.org" in u.netloc:
        m = re.search(r"(?:File|Tập_tin|Tập tin):(.+)$", unquote(u.path))
        return m.group(1) if m else None
    return None

def commons_info(title: str) -> dict | None:
    """Hỏi API Commons: link ảnh cỡ chuẩn 1920 px + tác giả + giấy phép."""
    r = polite_get(COMMONS_API, {"action": "query", "format": "json", "titles": f"File:{title}",
                                 "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1920})
    for p in r.json().get("query", {}).get("pages", {}).values():
        ii = (p.get("imageinfo") or [None])[0]
        if ii:
            meta = ii.get("extmetadata", {})
           artist = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", meta.get("Artist", {}).get("value", ""))).strip()
            return {"url": ii.get("thumburl") or ii["url"], "width": ii.get("width", 0),
                    "license": meta.get("LicenseShortName", {}).get("value", ""),
                    "credit": f"Wikimedia Commons / {artist}"[:110] if artist else "Wikimedia Commons",
                    "page": ii.get("descriptionurl", "")}
    return None

def commons_search(query: str, used: set, limit=10) -> list[str]:
    r = polite_get(COMMONS_API, {"action": "query", "format": "json", "list": "search", "srnamespace": 6,
                                 "srsearch": f"{query} filetype:bitmap", "srlimit": limit})
    return [h["title"].split(":", 1)[1] for h in r.json().get("query", {}).get("search", [])
            if h["title"].split(":", 1)[1] not in used]

STOP = {"portrait", "with", "from", "engraving", "page", "title", "first", "edition", "after", "their",
        "painting", "drawing", "own", "the", "and", "his", "her", "of", "by", "in", "c", "ca"}
def keywords(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-zÀ-ÿ']{4,}", text) if w.lower() not in STOP]

FREE_LICENSES = ("public domain", "pd", "cc0", "cc by", "cc-by", "no restrictions")

def save_image(content: bytes, out: Path) -> tuple[int, int]:
    tmp = out.with_suffix(".tmp"); tmp.write_bytes(content)
    img = ImageOps.exif_transpose(Image.open(tmp)).convert("RGB")
    img.thumbnail((3840, 3840)); img.save(out, quality=92); tmp.unlink()
    return img.size

def download_images(pkg: dict, d: Path) -> list[str]:
    """Tải ảnh cho từng slide. Thứ tự thử: link chính → link dự phòng → tự tìm ảnh thay thế trên Commons.
    Ảnh đã có sẵn (kể cả ảnh bạn tự bỏ vào thư mục images trên Drive) thì giữ nguyên."""
    d.mkdir(parents=True, exist_ok=True)
    report, used = [], set()
    for s in pkg["slides"]:
        n = commons_filename(s.get("image_url", "") or "")
        if n: used.add(n)
    for s in pkg["slides"]:
        sid, out = s["id"], d / f"{s['id']:02d}.jpg"
        side = d / f"{s['id']:02d}.src.txt"            # nguồn của ảnh do pipeline tự tải
        if out.exists():
            if not side.exists():
                report.append(f"Slide {sid:02d}: ✓ dùng ảnh bạn tự bỏ vào"); continue
            if side.read_text(encoding="utf-8") == (s.get("image_url") or ""):
                report.append(f"Slide {sid:02d}: ✓ dùng ảnh đã tải lần trước"); continue
            out.unlink()                                 # link ảnh trong JSON đã đổi → tải lại
        ok = False
        for url in [u for u in [s.get("image_url")] + s.get("backup_image_urls", []) if u]:
            try:
                name = commons_filename(url)
                info = None
                if name:
                    info = commons_info(name)
                    if not info:
                        raise RuntimeError("không có file này trên Commons")
                    url = info["url"]
                size = save_image(polite_get(url).content, out)
                if info and info["license"]:
                    s.update(image_credit=info["credit"], license=info["license"])
                side.write_text(s.get("image_url") or "", encoding="utf-8")
                log(f"  ảnh {sid:02d} ✓ {size}"); report.append(f"Slide {sid:02d}: ✓ {name or url}"); ok = True
                break
            except Exception as e:
                log(f"  ảnh {sid:02d}: link lỗi ({str(e)[:90]}) — thử link khác")
        if not ok:                                   # tự tìm ảnh thay thế trên Commons
            figure = pkg.get("figure", "")
            kw = keywords(s.get("caption_en") or _x(s, "caption"))
            surname = (figure.split() or [""])[-1].lower()
            tries = [(" ".join(kw[:6]), 2), (f"{figure} {' '.join(kw[:3])}", 2), (figure, 0)]
            try:
                for q, need in tries:
                    for name in commons_search(q, used):
                        low = name.lower()
                        if need and sum(k.lower() in low for k in kw) < need:
                            continue                      # tên file không khớp nội dung caption
                        if not need and surname and surname not in low:
                            continue
                        info = commons_info(name)
                        if not info or not any(k in info["license"].lower() for k in FREE_LICENSES):
                            continue
                        size = save_image(polite_get(info["url"]).content, out)
                        used.add(name)
                        new_cap = re.sub(r"\s+", " ", re.sub(r"\.(jpe?g|png|tiff?)$|_|\b(Wellcome|RMG)\s+[A-Z]*\d+\w*", " ", name, flags=re.I)).strip(" .-")
                        s.update(image_url=info["page"] or info["url"], image_credit=info["credit"],
                                 license=info["license"], caption_en=new_cap[:90])
                        if s.get("caption"):
                            s["caption"] = new_cap[:90]
                        side.write_text(s["image_url"], encoding="utf-8")
                        log(f"  ảnh {sid:02d} ↻ ảnh THAY THẾ tự động: {name} {size}")
                        report.append(f"Slide {sid:02d}: ↻ THAY THẾ tự động – {name} ({info['license']}) – caption đổi thành ảnh mới; KIỂM TRA có khớp lời đọc không")
                        ok = True; break
                    if ok: break
            except Exception as e:
                log(f"  ảnh {sid:02d}: tìm ảnh thay thế lỗi ({str(e)[:90]})")
        if not ok:
            log(f"  ⚠ slide {sid:02d}: KHÔNG có ảnh — dùng nền tối")
            report.append(f"Slide {sid:02d}: ✗ THIẾU ẢNH – bỏ file {sid:02d}.jpg vào thư mục images trên Drive rồi chạy lại")
    (d.parent / "image_report.txt").write_text("\n".join(report), encoding="utf-8")
    return report

# ----------------------------------------------------------------------------- 2. slide
def detect_face(img: Image.Image):
    """Tìm khuôn mặt lớn nhất (chân dung, tranh vẽ). Trả về (tâm x, tâm y, cỡ) theo pixel, hoặc None."""
    try:
        import cv2, numpy as np
    except Exception:
        return None
    g = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    g = cv2.equalizeHist(g)
    try:
        casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except Exception:
        return None
    if casc.empty():
        return None
    m = max(40, int(min(img.size) * 0.08))
    faces = casc.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(m, m))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    if w < min(img.size) * 0.10:                       # mặt quá nhỏ (ảnh đám đông) → bỏ
        return None
    return (x + w / 2, y + h / 2, h)

def render_slide_layers(s: dict, img_path: Path, d: Path):
    """Tạo 2 lớp: ảnh nền (sẽ chuyển động Ken Burns) và lớp chữ trong suốt (đứng yên)."""
    d.mkdir(parents=True, exist_ok=True)
    bg_out, txt_out = d / f"{s['id']:02d}_bg.png", d / f"{s['id']:02d}_txt.png"
    fresh = (bg_out.exists() and txt_out.exists() and img_path.exists()
             and bg_out.stat().st_mtime > img_path.stat().st_mtime
             and (d / f"{s['id']:02d}_meta.json").exists()
             and json.loads((d / f"{s['id']:02d}_meta.json").read_text()).get("text") == [_x(s, "caption"), s.get("image_credit", ""), CUR["lang"]])
    if fresh:
        return bg_out, txt_out
    img = (Image.open(img_path).convert("RGB") if img_path.exists()
           else Image.new("RGB", (W, H), (18, 18, 22)))           # thiếu ảnh → nền tối
    # nền: chính ảnh đó phóng to + làm mờ + tối đi (ảnh dọc/ảnh nhỏ không bị viền đen)
    bg = ImageOps.fit(img, (W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
    fg = img.copy(); fg.thumbnail((W, H - 40), Image.LANCZOS)
    if fg.width < W * 0.6 and fg.height < H * 0.6:      # ảnh quá nhỏ → phóng lên vừa khung
        k = min(W * 0.8 / fg.width, (H - 40) / fg.height); fg = fg.resize((int(fg.width * k), int(fg.height * k)), Image.LANCZOS)
    ox, oy = (W - fg.width) // 2, (H - fg.height) // 2
    bg.paste(fg, (ox, oy))
    bg.save(bg_out)
    face = detect_face(fg) if img_path.exists() else None
    face_img = None
    if face:
        fx, fy, fs = face
        face_img = [fx / fg.width, fy / fg.height, fs / fg.height]   # theo ảnh gốc (dùng cho Shorts)
        face = [(ox + fx) / W, (oy + fy) / H, fs / H]                # theo khung 1920x1080
    (d / f"{s['id']:02d}_meta.json").write_text(json.dumps({"face": face, "face_img": face_img,
        "text": [_x(s, "caption"), s.get("image_credit", ""), CUR["lang"]]}), encoding="utf-8")

    # lớp chữ: dải chú thích (bản Việt: tiếng Anh; bản khác: đúng ngôn ngữ) + credit nhỏ
    # tiếng Ả Rập đọc phải→trái nên chú thích nằm góc dưới PHẢI, credit góc dưới trái
    rtl = LANGS[CUR["lang"]]["rtl"]
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0)); dr = ImageDraw.Draw(txt)
    grad = Image.new("L", (1, 260)); [grad.putpixel((0, y), int(200 * y / 259)) for y in range(260)]
    txt.paste(Image.new("RGBA", (W, 260), (0, 0, 0, 255)), (0, H - 260), grad.resize((W, 260)))
    cap = _x(s, "caption")
    if cap:
        f = font(46, text=cap); lines = _wrap(dr, cap, f, W - 260)[:2]
        step = int(f.size * 1.26); y = H - 70 - step * len(lines)
        bar = [W - 78, y + 4, W - 70, y + step * len(lines) - 6] if rtl else [70, y + 4, 78, y + step * len(lines) - 6]
        dr.rectangle(bar, fill=(232, 180, 60, 255))  # vạch vàng
        for ln in lines:
            x = W - 100 - tlen(dr, ln, f) if rtl else 100
            dtext(dr, (x, y), ln, f, fill=(255, 255, 255, 255)); y += step
    if s.get("image_credit"):
        c = " ".join(str(s["image_credit"]).split())[:110]
        lang0 = CUR["lang"]; CUR["lang"] = "en"           # credit luôn là chữ Latin
        f2 = font(20, bold=False, text=c); CUR["lang"] = lang0
        x = 40 if rtl else W - 40 - dr.textlength(c, font=f2)
        dr.text((x, H - 40), c, font=f2, fill=(255, 255, 255, 150))
    txt.save(txt_out)
    return bg_out, txt_out

# ----------------------------------------------------------------------------- 3. Vbee TTS
def vbee_tts(text: str, out: Path, cfg: dict):
    key = f"{cfg['VOICE_CODE']}|{cfg.get('SPEED', 1.0)}|{text}"
    side = out.with_suffix(".txt")                      # ghi lại lời đọc đã dùng để tạo audio này
    if out.exists() and out.stat().st_size > 1000 and side.exists() and side.read_text(encoding="utf-8") == key:
        return out
    hdr = {"Authorization": f"Bearer {cfg['VBEE_TOKEN']}", "App-Id": cfg["VBEE_APP_ID"],
           "Content-Type": "application/json"}
    body = {"text": text, "voiceCode": cfg["VOICE_CODE"], "mode": "async",
            "webhookUrl": cfg.get("VBEE_WEBHOOK", "https://example.com/vbee-callback"),
            "outputFormat": "mp3", "bitrate": 128, "speed": cfg.get("SPEED", 1.0),
            "clientPause": {"sentenceBreak": 0.5, "paragraphBreak": 0.8}}
    for attempt in range(3):
        try:
            r = requests.post(VBEE_API, headers=hdr, json=body, timeout=60); r.raise_for_status()
            rid = r.json()["requestId"]
            for _ in range(120):                        # tối đa ~10 phút / đoạn
                time.sleep(5)
                g = requests.get(f"{VBEE_API}/requests/{rid}", headers=hdr, timeout=60).json()
                st = g.get("status")
                if st == "COMPLETED":                   # link chỉ sống 3 phút → tải ngay
                    a = requests.get(g["audioLink"], timeout=120); a.raise_for_status()
                    out.write_bytes(a.content); side.write_text(key, encoding="utf-8"); return out
                if st == "FAILED":
                    raise RuntimeError(g.get("error"))
            raise TimeoutError("Vbee xử lý quá lâu")
        except Exception as e:
            log(f"  Vbee lỗi lần {attempt + 1}: {e}"); time.sleep(10)
    raise RuntimeError(f"Không tạo được audio cho {out.name}")

# ----------------------------------------------------------------------------- 4. ghép video
MOTIONS = ["zoom_in", "zoom_out", "pan_right", "pan_left", "tilt_down", "tilt_up", "face"]
# chuyển cảnh kiểu điện ảnh; số lần lặp = độ ưu tiên (mờ dần là kiểu phim tài liệu dùng nhiều nhất)
WANTED_TRANSITIONS = ["fade"] * 4 + ["fadeblack"] * 2 + ["smoothleft", "smoothright", "slideleft",
                      "slideright", "circleopen", "zoomin", "hblur", "wipeleft", "radial"]
XFADE = 0.8                                          # giây chuyển cảnh
HEAD, TAIL = 0.8, 0.8                                # giây nghỉ đầu/cuối mỗi slide (≥ XFADE: không chồng lời đọc)

def available_transitions() -> list[str]:
    try:
        h = run(["ffmpeg", "-hide_banner", "-h", "filter=xfade"]).stdout
        have = [t for t in WANTED_TRANSITIONS if re.search(rf"^\s+{t}\b", h, re.M)]   # bản ffmpeg cũ thiếu kiểu nào thì bỏ kiểu đó
        return have or ["fade"]
    except Exception:
        return ["fade"]

def plan_effects(pkg: dict, metas: list[dict]) -> tuple[list[str], list[str]]:
    """Chọn ngẫu nhiên (nhưng cố định theo từng video) chuyển động cho mỗi slide và chuyển cảnh giữa các slide."""
    import random
    rnd = random.Random(pkg.get("slug", "video"))
    trans_pool = available_transitions()
    motions, trans = [], []
    for i, m in enumerate(metas):
        if m.get("face") and (not motions or motions[-1] != "face") and rnd.random() < 0.75:
            motions.append("face"); continue          # có mặt người → 75% zoom chậm vào khuôn mặt
        pool = [x for x in MOTIONS if x != "face" and (not motions or x != motions[-1])]
        motions.append(rnd.choice(pool))
    for i in range(len(metas) - 1):
        pool = [t for t in trans_pool if not trans or t != trans[-1]] or trans_pool
        trans.append(rnd.choice(pool))
    return motions, trans

def motion_expr(kind: str, n: int, face=None, big: float = 1.15) -> tuple[str, str, str]:
    """Biểu thức zoompan (z, x, y) cho từng kiểu chuyển động. p = tiến độ 0→1 (có làm mượt đầu/cuối)."""
    p = f"(on/{n})"
    e = f"({p}*{p}*(3-2*{p}))"                         # smoothstep: tăng tốc/giảm tốc êm
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == "zoom_in":   return f"1+{big - 1:.2f}*{e}", cx, cy
    if kind == "zoom_out":  return f"{big:.2f}-{big - 1:.2f}*{e}", cx, cy
    if kind == "pan_right": return f"{big:.2f}", f"(iw-iw/zoom)*{e}", cy
    if kind == "pan_left":  return f"{big:.2f}", f"(iw-iw/zoom)*(1-{e})", cy
    if kind == "tilt_down": return f"{big:.2f}", cx, f"(ih-ih/zoom)*{e}"
    if kind == "tilt_up":   return f"{big:.2f}", cx, f"(ih-ih/zoom)*(1-{e})"
    if kind == "face" and face:
        fx, fy, fs = face
        target = max(1.25, min(2.2, 0.55 / max(fs, 0.05)))  # mặt chiếm ~55% chiều cao khung khi zoom hết
        z = f"1+{target - 1:.3f}*{e}"
        ccx = f"(0.5+({fx:.4f}-0.5)*{e})"                  # tâm khung trượt dần từ giữa ảnh tới khuôn mặt
        ccy = f"(0.5+({fy:.4f}-0.5)*{e})"
        return (z, f"max(0,min(iw-iw/zoom,{ccx}*iw-iw/zoom/2))", f"max(0,min(ih-ih/zoom,{ccy}*ih-ih/zoom/2))")
    return motion_expr("zoom_in", n)

def make_segment(bg: Path, txt: Path, audio: Path, out: Path, motion: str = "zoom_in", face=None):
    tag = out.with_suffix(".motion")                     # đổi kiểu chuyển động → dựng lại slide đó
    if (out.exists() and tag.exists() and tag.read_text() == motion
            and out.stat().st_mtime > max(p.stat().st_mtime for p in (bg, txt, audio))):
        return out
    dur = duration(audio) + HEAD + TAIL
    n = int(dur * FPS)
    k = 2 if motion == "face" else 1.5                   # phóng nền lớn hơn khi zoom sâu → không bị rung
    z, x, y = motion_expr(motion, n, face)
    fc = (f"[0:v]scale={int(W * k)}:{int(H * k)},zoompan=z='{z}':x='{x}':y='{y}'"
          f":d={n}:s={W}x{H}:fps={FPS}[kb];"
          f"[1:v]format=rgba,loop=-1:1:0,setpts=N/{FPS}/TB,fade=t=in:st={HEAD + 0.3:.2f}:d=0.8:alpha=1[t];"
          f"[kb][t]overlay=0:0:shortest=1,format=yuv420p[v];"
          f"[2:a]adelay={int(HEAD * 1000)}|{int(HEAD * 1000)},apad,aresample=48000[a]")
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(bg), "-i", str(txt), "-i", str(audio),
         "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(out)])
    tag.write_text(motion)
    return out

def slide_starts(segments: list[Path], xd: float = XFADE) -> tuple[list[float], float]:
    durs = [duration(p) for p in segments]
    starts, t = [0.0], durs[0]
    for d in durs[1:]:
        starts.append(t - xd); t += d - xd
    return starts, t

def join_with_transitions(segments: list[Path], transitions: list[str], out: Path, xd: float = XFADE,
                          fade_in: float = 0.6, fade_out: float = 1.2) -> list[float]:
    """Nối các slide bằng hiệu ứng chuyển cảnh (xfade) + hoà âm (acrossfade). Trả về thời điểm bắt đầu mỗi slide."""
    starts, total = slide_starts(segments, xd)
    if len(segments) == 1:
        shutil.copy(segments[0], out); return starts
    inputs, fc, v, a = [], [], "[0:v]", "[0:a]"
    for p in segments:
        inputs += ["-i", str(p)]
    for i in range(1, len(segments)):
        off = starts[i]
        vo, ao = f"[v{i}]", f"[a{i}]"
        fc.append(f"{v}[{i}:v]xfade=transition={transitions[i - 1]}:duration={xd}:offset={off:.3f}{vo}")
        fc.append(f"{a}[{i}:a]acrossfade=d={xd}:c1=tri:c2=tri{ao}")
        v, a = vo, ao
    fc.append(f"{v}fade=t=in:st=0:d={fade_in},fade=t=out:st={total - fade_out:.2f}:d={fade_out},format=yuv420p[vout]")
    script = out.with_suffix(".filter.txt")
    script.write_text(";".join(fc), encoding="utf-8")
    run(["ffmpeg", "-y", *inputs, "-filter_complex_script", str(script), "-map", "[vout]", "-map", a,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", str(out)])
    return starts

def assemble(segments: list[Path], transitions: list[str], music: Path | None, out: Path,
             work: Path | None = None, xd: float = XFADE, music_vol: float = 0.09, **fades) -> list[float]:
    work = work or out.parent / "_work"
    plan = work / f"{out.stem}.plan.json"                 # đã dựng đúng như vậy rồi → không dựng lại
    key = json.dumps({"t": transitions, "s": [str(p) for p in segments], "m": str(music), "v": music_vol})
    if (out.exists() and plan.exists() and plan.read_text() == key
            and out.stat().st_mtime > max(p.stat().st_mtime for p in segments)):
        log(f"  {out.name}: đã có, bỏ qua bước ghép")
        return slide_starts(segments, xd)[0]
    raw = work / f"{out.stem}.raw.mp4"
    starts = join_with_transitions(segments, transitions, raw, xd, **fades)
    if music and music.exists():
        D = duration(raw)
        fc = (f"[1:a]volume={music_vol},afade=t=in:d=2,afade=t=out:st={D-4:.2f}:d=4[m];"
              f"[m][0:a]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=400[duck];"
              f"[0:a][duck]amix=inputs=2:duration=first:normalize=0[a]")
        run(["ffmpeg", "-y", "-i", str(raw), "-stream_loop", "-1", "-i", str(music),
             "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)])
        raw.unlink()
    else:
        shutil.move(str(raw), str(out))
    plan.write_text(key)
    return starts

# ----------------------------------------------------------------------------- 5. thumbnail
def make_thumbnail(pkg: dict, img_dir: Path, out: Path):
    t = pkg.get("thumbnail", {})
    sid = t.get("slide_id", pkg["slides"][0]["id"])
    cands = [img_dir / f"{sid:02d}.jpg"] + sorted(img_dir.glob("*.jpg"))
    src = next((p for p in cands if p.exists()), None)
    img = Image.open(src).convert("RGB") if src else Image.new("RGB", (1280, 720), (18, 18, 22))
    rtl = LANGS[CUR["lang"]]["rtl"]                     # tiếng Ả Rập: chữ bên PHẢI, khuôn mặt bên trái
    th = ImageOps.fit(img, (1280, 720), centering=(0.3 if rtl else 0.7, 0.3))
    shade = Image.new("L", (1280, 1))
    [shade.putpixel((x, 0), max(0, int(235 - (1279 - x if rtl else x) * 0.33))) for x in range(1280)]
    th.paste(Image.new("RGB", (1280, 720), (0, 0, 0)), (0, 0), shade.resize((1280, 720)))
    dr = ImageDraw.Draw(th)
    y = 150
    for text, size, color in [(t.get("line1", ""), 92, (255, 255, 255)), (t.get("line2", ""), 76, (255, 200, 40))]:
        text = upper(text)
        f = font(size, text=text)
        while size > 52 and any(tlen(dr, w, f) > 700 for w in tokens(text)[0]):
            size -= 6; f = font(size, text=text)         # từ quá dài (tiếng Pháp/Tây Ban Nha) → thu nhỏ chữ
        for ln in _wrap(dr, text, f, 700)[:2]:
            x = 1280 - 60 - tlen(dr, ln, f) if rtl else 60
            dtext(dr, (x, y), ln, f, fill=color, stroke_width=6, stroke_fill=(0, 0, 0)); y += int(size * 1.15)
        y += 10
    th.save(out, quality=95)

# ----------------------------------------------------------------------------- 6. metadata
def hashtags(items) -> str:
    """Hashtag cho mô tả: luôn có '#', không khoảng trắng (khoảng trắng → '_'), bỏ trùng, tối đa 15."""
    out = []
    for t in items or []:
        t = "#" + re.sub(r"\s+", "_", str(t).strip().lstrip("#").strip())
        if len(t) > 1 and t.lower() not in [x.lower() for x in out]:
            out.append(t)
    return " ".join(out[:15])

def clean_tags(items) -> list[str]:
    """Tags (ô 'Thẻ' trong YouTube Studio): KHÔNG có '#', không dấu phẩy, bỏ trùng."""
    out = []
    for t in items or []:
        t = re.sub(r"\s+", " ", str(t).replace("#", " ").replace(",", " ")).strip()
        if t and t.lower() not in [x.lower() for x in out]:
            out.append(t)
    return out
def build_description(pkg: dict, chap: str, limit: int = 4900) -> str:
    """Mô tả YouTube ≤ 5.000 ký tự: rút gọn dần phần nguồn và ghi công ảnh nếu quá dài."""
    m = pkg["youtube"]; tags = hashtags(m.get("hashtags", []))
    srcs_all = [str(x) for x in pkg.get("sources", [])]
    # gộp ghi công ảnh theo tác giả + giấy phép: "Slide 1, 4, 9: Wikimedia Commons / X (Public domain)"
    groups = {}
    for sl in pkg["slides"]:
        groups.setdefault((sl.get("image_credit", ""), sl.get("license", "")), []).append(str(sl["id"]))
    credits = "\n".join(f"- {L('slide')} {', '.join(ids)}: {c} ({l})" for (c, l), ids in groups.items())
    for n_src, url in [(len(srcs_all), True), (8, True), (8, False), (5, False), (3, False)]:
        srcs = srcs_all[:n_src] if url else [re.sub(r"\s*[–-]?\s*https?://\S+", "", x) for x in srcs_all[:n_src]]
        desc = (f"{m['description'].strip()}\n\n{L('chap')}\n{chap}\n\n{L('src')}\n"
                + "\n".join(f"- {x}" for x in srcs)
                + f"\n\n{L('img')}\n{credits}\n\n{tags}\n")
        if len(desc) <= limit:
            return desc
    return desc[:limit - len(tags) - 2] + "\n" + tags

def write_metadata(pkg: dict, chapters: list[tuple[float, str]], d: Path):
    m = pkg["youtube"]
    chap = "\n".join(f"{fmt_ts(t)} {name}" for t, name in chapters)
    tags = hashtags(m.get("hashtags", []))
    desc = build_description(pkg, chap)
    (d / "youtube_description.txt").write_text(desc, encoding="utf-8")
    full = "\n".join(f"- {L('slide')} {sl['id']}: {sl.get('image_credit','')} ({sl.get('license','')}) {sl.get('image_url','')}" for sl in pkg["slides"])
    (d / "credits_full.txt").write_text(L("src_full") + "\n" + "\n".join(f"- {x}" for x in pkg.get("sources", []))
                                       + "\n\n" + L("img_full") + "\n" + full, encoding="utf-8")
    (d / "youtube_title.txt").write_text("\n".join([m["title"]] + m.get("alt_titles", [])), encoding="utf-8")
    tag_list, total = [], 0
    for t in clean_tags(m.get("tags", [])):         # YouTube: tổng tag ≤ 500 ký tự
        if total + len(t) + 2 > 480: break
        tag_list.append(t); total += len(t) + 2
    (d / "tags.txt").write_text(", ".join(tag_list), encoding="utf-8")
    (d / "facebook_post.txt").write_text(m.get("facebook_post", m["description"]) + "\n\n" + tags, encoding="utf-8")
    (d / "script_voiceover.txt").write_text(
        "\n\n".join(f"[{L('slide')} {s['id']} – {s.get('section','')}]\n{_x(s, 'narration')}" for s in pkg["slides"]),
        encoding="utf-8")


# ----------------------------------------------------------------------------- 7. SHORTS (dọc 1080x1920)
SW, SH = 1080, 1920
S_HEAD, S_TAIL, S_XFADE = 0.35, 0.45, 0.4

def _wrap(draw, text: str, f, max_w: int) -> list[str]:
    words, j = tokens(text)
    lines, cur = [], ""
    for w in words:
        t = (cur + j + w).strip() if cur else w
        if tlen(draw, t, f) <= max_w:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def short_background(img_path: Path, face_img, out: Path):
    """Khung dọc: ảnh dọc/chân dung → cắt kín khung, giữ khuôn mặt ở 1/3 trên; ảnh ngang → đặt trên nền mờ.
    Trả về (đường dẫn, vị trí khuôn mặt trong khung dọc hoặc None)."""
    img = (Image.open(img_path).convert("RGB") if img_path.exists() else Image.new("RGB", (SW, SH), (18, 18, 22)))
    w, h = img.size
    sface = None
    if w / h < 0.9:                                          # ảnh dọc → cắt kín khung
        k = max(SW / w, SH / h); nw, nh = int(w * k + 0.5), int(h * k + 0.5)
        big = img.resize((nw, nh), Image.LANCZOS)
        fx, fy = ((face_img[0] * nw, face_img[1] * nh) if face_img else (nw / 2, nh * 0.42))
        left = int(min(max(fx - SW / 2, 0), nw - SW)); top = int(min(max(fy - SH * 0.40, 0), nh - SH))
        frame = big.crop((left, top, left + SW, top + SH))
        if face_img:
            sface = [(fx - left) / SW, (fy - top) / SH, face_img[2] * nh / SH]
    else:                                                    # ảnh ngang → nền mờ + ảnh rộng toàn khung
        frame = ImageOps.fit(img, (SW, SH)).filter(ImageFilter.GaussianBlur(45))
        frame = Image.blend(frame, Image.new("RGB", (SW, SH), (0, 0, 0)), 0.45)
        fg = img.copy(); k = SW / w; fg = fg.resize((SW, int(h * k)), Image.LANCZOS)
        if fg.height > SH * 0.62:
            fg = ImageOps.fit(fg, (SW, int(SH * 0.62)))
        frame.paste(fg, (0, int(SH * 0.47 - fg.height / 2)))
    frame.save(out)
    return out, sface

def _balanced(draw, text: str, size_max: int, size_min: int, max_w: int, max_lines: int = 2):
    """Chọn cỡ chữ lớn nhất vừa khung, chia dòng cân đối (không để một chữ lẻ loi ở dòng dưới)."""
    words, j = tokens(text)
    for size in range(size_max, size_min - 1, -4):
        f = font(size, text=text)
        if tlen(draw, text, f) <= max_w:
            return f, [text]
        if max_lines >= 2 and len(words) > 1:
            best = min(((max(tlen(draw, j.join(words[:i]), f), tlen(draw, j.join(words[i:]), f)), i)
                        for i in range(1, len(words))))
            if best[0] <= max_w:
                return f, [j.join(words[:best[1]]), j.join(words[best[1]:])]
    f = font(size_min, text=text)
    return f, _wrap(draw, text, f, max_w)[:max_lines + 1]

def short_text_layers(hook: str, chunks: list[str], d: Path, sid: int) -> tuple[Path, list[Path]]:
    """Dòng chữ lớn gây tò mò (trên) + các đoạn phụ đề (dưới), né vùng nút bấm của YouTube Shorts."""
    hook_png = d / f"s{sid:02d}_hook.png"
    im = Image.new("RGBA", (SW, SH), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    grad = Image.new("L", (1, 520)); [grad.putpixel((0, y), int(170 * (1 - y / 519))) for y in range(520)]
    im.paste(Image.new("RGBA", (SW, 520), (0, 0, 0, 255)), (0, 0), grad.resize((SW, 520)))
    if hook:
        f, lines = _balanced(dr, upper(hook), 92, 56, SW - 150)
        y, step = 230, int(f.size * 1.18)
        for ln in lines:
            dtext(dr, ((SW - tlen(dr, ln, f)) / 2, y), ln, f, fill=(255, 214, 64),
                    stroke_width=max(5, f.size // 11), stroke_fill=(0, 0, 0)); y += step
    im.save(hook_png)
    subs = []
    for k, ch in enumerate(chunks):
        im = Image.new("RGBA", (SW, SH), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
        f, lines = _balanced(dr, ch, 64, 48, SW - 220)
        step = int(f.size * 1.25); y = 1290 - (len(lines) - 1) * step // 2
        for ln in lines:
            dtext(dr, ((SW - tlen(dr, ln, f)) / 2, y), ln, f, fill=(255, 255, 255),
                    stroke_width=6, stroke_fill=(0, 0, 0)); y += step
        pth = d / f"s{sid:02d}_sub{k:02d}.png"; im.save(pth); subs.append(pth)
    return hook_png, subs

def split_chunks(text: str, max_words: int = 6) -> list[str]:
    """Chia lời đọc thành các đoạn phụ đề ngắn, ưu tiên cắt ở dấu câu."""
    out = []
    if LANGS[CUR["lang"]]["cjk"]:                         # chữ Hán: cắt ở dấu câu, mỗi đoạn ≤ 14 chữ
        pieces = [p.strip() for p in re.findall(r"[^，。！？；：、,.!?;:]+[，。！？；：、,.!?;:]*", text.strip()) if p.strip()]
        merged = []
        for p in pieces:                                  # gộp các vế ngắn liền nhau (≤ 16 chữ)
            if merged and len(merged[-1]) + len(p) <= 16:
                merged[-1] += p
            else:
                merged.append(p)
        for p in merged:                                  # vế dài → chia đều, không để đuôi lẻ
            k = -(-len(p) // 15); size = -(-len(p) // k)
            out += [p[i:i + size] for i in range(0, len(p), size)]
        return out or [text]
    for sent in re.split(r"(?<=[.!?…,;:،؛؟])\s+", text.strip()):
        words = sent.split()
        while words:
            n = len(words) if len(words) <= max_words + 2 else max_words
            out.append(" ".join(words[:n])); words = words[n:]
    return out

def make_short_scene(bg: Path, hook: Path, subs: list[Path], chunks: list[str], audio: Path,
                     out: Path, motion: str, face=None) -> Path:
    tag = out.with_suffix(".motion")
    if (out.exists() and tag.exists() and tag.read_text() == motion
            and out.stat().st_mtime > max(p.stat().st_mtime for p in [bg, hook, audio, *subs])):
        return out
    speech = duration(audio); dur = speech + S_HEAD + S_TAIL; n = int(dur * FPS)
    z, x, y = motion_expr(motion, n, face, big=1.18)
    inputs = ["-loop", "1", "-i", str(bg), "-i", str(hook), "-i", str(audio)]
    for p in subs:
        inputs += ["-i", str(p)]
    fc = [f"[0:v]scale={SW * 2}:{SH * 2},zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={SW}x{SH}:fps={FPS}[kb]",
          f"[1:v]format=rgba,loop=-1:1:0,setpts=N/{FPS}/TB,fade=t=in:st=0.1:d=0.3:alpha=1[h]",
          "[kb][h]overlay=0:0:shortest=1[b0]"]
    total_chars = sum(len(c) for c in chunks) or 1
    t, last = S_HEAD, "[b0]"
    for k, (p, c) in enumerate(zip(subs, chunks)):        # phụ đề chạy theo nhịp lời đọc
        dt = speech * len(c) / total_chars
        fc.append(f"[{3 + k}:v]format=rgba[s{k}]")
        fc.append(f"{last}[s{k}]overlay=0:0:enable='between(t,{t:.2f},{t + dt:.2f})'[b{k + 1}]")
        last, t = f"[b{k + 1}]", t + dt
    fc.append(f"{last}format=yuv420p[v]")
    fc.append(f"[2:a]adelay={int(S_HEAD * 1000)}|{int(S_HEAD * 1000)},apad,aresample=48000[a]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
         "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(out)])
    tag.write_text(motion)
    return out

def build_short(pkg: dict, out: Path, work: Path, cfg: dict, music: Path | None, skip_tts=False,
                img_dir: Path | None = None) -> Path | None:
    img_dir = img_dir or work / "images"
    sh = pkg.get("short")
    if not sh or not sh.get("scenes"):
        log("  (gói JSON chưa có phần 'short' → bỏ qua Shorts)")
        return None
    d = work / "short"; d.mkdir(parents=True, exist_ok=True)
    # Shorts đọc chậm hơn video chính 5% (đổi bằng CFG['SHORT_SPEED'] nếu muốn)
    scfg = dict(cfg, SPEED=round(cfg.get("SHORT_SPEED", cfg.get("SPEED", 1.0) * 0.95), 3))
    import random
    rnd = random.Random(pkg.get("slug", "") + "-short")
    trans_pool = [t for t in available_transitions() if t in ("fade", "smoothleft", "smoothright", "slideleft",
                                                               "slideright", "zoomin", "hblur")] or ["fade"]
    scenes, transitions, prev = [], [], None
    for i, sc in enumerate(sh["scenes"], 1):
        sid = int(sc["slide_id"])
        meta_f = work / "slides" / f"{sid:02d}_meta.json"
        face_img = (json.loads(meta_f.read_text(encoding="utf-8")).get("face_img") if meta_f.exists() else None)
        bg, sface = short_background(img_dir / f"{sid:02d}.jpg", face_img, d / f"s{i:02d}_bg.png")
        narr = _x(sc, "narration")
        # bản Việt: phụ đề tiếng Anh (subtitle_en); bản ngôn ngữ khác: phụ đề chính là lời đọc
        sub_text = (sc.get("subtitle_en") if CUR["lang"] == "vi" else sc.get("subtitle")) or narr
        chunks = split_chunks(sub_text, max_words=6)
        hook, subs = short_text_layers(sc.get("hook_text", ""), chunks, d, i)
        audio = work / "audio" / f"short_{i:02d}.mp3"
        if not skip_tts:
            vbee_tts(narr, audio, scfg)
        pool = (["face"] * 3 if sface else []) + ["zoom_in", "zoom_out", "tilt_up", "tilt_down"]
        motion = rnd.choice([m for m in pool if m != prev] or pool); prev = motion
        scenes.append(make_short_scene(bg, hook, subs, chunks, audio, d / f"scene_{i:02d}.mp4", motion, sface))
        log(f"  short cảnh {i} ✓ ({motion})")
        if i > 1:
            transitions.append(rnd.choice([t for t in trans_pool if not transitions or t != transitions[-1]] or trans_pool))
    video = out / f"{pkg['slug']}_short.mp4"
    assemble(scenes, transitions, music, video, work=d, xd=S_XFADE, music_vol=0.14, fade_in=0.2, fade_out=0.6)
    dur = duration(video)
    log(f"   short ✓ {dur:.1f} giây" + ("  ⚠ dài hơn 60 giây — nên rút gọn lời đọc" if dur > 60 else ""))
    tags = hashtags(["#Shorts"] + list(sh.get("hashtags") or pkg["youtube"].get("hashtags", [])))
    (out / "short_title.txt").write_text(sh.get("title", pkg["youtube"]["title"])[:95], encoding="utf-8")
    (out / "short_description.txt").write_text(
        f"{sh.get('description', '').strip()}\n\n{L('watch')} {{MAIN_URL}}\n\n{tags}\n", encoding="utf-8")
    return video

# ----------------------------------------------------------------------------- CHẠY TOÀN BỘ
def voice_cfg(cfg: dict, lang: str) -> dict:
    """Giọng Vbee + tốc độ theo ngôn ngữ: CFG['VOICES'] = {'en': 'mã giọng', ...}, CFG['SPEEDS'] (tuỳ chọn)."""
    voice = (cfg.get("VOICES") or {}).get(lang) or (cfg.get("VOICE_CODE") if lang == "vi" else None)
    if not voice:
        raise SystemExit(f"❌ Chưa có mã giọng Vbee cho ngôn ngữ '{lang}'. Thêm vào CFG['VOICES'] ở ô 2.")
    speed = (cfg.get("SPEEDS") or {}).get(lang, cfg.get("SPEED", 1.0))
    c = dict(cfg, VOICE_CODE=voice, SPEED=speed)
    if lang != "vi":
        c.pop("SHORT_SPEED", None)                     # Shorts bản dịch: chậm hơn 5% so với giọng của ngôn ngữ đó
    return c

def sync_images_from_base(pkg: dict, base_file: Path) -> int:
    """Bản dịch dùng ĐÚNG ảnh của bản Việt (kể cả ảnh đã được thay thế tự động/do bạn tự thay)."""
    if not base_file.exists():
        return 0
    base = {s["id"]: s for s in json.loads(base_file.read_text(encoding="utf-8")).get("slides", [])}
    n = 0
    for s in pkg["slides"]:
        b = base.get(s["id"])
        if b:
            for k in ("image_url", "backup_image_urls", "image_credit", "license"):
                if k in b and s.get(k) != b[k]:
                    s[k] = b[k]; n += 1
    return n

def build(package_path: str, output_root: str, cfg: dict, music_path: str | None = None, skip_tts=False):
    pkg = json.loads(Path(package_path).read_text(encoding="utf-8"))
    lang = norm_lang(pkg.get("lang")); CUR["lang"] = lang; pkg["lang"] = lang
    root = Path(output_root) / pkg["slug"]                # output/<tên>/
    out = root / LANGS[lang]["folder"]; work = out / "_work"   # output/<tên>/<Ngôn ngữ>/
    img_dir = root / "images"                             # ảnh dùng chung cho mọi ngôn ngữ
    for sub in ["slides", "audio", "segments"]:
        (work / sub).mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    vcfg = voice_cfg(cfg, lang)
    global UA
    if cfg.get("CONTACT"):
        UA = f"BiographyVideoFactory/1.1 (personal educational video project; contact: {cfg['CONTACT']})"
    log(f"Ngôn ngữ: {lang}  →  {out}")

    if lang != "vi":
        n = sync_images_from_base(pkg, root / LANGS["vi"]["folder"] / "production.json")
        if n:
            log(f"  đồng bộ {n} thông tin ảnh theo bản Việt")
    log("1/7 Tải ảnh tư liệu…")
    report = download_images(pkg, img_dir)
    shutil.copy(root / "image_report.txt", out / "image_report.txt")
    only_short = bool(pkg.get("only_short"))             # gói chỉ yêu cầu làm Shorts cho video đã có
    if not only_short:
        (out / "production.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = [r for r in report if "✗" in r]
    if missing:
        log(f"  ⚠ {len(missing)} slide thiếu ảnh — xem image_report.txt")
    log("2/7 Dựng slide…")
    layers = [render_slide_layers(s, img_dir / f"{s['id']:02d}.jpg", work / "slides") for s in pkg["slides"]]
    music = Path(music_path) if music_path else None
    if only_short:
        log("Chế độ CHỈ LÀM SHORTS (video chính giữ nguyên)")
        build_short(pkg, out, work, vcfg, music, skip_tts, img_dir)
        log(f"HOÀN TẤT → {out}")
        return out
    log("3/7 Vbee đọc voice-over…")
    audios = []
    for s in pkg["slides"]:
        a = work / "audio" / f"{s['id']:02d}.mp3"
        if not skip_tts:
            vbee_tts(_x(s, "narration"), a, vcfg)
        audios.append(a); log(f"  audio {s['id']:02d} ✓ {duration(a):.1f}s")
    log("4/7 Ghép video…")
    metas = []
    for s in pkg["slides"]:
        mf = work / "slides" / f"{s['id']:02d}_meta.json"
        metas.append(json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {})
    motions, transitions = plan_effects(pkg, metas)       # cùng tên nhân vật → cùng hiệu ứng ở mọi ngôn ngữ
    segs = []
    for s, (bg, txt), a, mo, me in zip(pkg["slides"], layers, audios, motions, metas):
        segs.append(make_segment(bg, txt, a, work / "segments" / f"{s['id']:02d}.mp4", mo, me.get("face")))
        log(f"  slide {s['id']:02d} ✓ chuyển động: {mo}")
    log(f"  chuyển cảnh: {', '.join(transitions)}")
    video = out / f"{pkg['slug']}.mp4"
    starts = assemble(segs, transitions, music, video)
    chapters, last_sec = [], None
    for s, st in zip(pkg["slides"], starts):
        if s.get("section") and s["section"] != last_sec:
            chapters.append((st, s["section"])); last_sec = s["section"]
    log(f"   video ✓ {fmt_ts(duration(video))}")
    log("5/7 Thumbnail…");  make_thumbnail(pkg, img_dir, out / "thumbnail.jpg")
    log("6/7 Description, hashtag, chapters…");  write_metadata(pkg, chapters, out)
    log("7/7 Video Shorts…")
    build_short(pkg, out, work, vcfg, music, skip_tts, img_dir)
    (out / "slides").mkdir(exist_ok=True)               # 20 slide xem trước (ảnh + chữ)
    for s, (bg, txt) in zip(pkg["slides"], layers):
        im = Image.open(bg).convert("RGBA"); im.alpha_composite(Image.open(txt))
        im.convert("RGB").save(out / "slides" / f"slide_{s['id']:02d}.jpg", quality=90)
    log(f"HOÀN TẤT → {out}")
    return out
