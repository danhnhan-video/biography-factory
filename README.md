# 🎬 Biography Video Factory: AI Agent làm video tiểu sử danh nhân

Hệ thống tự động: **nghiên cứu → kịch bản → 6 thứ tiếng → dựng video + Shorts → lưu Google Drive → báo về điện thoại.**
Mọi thao tác hằng ngày làm được bằng **điện thoại hoặc máy tính bảng**. Không cần mở máy tính hay Colab.

```
📱 Claude (Project)           ☁️ Google Drive              🖥️ Máy chủ GitHub (miễn phí)          📱 Điện thoại
"Làm video về X"        →     DanhNhan/_inbox        →     30 phút kiểm tra 1 lần              →   🔔 ntfy: "✅ Xong…"
"Duyệt + đa ngữ"              (6 file JSON)                tải ảnh · Vbee đọc · dựng video          app Drive: xem video
"Tiến độ"                                                  → output/<tên>/<Ngôn ngữ>/
```

| Thư mục trên Drive | Ý nghĩa |
|---|---|
| `DanhNhan/_inbox` | Việc chờ máy chủ nhận (tối đa ~30 phút) |
| `DanhNhan/_dang_lam` | Đang dựng (tối đa 3 ngôn ngữ cùng lúc, mỗi ngôn ngữ ~1–1,5 giờ) |
| `DanhNhan/_done` | Đã xong |
| `DanhNhan/_loi` | Bị lỗi, kèm file `.loi.txt` ghi nguyên nhân |
| `DanhNhan/output/<tên>/images` | Ảnh tư liệu dùng chung cho mọi ngôn ngữ |
| `DanhNhan/output/<tên>/Viet`, `Anh`, `Phap`, `TayBanNha`, `ARap`, `Trung` | Video, Shorts, thumbnail, tiêu đề, mô tả của từng thứ tiếng |

---

## PHẦN A: CÀI ĐẶT (làm 1 lần trên máy tính, khoảng 40 phút)

### A1. Bật Google Drive API (khoảng 2 phút)
1. Vào https://console.cloud.google.com và chọn dự án **DanhNhan Video Uploader** (dự án dùng cho YouTube).
2. Mở **APIs & Services → Library**, tìm **Google Drive API**, bấm **Enable**.

### A2. Lấy Drive token cho máy chủ (khoảng 5 phút)
1. Tải file `tools/Lay_Drive_Token.ipynb` lên thư mục `DanhNhan` trên Google Drive.
2. Nhấp đúp file đó, chọn **Open with → Google Colaboratory**.
3. Bấm 🔑 (Secrets) ở cột trái, bật **Notebook access** cho `YT_CLIENT_JSON`.
4. Bấm ▶ chạy ô code và làm theo hướng dẫn hiện ra (giống lần cấp quyền YouTube trước đây).
5. Chép **refresh token** hiện ra vào sổ tạm. Bạn sẽ dán nó ở bước A4.

### A3. Tạo kho code trên GitHub (khoảng 10 phút)
1. Đăng nhập https://github.com bằng tài khoản **danhnhan-video**.
2. Bấm **+ → New repository**. Đặt tên `biography-factory`, chọn **Public** (để chạy miễn phí không giới hạn), rồi bấm **Create repository**.
3. Trên trang kho vừa tạo, bấm **uploading an existing file**.
4. Giải nén file zip, rồi **kéo toàn bộ nội dung bên trong** thư mục `biography-factory` (gồm thư mục `.github`, `factory`, `tools`, `project` và các file) vào trang. Sau đó bấm **Commit changes**.
   - Trên máy Mac, thư mục `.github` bị ẩn. Nhấn **Cmd + Shift + .** để hiện nó ra.
   - Kiểm tra: trong kho phải có `.github/workflows/factory.yml`. Nếu thiếu, bấm **Add file → Create new file**, gõ tên `.github/workflows/factory.yml`, dán nội dung file đó vào rồi Commit.

### A4. Khai báo khóa bí mật (khoảng 5 phút)
Trong kho, vào **Settings → Secrets and variables → Actions → New repository secret**. Thêm lần lượt:

| Name | Giá trị |
|---|---|
| `VBEE_TOKEN` | Token Vbee (giống Secret trong Colab) |
| `VBEE_APP_ID` | App ID Vbee |
| `GDRIVE_CLIENT_JSON` | Toàn bộ nội dung file client JSON. Đây chính là giá trị của Secret `YT_CLIENT_JSON` trong Colab: bấm 👁 để xem rồi chép |
| `GDRIVE_REFRESH_TOKEN` | Refresh token lấy ở bước A2 |
| `NTFY_TOPIC` | Một tên khó đoán do bạn tự đặt, ví dụ `danhnhan-7f3k9q2x`. Ai biết tên này sẽ đọc được thông báo |

Khóa bí mật được GitHub mã hóa: không ai xem được, kể cả khi kho để Public.

