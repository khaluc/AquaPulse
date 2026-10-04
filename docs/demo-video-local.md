# Quay video thuyết trình AquaPulse trong khoảng 4 phút

Quay màn hình trình duyệt kèm giọng nói, theo câu chuyện:
quan sát của người dân → phân tích → hộ chiếu đoạn kênh → xác minh → theo dõi kết quả.

Bản lời đọc đầy đủ trong khoảng 4–5 phút: [loi-thuyet-trinh.md](loi-thuyet-trinh.md).

## Chuẩn bị trước khi quay

- Mở http://localhost:8008/?demo=1. Cách khởi động server: [local-demo.md](local-demo.md).
- Mở sẵn các tab: trang chủ, `/report?demo=1`, `/passport?segment=doi-te-1&demo=1`,
  `/tasks-board?demo=1`, `/dashboard?demo=1` trên cùng địa chỉ localhost:8008.
- Chuẩn bị một ảnh sông/kênh thật để thử phân tích. Có thể dùng ảnh trong
  `backend/storage/local-demo` và nói rõ đó là ảnh vẽ minh họa.
- Thử phân tích ảnh một lần trước buổi quay. Form dùng Kimi API khi được bật và có key;
  phần mô tả AI trong dữ liệu đã seed là mô phỏng. Nếu API chưa sẵn sàng, trình bày một
  kết quả đã có và cảnh báo có bằng chứng trên trang chủ.
- Mở rộng cửa sổ trình duyệt, giữ chữ đủ lớn để đọc. Thu thử 10 giây và nghe lại tiếng micro.
- Đăng nhập trước ở trang nhiệm vụ bằng `local-demo-expert`; khi quay chỉ cần mở hàng đợi.

## Thao tác và lời đọc

### 0:00–0:20 · Giới thiệu, giữ trang chủ trên màn hình

> Xin chào, đây là AquaPulse, ứng dụng giúp cộng đồng theo dõi tình trạng sông và kênh đô thị.
> Một bức ảnh cùng những điều người dân quan sát được có thể trở thành tín hiệu để nhóm
> tình nguyện viên và chuyên gia kiểm tra. Trong video này, các báo cáo mẫu được mô phỏng để trình diễn.

### 0:20–0:55 · Trang chủ

Chỉ vào bản đồ, cuộn tới hộ chiếu dòng kênh và mở một cảnh báo.

> Trang chủ tập hợp các báo cáo theo vị trí và đoạn kênh. Mỗi cảnh báo cho biết những dấu hiệu
> đã được ghi nhận, bằng chứng, độ tin cậy và bước kiểm tra tiếp theo. Người xem có thể tìm
> ngay khu vực cần chú ý và hiểu vì sao hệ thống hiển thị cảnh báo.

### 0:55–1:55 · Gửi quan sát

Chọn ảnh, chọn nhóm sông/kênh và trả lời theo những gì thực sự quan sát được.
Đợi kết quả phân tích, chỉ vào các chỉ số và phần giải thích. Đổi VI → EN để minh họa kết quả được giữ lại.
Nếu gửi báo cáo, dùng vị trí của ảnh hoặc nhập tay; vị trí hiện tại chỉ phù hợp khi ảnh chụp tại chỗ.

> Người dân chọn một bức ảnh và bổ sung thông tin như màu nước, mùi, bọt hay rác nổi.
> Model Kimi hỗ trợ mô tả bối cảnh ảnh, còn hệ thống kết hợp thông tin để hiển thị rủi ro,
> tình trạng sinh thái và độ tin cậy. Người dùng cũng có thể đổi giữa tiếng Việt và tiếng Anh
> để đọc kết quả. Những dấu hiệu cần kiểm tra sẽ được chuyển sang quy trình xác minh.

Chỉ nói đoạn về Kimi khi đang minh họa kết quả gọi API thật.
Với kết quả seed, nói: “Phần mô tả ảnh trong báo cáo mẫu này được mô phỏng.”

### 1:55–2:35 · Hộ chiếu đoạn kênh

Mở hộ chiếu Kênh Đôi – Kênh Tẻ, chỉ vào các chỉ số, lịch sử và bấm một câu hỏi nhanh.
Đọc các giá trị đang hiển thị; chúng thay đổi theo dữ liệu và thời gian.

> Các báo cáo được tập hợp thành hộ chiếu cho từng đoạn kênh. Ở đây có các chỉ số,
> lịch sử quan sát và phần giải thích bằng ngôn ngữ dễ hiểu. Mục hỏi nhanh giúp người dân
> tìm thông tin phù hợp với mối quan tâm của mình, dựa trên những dữ liệu hệ thống đang có.

### 2:35–3:10 · Nhiệm vụ và xác minh

Mở tab nhiệm vụ đã đăng nhập, chọn một báo cáo và xem ảnh gốc.
Chỉ vào nhãn cần chuyên gia và các nhiệm vụ cộng đồng.
Nếu thao tác kết luận, nói rõ đây là kịch bản mô phỏng.

> Các báo cáo cần kiểm tra được đưa vào hàng đợi. Tình nguyện viên nhận nhiệm vụ,
> bổ sung ảnh hiện trường và gửi kết quả; trường hợp cần chuyên môn được chuyển đến chuyên gia.
> Nhờ vậy, mỗi báo cáo có lịch sử xử lý để theo dõi.

### 3:10–3:40 · Dashboard

Chỉ vào biểu đồ theo ngày, tỷ lệ xác minh và phần so sánh trước/sau.

> Dashboard cho thấy hoạt động theo thời gian và kết quả của quy trình xác minh.
> Các ảnh và điểm số trước, sau xử lý giúp minh họa sự thay đổi ở những điểm đã được ghi nhận.
> Trong bản demo, phần này được tạo từ các hoạt động mẫu.

### 3:40–4:00 · Kết thúc

> AquaPulse kết nối quan sát của người dân với việc kiểm tra và theo dõi tại địa phương.
> Ứng dụng cho biết các dấu hiệu đang có và mức độ chắc chắn; để kết luận chất lượng nước,
> vẫn cần lấy mẫu và kiểm tra chuyên môn. Xin cảm ơn.

## Quay trên Windows

Khi cửa sổ trình duyệt đang được chọn:

1. Nhấn **Windows + G**, mở bảng Capture và kiểm tra micro đã bật.
2. Nhấn **Windows + Alt + R** để bắt đầu quay.
3. Thực hiện các bước trên và đọc lời thuyết trình. **Windows + Alt + M** bật/tắt micro trong lúc quay.
4. Nhấn **Windows + Alt + R** để dừng. Video MP4 nằm trong thư mục **Videos → Captures**.

Các phím tắt và vị trí lưu theo [hướng dẫn Microsoft](https://support.microsoft.com/en-us/accessibility/windows/use-a-screen-reader-to-record-your-screen-with-xbox-game-bar).

Di chuột chậm và dừng vài giây ở phần đang giải thích. Có thể cắt đoạn chờ phân tích ảnh
để giữ nhịp video; đọc lại lời kể cho đúng các số và trạng thái thực tế trên màn hình.
