# Demo local với dữ liệu mẫu

Bộ mẫu dùng database `aquapulse_demo` tại localhost và ảnh trong
`backend/storage/local-demo`. Mỗi quan sát được gắn `is_demo`; ảnh có chữ demo,
mô tả thị giác được mô phỏng, điểm số tính bằng rule engine của ứng dụng.

Chạy từ thư mục gốc bằng PowerShell:

```powershell
docker compose up -d db
backend/.venv/Scripts/python.exe backend/scripts/seed_local_demo.py
backend/.venv/Scripts/python.exe backend/scripts/run_local_demo.py
```

Mở http://localhost:8008/?demo=1. Cờ demo đi theo các trang trong cùng tab.

Quay video thuyết trình: [kịch bản 4 phút và lời đọc](demo-video-local.md).

- Trang chủ: bản đồ, cảnh báo, số quan sát, thông báo, bảng xếp hạng.
- Dashboard: cả bốn lớp, biểu đồ theo ngày, ảnh trước/sau, tỷ lệ xác minh.
- Hộ chiếu: 35 đoạn thuộc 8 tuyến kênh, lịch sử, Risk/Eco và xu hướng.
- Nhiệm vụ: đang mở, hoàn thành, hết hạn; hàng đợi có đủ các trạng thái xác minh.
- Báo cáo: có thể chọn một ảnh từ `backend/storage/local-demo` để thử form.

Mã đăng nhập demo local trên trang nhiệm vụ:

| Vai trò | Mã |
|---|---|
| Tình nguyện viên | `local-demo-volunteer` |
| Chuyên gia | `local-demo-expert` |

Mặc định tạo 8 quan sát mỗi đoạn kênh và 12 cho mỗi nhóm còn lại, tổng cộng 388 quan sát,
24 nhiệm vụ và 45 người tham gia trong hơn ba tuần.
Muốn thêm: `seed_local_demo.py --per-segment 24 --per-group 36`.
Chạy lại thay bộ mẫu cũ trong database demo; giữ các quan sát nhập thật.

OneAquaHealth và báo chí được sao chép từ dữ liệu thật đã lưu trong database local gốc.
Có thể thêm `--sync-reference` để cập nhật từ nguồn công khai. Số đo phòng thí nghiệm
không được bịa thành dữ liệu mẫu.

Cấu hình local được tạo trong `.env.local-demo`. Server chỉ lắng nghe `127.0.0.1`.
Ảnh seed dùng AI mô phỏng; khi bạn tự gửi ảnh qua form, backend dùng Kimi API nếu
`.env` có `DASHSCOPE_API_KEY`. Có thể đặt `AQUAPULSE_VISION_ENABLED=0` trong
`.env.local-demo` để thử form không gọi API.