### A5. Cài ứng dụng trên điện thoại (khoảng 5 phút)
- **ntfy** (Android hoặc iOS): bấm **+**, nhập đúng tên đã đặt ở `NTFY_TOPIC`. Từ đây bạn nhận thông báo khi bắt đầu, khi xong và khi có lỗi.
- **Claude**: mở Project "Tóm tắt các Danh nhân" (Project dùng chung giữa điện thoại và máy tính).
- **Google Drive**: để xem video.
- **GitHub** (không bắt buộc): để bấm chạy ngay hoặc xem chi tiết lỗi.

### A6. Cập nhật Claude Project (khoảng 3 phút)
Dán thêm vào cuối instruction của Project:
1. `project/1_bo_sung_may_chu.md`: lệnh điều khiển máy chủ ("Duyệt + đa ngữ", "Tiến độ", "Chạy lại").
2. `project/2_huong_dan_da_ngu.md`: nếu bạn chưa dán phần này trước đây.

### A7. Chạy thử
Trên GitHub, vào **Actions → Biography Video Factory → Run workflow**. Bước **Quét _inbox** chạy xong và có dấu ✅ nghĩa là máy chủ đã kết nối được Drive. Nếu `_inbox` đang trống thì không có video nào được dựng, như vậy là bình thường.

---

## PHẦN B: SỬ DỤNG HẰNG NGÀY (trên điện thoại)

| Bạn làm gì | Ở đâu |
|---|---|
| 1. Gõ **Làm video về Marie Curie** | App Claude, trong Project |
| 2. Đọc bảng kiểm chứng và kịch bản, sửa bằng lệnh `Sửa slide 7: …` | App Claude |
| 3. Gõ **Duyệt + đa ngữ**. Claude lưu 6 file JSON vào `_inbox` | App Claude |
| 4. Chờ thông báo 🎬 "Bắt đầu dựng video" (trong khoảng 30 phút) | App ntfy |
| 5. Khoảng 3–4 giờ sau: lần lượt nhận 6 thông báo ✅ "Xong…". Bấm vào thông báo để mở thư mục | App ntfy, rồi app Drive |
| 6. Xem video, đọc `image_report.txt` nếu có ảnh bị thay thế | App Drive |
| Muốn biết tiến độ: gõ **Tiến độ** | App Claude |
| Muốn chạy ngay, không chờ 30 phút | App GitHub: Actions → Run workflow |
| Gặp ❌ lỗi: gõ **Tiến độ** để Claude đọc lỗi và giải thích. Sửa xong thì gõ **Chạy lại isaac-newton.en.json** | App Claude |

Chỉ cần làm bản tiếng Việt thì gõ **Duyệt** thay cho "Duyệt + đa ngữ".

**Thay một ảnh:** đặt ảnh của bạn vào `output/<tên>/images/07.jpg` (đúng số slide), rồi gõ **Chạy lại <tên>.json** và chạy lại các bản dịch. Audio đã đọc được giữ lại nên **không tốn Vbee lần 2**.

---

## PHẦN C: CẤU HÌNH (`config.json` trong kho GitHub)
Sửa trên web GitHub: mở file, bấm ✏️, sửa, rồi **Commit changes**. Làm được cả trên trình duyệt điện thoại.

- `voices`: mã giọng Vbee cho từng thứ tiếng. Mặc định là các giọng có hệ số credit ×1. Muốn hay hơn thì đổi sang giọng Premium ×4, ví dụ `en-US-ChristopherNeural`.
- `speeds`: tốc độ đọc từng thứ tiếng. Shorts tự đọc chậm hơn 5%.
- `youtube`: **để nguyên** `"auto_upload": false` cho tới khi YouTube duyệt API (bước 8).

## PHẦN D: XỬ LÝ SỰ CỐ
| Hiện tượng | Cách xử lý |
|---|---|
| Thông báo "❌ Máy chủ lỗi khi quét _inbox" / `invalid_grant` | Drive token hết hiệu lực. Làm lại bước A2 rồi thay Secret `GDRIVE_REFRESH_TOKEN` |
| `Thiếu GitHub Secret VBEE_TOKEN` | Kiểm tra lại bước A4 (tên Secret phải đúng chữ hoa) |
| `.loi.txt` báo lỗi Vbee 401/403 | Token Vbee sai hoặc hết hạn. Cập nhật Secret `VBEE_TOKEN` |
| File nằm lâu trong `_inbox` | Mở GitHub → Actions xem có lần chạy nào không. GitHub có thể trễ 10–30 phút; bấm **Run workflow** để chạy ngay |
| GitHub gửi email "scheduled workflow disabled" | Vào Actions và bấm **Enable workflow**. Bình thường máy chủ tự giữ hoạt động mỗi tuần |
| Google Drive đầy | Mỗi nhân vật đủ 6 thứ tiếng khoảng 2 GB. Xóa thư mục `audio/` và `slides/` của các video đã đăng, hoặc nâng cấp Google One |

## PHẦN E: DỰ PHÒNG
`tools/Biography_Video_Factory_v5.ipynb`: notebook Colab cũ, vẫn chạy được nếu GitHub gặp sự cố.

## BƯỚC 8 (sau khi YouTube duyệt API)
Code đăng YouTube (`factory/yt_upload.py`) và cấu hình 6 kênh đã có sẵn trong gói. Khi nhận được email duyệt, chỉ cần thêm token cho từng kênh và bật `auto_upload`.
