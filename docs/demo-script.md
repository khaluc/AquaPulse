# Kịch bản demo 3–5 phút: kênh Nhiêu Lộc – Thị Nghè

*English version: [demo-script.en.md](demo-script.en.md).*

Câu chuyện của bản ý tưởng AquaPulse: trước mưa → sau mưa → ba người báo váng dầu cùng một đoạn kênh
→ AI chỉ "nghi ngờ" → cảnh báo mức vàng có bằng chứng → tình nguyện viên xác minh → cảnh báo cập nhật và
khuyến nghị tránh tiếp xúc với nước.

Các số dưới đây là số hệ thống tạo ra sau khi chạy `seed_river_demo.py` (ngày 18/9/2026). Lượng mưa lấy
thật từ Open-Meteo nên sẽ khác theo ngày chạy.

## Chuẩn bị

```bash
docker compose up -d db
cd backend
python scripts/seed_river_demo.py        # PowerShell: $env:PYTHONIOENCODING="utf-8" trước
python -m uvicorn app.main:app --port 8010
```

- **Cổng:** trên máy đang dùng, cổng 8000 do Docker Desktop giữ, nên ví dụ dùng 8010. Đổi cổng nào cũng được,
  chỉ cần đổi trong đường dẫn bên dưới.
- Cần file `.env` có `AQUAPULSE_REVIEWERS` với một tài khoản `volunteer` và một `expert` (xem `.env.example`).
  File `.env` đã có sẵn trên máy dev này; token nằm trong đó, không commit lên git. Thiếu dòng này thì không
  đăng nhập xác minh được ở bước 4.
- Chạy lại script ngay trước buổi demo để câu chuyện "sau mưa" rơi vào 24 giờ gần nhất.
- Mở sẵn: `/?demo=1`, `/passport?segment=nhieu-loc-thi-nghe-2`, `/tasks-board`, `/report`.
  Thêm `?demo=1` một lần là cả phiên trình duyệt hiện dữ liệu mẫu; dải vàng trên đầu trang ghi rõ đang xem dữ liệu mẫu.
- **Nói rõ với ban giám khảo:** ảnh trong dữ liệu mẫu là ảnh vẽ, đóng chữ "ẢNH MẪU DEMO"; phần AI "nghi ngờ váng dầu"
  trên các ảnh đó là mô phỏng. Muốn thấy AI thật, gửi một ảnh thật ở bước 5.

## Kịch bản

**0:00 · Vấn đề (20 giây).** "Người dân nhìn thấy kênh mỗi ngày: màu nước, mùi, rác, váng dầu. Nhưng những quan sát
đó rời rạc, khó hiểu, không thành hành động. AquaPulse là trạm y tế cho sông đô thị."

**0:20 · Trang chủ (40 giây).** Kênh Nhiêu Lộc – Thị Nghè chia 4 đoạn, tô màu theo mức. Đoạn 2 màu vàng.
Bảng "Hộ chiếu dòng kênh": mỗi đoạn có Eco, Risk, Tin cậy, Xu hướng, Sức khỏe người. Mục "Cảnh báo":

> Mức vàng · 3 quan sát trong bán kính 500 m ghi nhận váng dầu (3), mùi lạ (3), rác nổi (3) trong 22 giờ.
> Bằng chứng: 3 người khác nhau, 3 ảnh; AI chỉ gán "nghi ngờ", chưa kết luận.
> Độ tin cậy: trung bình (0,74), phần lớn ảnh chụp ban đêm.
> Ai xác minh: cần nhóm tình nguyện viên xác minh tại hiện trường.
> Bạn nên làm gì: tránh tiếp xúc trực tiếp với nước cho đến khi có kết quả kiểm tra.

Nói: "Đây là 5 phần của một cảnh báo có bằng chứng. Không có chữ 'nước bẩn', không có chữ 'ổ dịch'."

**1:00 · Hộ chiếu đoạn 2 (50 giây).** Eco 0,31 · Risk 0,67 · Tin cậy trung bình · Sức khỏe người 0,77.
Câu giải thích do hệ thống sinh ra từ số liệu: "Độ tin cậy trung bình vì phần lớn quan sát được gửi vào ban
đêm… chưa có ai xác minh tại hiện trường", "Nên bổ sung 2 quan sát ban ngày trước khi phát cảnh báo chính thức",
"Không để trẻ chơi, lội nước ở đoạn này cho tới khi có kết quả xác minh". Biểu đồ: 14 ngày quan sát và mưa đo được.
Bấm "Có nên cho trẻ chơi gần đây không?": câu trả lời kèm dữ liệu đang dùng, mức chắc chắn, điều chưa biết,
khuyến nghị không mang tính y tế.

