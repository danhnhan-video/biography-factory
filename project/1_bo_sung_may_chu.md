## MÁY CHỦ TỰ ĐỘNG (thay cho việc mở Colab)

Video được dựng tự động bởi máy chủ GitHub. Máy chủ kiểm tra `DanhNhan/_inbox` mỗi 30 phút.
Trạng thái của mỗi file JSON thể hiện qua thư mục chứa nó trên Google Drive:

| Thư mục | Ý nghĩa |
|---|---|
| `DanhNhan/_inbox` | Chờ máy chủ nhận (tối đa ~30 phút) |
| `DanhNhan/_dang_lam` | Đang dựng (mỗi ngôn ngữ ~1–1,5 giờ, tối đa 3 ngôn ngữ cùng lúc) |
| `DanhNhan/_done` | Đã xong — kết quả ở `DanhNhan/output/<slug>/<Viet|Anh|Phap|TayBanNha|ARap|Trung>/` |
| `DanhNhan/_loi` | Lỗi — có file `<tên>.loi.txt` ghi nguyên nhân |

### Lệnh dùng được (kể cả trên điện thoại)
- **"Làm video về [tên]"** → Bước 1 (nghiên cứu + kịch bản), dừng chờ duyệt.
- **"Duyệt"** → lưu `<slug>.json` (tiếng Việt, thêm `"lang": "vi"`) vào `_inbox`.
- **"Duyệt + đa ngữ"** → lưu bản Việt VÀ ngay sau đó làm "Dịch đa ngữ" (5 file `<slug>.<lang>.json`), tất cả vào `_inbox`. Báo bảng tóm tắt 6 file.
- **"Tiến độ"** → dùng Google Drive liệt kê các file trong `_inbox`, `_dang_lam`, `_loi` và 10 file mới nhất trong `_done`; với mỗi nhân vật đang làm, liệt kê các thư mục ngôn ngữ đã có video `.mp4` trong `output/<slug>/`. Trình bày bảng ngắn: Nhân vật | Ngôn ngữ | Trạng thái. Nếu có lỗi, đọc file `.loi.txt` và giải thích bằng tiếng Việt dễ hiểu + cách sửa.
- **"Chạy lại [tên file]"** → chuyển file JSON đó từ `_loi` (hoặc `_done`) về `_inbox` bằng Google Drive (đổi thư mục cha). Audio đã đọc được giữ lại nên không tốn Vbee lần 2.
- **"Sửa ảnh slide [số] của [slug]"** → tìm ảnh thay thế đúng quy tắc ảnh tư liệu, sửa `image_url`/`image_credit`/`license` của slide đó trong `output/<slug>/Viet/production.json` thành gói mới, lưu `<slug>.json` vào `_inbox` (máy chủ tự thấy link ảnh đã đổi và tải ảnh mới). Sau đó lưu lại các bản dịch đang có trong `_done` của nhân vật này về `_inbox` để dựng lại với ảnh mới.

### Quy tắc khi lưu file
- Luôn lưu vào đúng thư mục `DanhNhan/_inbox` (thư mục `DanhNhan` ở gốc My Drive). Dạng file JSON thuần (application/json), không chuyển thành Google Docs.
- Tên file: bản Việt `<slug>.json`; bản dịch `<slug>.<lang>.json`. Cùng một `slug` cho mọi ngôn ngữ.
- Sau khi lưu, nói ngắn gọn: "Đã gửi N việc cho máy chủ. Video sẽ có sau khoảng X giờ; bạn sẽ nhận thông báo trên điện thoại."
