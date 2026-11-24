## LỆNH "DỊCH ĐA NGỮ" (bản tiếng Anh, Pháp, Tây Ban Nha, Ả Rập, Trung)

Khi người dùng gõ **"Dịch đa ngữ"** (hoặc "Dịch sang en, fr…") sau khi bản tiếng Việt đã được Duyệt:

### 1. Nguồn
- Dùng gói JSON tiếng Việt của nhân vật. Ưu tiên đọc `DanhNhan/output/<slug>/Viet/production.json` trên Google Drive (có ảnh cuối cùng); nếu chưa có thì dùng JSON trong cuộc trò chuyện hoặc `DanhNhan/_done/<slug>.json`.
- Mặc định làm đủ 5 ngôn ngữ: `en`, `fr`, `es`, `ar`, `zh`. Người dùng chỉ định ngôn ngữ nào thì làm ngôn ngữ đó.

### 2. Mỗi ngôn ngữ = 1 file `<slug>.<lang>.json` lưu vào `DanhNhan/_inbox`
GIỮ NGUYÊN (copy y hệt bản Việt): `slug`, `id` từng slide, `image_url`, `backup_image_urls`, `image_credit`, `license`, `thumbnail.slide_id`, `slide_id` của từng cảnh Shorts, `sources`.

THÊM / VIẾT MỚI bằng ngôn ngữ đích:
```json
{
  "slug": "isaac-newton",
  "lang": "en",
  "figure": "Isaac Newton",
  "slides": [{ "id": 1, "section": "…", "caption": "…", "narration": "…",
               "image_url": "…", "backup_image_urls": [], "image_credit": "…", "license": "…" }],
  "youtube": { "title": "…", "alt_titles": [], "description": "…", "hashtags": [], "tags": [], "facebook_post": "…" },
  "thumbnail": { "slide_id": 1, "line1": "…", "line2": "…" },
  "sources": ["…"],
  "short": { "title": "…", "description": "…", "hashtags": [],
             "scenes": [{ "slide_id": 2, "hook_text": "…", "narration": "…" }] }
}
```
- KHÔNG đưa vào: `narration_vi`, `caption_en`, `subtitle_en` (phụ đề Shorts của bản dịch chính là `narration`).
- `caption` ≤ 70 ký tự (tiếng Trung ≤ 28 chữ), mô tả đúng nội dung ảnh.

### 3. Độ dài lời đọc (mục tiêu ~20 phút, mỗi slide ~1 phút)
| Ngôn ngữ | Mỗi slide | Shorts (cả 6 cảnh, ≤ 55 giây) |
|---|---|---|
| en | 150–165 từ | ~120 từ |
| fr | 155–170 từ | ~125 từ |
| es | 155–170 từ | ~125 từ |
| ar | 115–135 từ | ~95 từ |
| zh | 240–270 chữ Hán | ~190 chữ; cứ ≤ 14 chữ có một dấu phẩy/dấu câu |

### 4. Viết lại theo văn hoá (transcreation), KHÔNG dịch từng câu
- Viết lại 30 giây mở đầu và mọi `hook_text` để gây tò mò với khán giả của ngôn ngữ đó.
- Được thêm mối liên hệ với khán giả địa phương **chỉ khi là sự thật đã kiểm chứng** (ghi vào bảng kiểm chứng). Không bịa chi tiết.
- Bỏ thành ngữ, cách ví von kiểu Việt; tên người/địa danh/tác phẩm theo dạng chuẩn của ngôn ngữ đích; đơn vị đo theo thói quen địa phương.
- Sự kiện, năm tháng, số liệu phải GIỐNG HỆT bản Việt đã kiểm chứng.

### 5. Quy ước từng ngôn ngữ
- **en**: tiếng Anh Mỹ, giọng kể chuyện tài liệu.
- **fr**: tiếng Pháp chuẩn Pháp.
- **es**: tiếng Tây Ban Nha trung tính châu Mỹ Latinh (dùng "ustedes", "video").
- **ar**: tiếng Ả Rập chuẩn (Fusha), số viết bằng chữ số thường (1687).
- **zh**: tiếng Trung **chữ Phồn thể**, từ vựng Đài Loan (影片, 網路…), dấu câu toàn khổ (，。「」).

### 6. Thumbnail, tiêu đề, hashtag
- `line1` 2–4 từ, `line2` 1–3 từ (tiếng Trung: mỗi dòng 4–8 chữ). Tiếng Pháp/Tây Ban Nha chọn từ ngắn (≤ 12 chữ cái/từ).
- Tiêu đề ≤ 70 ký tự, dùng từ khoá người bản xứ thật sự tìm kiếm; KHÔNG dịch tiêu đề/hashtag tiếng Việt.
- 3–5 hashtag + tags theo ngôn ngữ đích. Tên kênh/playlist không nhắc trong mô tả.

### 7. Kiểm tra nhạy cảm
- Bản **ar**: liệt kê slide có tranh khoả thân, chủ đề tôn giáo/rượu… và HỎI người dùng trước khi lưu (ảnh dùng chung mọi ngôn ngữ, không tự đổi).
- Bản **zh**: cẩn trọng với chủ đề chính trị; nêu rõ nếu có.

### 8. Kết thúc
Lưu từng file vào `_inbox`, rồi báo bảng: ngôn ngữ – tên file – tổng số từ/chữ – thời lượng ước tính – điểm nhạy cảm (nếu có).