**1:50 · Xác minh (50 giây).** `/tasks-board`, đăng nhập tình nguyện viên. Nhận một báo cáo váng dầu ở đoạn 2,
chọn "Có, đúng như báo cáo", ghi chú "Thấy váng dầu loang khoảng 20 m dọc bờ". Quay lại trang chủ: cảnh báo
**lên mức cam**, bằng chứng thêm "1 báo cáo đã được xác nhận tại hiện trường", người xác minh tiếp theo đổi thành
"Cần chuyên gia môi trường lấy mẫu", lời khuyên tránh tiếp xúc với nước vẫn giữ. Mức đỏ chỉ chuyên gia quyết định.

**2:40 · Gửi quan sát thật (60 giây).** `/report`, bước 1 chọn kiểu ảnh: "Mặt nước, dấu hiệu khác" (chỉ AI mô tả)
cho ảnh kênh, hoặc "Vật chứa, nước đọng" nếu chụp chậu, lốp xe (khi đó YOLO11n và model vùng nước mới chạy).
Form "Sông, kênh" có sẵn. Chụp hoặc chọn một ảnh thật, bật
"Hỏi AI mô tả bối cảnh" (Qwen chạy trên máy, ảnh không rời máy chủ). Chọn mục tiêu, trả lời 5–7 câu: màu, mùi,
bọt, váng dầu, rác nổi, có cá sống không. Nếu AI thấy dấu hiệu bạn chưa nhắc, nó hỏi lại:
*"Ảnh cho thấy khả năng có váng dầu, độ tin cậy 70%. Bạn có thấy ánh cầu vồng hoặc mùi xăng dầu không?"*.
Kết quả tách Rủi ro, Sinh thái, Độ tin cậy, Liên quan sức khỏe người. Gửi: báo "Quan sát thuộc đoạn … kênh
Nhiêu Lộc – Thị Nghè", có nút "Tham gia xác minh" và "Đánh dấu thông tin sai".

**3:20 · Dữ liệu của chính dự án (20 giây).** Cuộn tới "Mạng quan trắc châu Âu": AquaPulse đọc API mở của
OneAquaHealth. Chọn Benevento: 20 điểm quan trắc với chỉ số rủi ro sức khỏe của dự án, thêm 69 điểm do người dân
tạo trong Citizen Science App. Bấm một điểm: mầm bệnh, ô nhiễm từ phân, gen kháng kháng sinh, ngày lấy mẫu,
nitrat, thời tiết đo được. Nói rõ: **số của họ chỉ được hiển thị, không trộn vào điểm rủi ro của mình**; báo cáo
người dân chỉ được liên kết tới điểm quan trắc gần nhất kèm khoảng cách.

**3:40 · Chuẩn dữ liệu (20 giây).** Mở `/fhir/waterways/nhieu-loc-thi-nghe-2?include_demo=true`: Bundle FHIR gồm
Location (đoạn kênh), RiskAssessment (hộ chiếu), Observation (từng quan sát, không có mã người báo).

**4:00 · Kết (20 giây).** "AquaPulse biến một bức ảnh của người dân thành tín hiệu có thể hành động, nhưng luôn
cho biết tín hiệu đó chắc chắn đến đâu."

## Đừng nói

| Câu dễ nói | Thực tế |
|---|---|
| "AI phát hiện váng dầu" | AI chỉ gán "nghi ngờ" và hỏi lại. Chưa có model váng dầu được huấn luyện; trong dữ liệu mẫu, phần AI là mô phỏng. |
| "Nước kênh an toàn / độc hại" | Hệ thống không kết luận được. Chỉ lấy mẫu và xét nghiệm mới nói được. |
| "Xu hướng tăng 40%" | Với dữ liệu mẫu, hệ thống ghi "chưa đủ dữ liệu để nói xu hướng" vì mới có 3 báo cáo bất thường; nó cố ý không thổi phồng. |
| "Có loài X ở đoạn này" | Người dân chỉ trả lời có/không thấy cá, tôm, côn trùng sống; chưa định danh loài. |

## Nếu có sự cố

- Không có mạng: bản đồ nền và biểu đồ mưa trống; mọi thứ khác vẫn chạy.
- Không thấy ô "Hỏi AI mô tả bối cảnh" ở bước 1: máy chủ không tìm thấy model. Thường là do bản Ollama cài
  thẳng trên Windows đang giữ cổng 11434 (bản đó không có model), còn model nằm trong container
  `aquapulse-ollama`. Kiểm tra bằng `curl http://127.0.0.1:11434/api/tags`: trả `{"models":[]}` thì tắt
  Ollama trên Windows (cả `ollama app`), chạy `docker restart aquapulse-ollama`, rồi khởi động lại backend.
- Qwen không chạy: bỏ bước "Hỏi AI"; phần còn lại không phụ thuộc.
- Muốn chạy lại từ đầu (cảnh báo về mức vàng): `python scripts/seed_river_demo.py`.
  Muốn có sẵn bước xác minh: thêm `--verify`.
