# AquaPulse Vector Watch

*English version for the hackathon submission: [README.en.md](README.en.md).*

Bộ demo local đầy đủ với nhiều dữ liệu mẫu: [hướng dẫn chạy](docs/local-demo.md).

Phát hiện dấu hiệu môi trường → ước tính rủi ro → đề xuất xác minh. Hệ thống **không** chẩn
đoán bệnh, không khẳng định muỗi mang virus, không kết luận nước nhiễm khuẩn qua ảnh, và
không tự đề xuất phun hóa chất. Xem `GET /scope` hoặc [backend/app/domain.py](backend/app/domain.py).

## Chạy thử nhận diện

```bash
cd backend
python -m venv .venv
.venv/Scripts/Activate.ps1          # Windows PowerShell; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8008
```

Các trang:

| Trang | Dành cho |
|---|---|
| `/` | Trang chủ: số quan sát hôm nay, cảnh báo đang mở, bản đồ điểm, thông báo, điểm thưởng |
| `/report` | Gửi quan sát theo 4 bước: (1) ảnh, (2) câu hỏi theo nhóm, (3) vị trí và thời gian, (4) gửi. Bước 1 chọn kiểu ảnh: **vật chứa, nước đọng** (chạy YOLO11n + model nước + AI mô tả) hoặc **mặt nước, dấu hiệu khác** (chỉ AI mô tả). Cột phải là kết quả AI: mức, độ tin cậy, câu AI hỏi lại. Sau khi gửi có nút "Tham gia xác minh" và "Đánh dấu thông tin sai" |
| `/tasks-board` | Nhiệm vụ cộng đồng; tình nguyện viên và chuyên gia đăng nhập bằng token để xác minh, gửi ảnh trước/sau, đóng cảnh báo, tạo nhiệm vụ |
| `/dashboard` | Chuyên gia: chỉ số, báo cáo mỗi ngày, trước/sau xử lý, khu vực cần chú ý, bản đồ 4 lớp |

Kịch bản demo 3–5 phút với số liệu thật: [docs/demo-script.md](docs/demo-script.md)
(bản tiếng Anh: [docs/demo-script.en.md](docs/demo-script.en.md)).

Giao diện có hai ngôn ngữ: nút **VI | EN** trên thanh trên cùng đổi cả trang, kể cả những câu do máy chủ
sinh ra (giải thích hộ chiếu, cảnh báo, câu trả lời hỏi nhanh). Thêm `?lang=en` vào bất kỳ đường dẫn nào
cũng mở trang bằng tiếng Anh; API nhận `?lang=en` cho mọi endpoint trả JSON (trừ `/fhir/*`, giữ nguyên
ngôn ngữ của bản ghi). Model mô tả ảnh cũng được hỏi bằng ngôn ngữ đang xem, nên câu mô tả của nó trả về
tiếng Anh khi trang ở chế độ EN (kết quả được đệm riêng theo từng ngôn ngữ). Xem [backend/app/i18n.py](backend/app/i18n.py) và
[backend/app/static/i18n.js](backend/app/static/i18n.js).

### Sông, kênh: "trạm y tế cho sông đô thị"

- **Form "Sông, kênh"** (mặc định ở `/report`): mục tiêu quan sát (môi trường, sức khỏe trẻ em, ngập, đa dạng
  sinh học) và 7 dấu hiệu nhìn, ngửi được: màu, mùi, bọt, váng dầu, rác nổi, cá/tôm/côn trùng sống, cá chết.
- **Hai kiểu phân tích ảnh** (`with_detector` trên `POST /detect` và `POST /observations`):
  vật chứa đọng nước thì chạy YOLO11n và model vùng nước; mặt nước sông, kênh, rác nổi, váng dầu thì không chạy
  hai model đó vì chúng chưa được huấn luyện cho cảnh này, chỉ dùng model mô tả và câu trả lời của người dân.
  Khi model không chạy, hệ thống ghi rõ "chưa nhìn" chứ không tính là "đã nhìn và không thấy": nguồn đó bị loại
  khỏi mẫu số độ tin cậy thay vì bỏ phiếu "không có".
- **Ba chỉ số tách riêng** cho mỗi quan sát: Risk (dấu hiệu ô nhiễm), Eco (tình trạng sinh thái, 1 = trông khỏe),
  Human-health (trẻ em, tiếp xúc nước, mùi), cạnh độ tin cậy.
- **Chưa xác minh thì tối đa mức vàng**: tình nguyện viên xác nhận tại hiện trường thì cảnh báo lên cam, mức đỏ
  chỉ do chuyên gia. Khi model ảnh thấy dấu hiệu người báo chưa nói, app hỏi lại kèm %.
- **Cảnh báo có bằng chứng**: điều gì xảy ra, bằng chứng, độ tin cậy (ảnh đêm tính thấp hơn), ai xác minh,
  người dân nên làm gì.
- **Đoạn kênh và hộ chiếu rủi ro**: 8 tuyến kênh rạch TP.HCM, 35 đoạn (Nhiêu Lộc – Thị Nghè, Tàu Hủ – Bến Nghé,
  Kênh Đôi – Kênh Tẻ, Tham Lương, Bến Cát, Nước Lên, Lò Gốm, sông Sài Gòn). Đường kênh lấy từ OpenStreetMap bằng
  `python backend/scripts/build_waterways.py`, lưu trong `db/data/*.geojson`, nạp lúc khởi động.
  `GET /waterways`, `GET /waterways/{id}/passport`, trang `/passport?segment=…`: Eco, Risk, Tin cậy,
  Xu hướng, Sức khỏe người, câu giải thích, lịch sử, mưa đo được (Open-Meteo), sinh vật, cộng đồng, cảnh báo.
  Trong OSM, tuyến Tham Lương – Bến Cát – Nước Lên là ba khúc rời nhau (các đoạn nối chưa có tên), nên giữ
  thành ba tuyến riêng thay vì vẽ một đường xuyên qua đất liền.
- **Hỏi nhanh** (`GET /translator?question=children|odor|after_rain|biodiversity`): câu trả lời dựng bằng luật,
  luôn kèm dữ liệu đang dùng, mức chắc chắn, điều chưa biết, khuyến nghị không mang tính y tế.
- **FHIR R4**: `GET /fhir/Observation/{id}`, `GET /fhir/waterways/{id}` (Bundle: Location, RiskAssessment,
  Observation; không kèm mã người báo).
- **Dữ liệu mẫu**: `python backend/scripts/seed_river_demo.py [--verify]`; trang chỉ hiện khi mở kèm `?demo=1`.
  Ảnh mẫu là ảnh vẽ đóng chữ "ẢNH MẪU DEMO", phần AI trên ảnh mẫu là mô phỏng.

### Model mô tả bối cảnh (Kimi API)

Phần mô tả bối cảnh dùng `kimi-k3` qua API tương thích OpenAI của Alibaba Model Studio.
Sao chép `.env.example` thành `.env`, rồi đổi cấu hình sau và điền API key thật trên máy chạy backend:

```dotenv
AQUAPULSE_VISION_ENABLED=1
AQUAPULSE_VISION_PROVIDER=kimi
DASHSCOPE_API_KEY=your-model-studio-api-key
KIMI_MODEL=kimi-k3
KIMI_BASE_URL=https://ws-ojz5frpqw24ibm8d.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
```

Khởi động lại backend sau khi đổi `.env`. Khi đã cấu hình key, app tự gọi phần mô tả ảnh;
không cần bật bằng checkbox. Ảnh được làm mờ khuôn mặt, thu nhỏ và mã hóa lại trước khi gửi
tới dịch vụ bên ngoài. Kimi mô tả dấu hiệu nhìn thấy; điểm rủi ro và yêu cầu xác minh do backend tính.
Không commit `.env`. Nếu không có key, backend không tải client Kimi.
Các adapter Qwen qua Ollama và Gemini vẫn có trong code, được chọn bằng `AQUAPULSE_VISION_PROVIDER`.

Model mặc định là `ml/runs/n_clean/weights/best.onnx`. Đổi bằng biến môi trường
`AQUAPULSE_DETECTOR_MODEL`. Backend chạy model bằng `onnxruntime`, không cần PyTorch.

### Database và điểm nóng (PostGIS)

```bash
docker compose up -d db                            # PostgreSQL 18 + PostGIS 3.6, chỉ mở ở localhost
cd backend && python scripts/seed_demo.py --clear  # tùy chọn: dữ liệu demo, gắn cờ is_demo
```

Backend tự chạy migration trong `db/migrations/` khi khởi động. Không có database thì
`/detect` vẫn chạy, còn `/observations` và `/hotspots` trả 503.

- `POST /observations`: kiểm tra vị trí, thời gian, chất lượng ảnh; chấm điểm; **chỉ lưu khi ảnh dùng được**.
  Ảnh được mã hoá lại nên không còn EXIF/GPS trên đĩa.
- `GET /hotspots?hours=72&radius_m=500&min_reports=3&min_reporters=2&category=vector`
  (thêm `include_demo=true` để thấy dữ liệu demo). Dùng DBSCAN của PostGIS; đã đối chiếu với
  DBSCAN của scikit-learn trong kế hoạch: cùng cụm, cùng điểm lẻ.
- `GET /trends?days=7&category=vector[&latitude=..&longitude=..&radius_m=1000]`: tuần này so với
  tuần trước, kèm chuỗi số theo ngày (giờ Việt Nam) để vẽ biểu đồ.

### Module Vector Watch và dashboard

Các nhóm sinh vật và chỉ thị (muỗi Aedes/Culex, ruồi, nước bất thường, chuột, xác động vật, ốc,
và nhóm tầng C chỉ ghi nhận), mỗi nhóm có form, luật điểm, người xác minh và giới hạn riêng.
Xem [docs/vector-watch.md](docs/vector-watch.md).

- `GET /vector-watch/catalog`: danh mục nhóm và câu hỏi của từng nhóm (form đọc từ đây).
- `http://127.0.0.1:8008/dashboard`: bản đồ 4 lớp, điểm nóng theo lớp, bảng tổng hợp.
- `POST /verification/tasks/{id}/photos`: ảnh trước/sau xử lý; ảnh sau được chấm lại.

### Xác minh bởi con người (mục 16)

Mỗi báo cáo được điều phối sau khi chấm điểm (`review` trong kết quả):

1. Có trường hợp bắt buộc xác minh (lăng quăng, váng dầu, xác động vật, mùi hóa chất,
   mức cam/đỏ, C < 0,60, hai model mâu thuẫn) → **hàng đợi xác minh**, bất kể độ tin cậy.
2. Người báo mâu thuẫn với AI, thiếu dữ liệu, hoặc C ≤ 0,85 → **nhờ người báo xác nhận**
   (`POST /observations/{id}/confirm`), rồi chấm và điều phối lại.
3. Còn lại → **hiển thị kết quả sơ bộ**.

Tài khoản xác minh đặt trong `.env` (`AQUAPULSE_REVIEWERS`, xem `.env.example`), gọi API với
`Authorization: Bearer <token>`:

- `GET /verification/tasks`, `POST /verification/tasks/{id}/claim`
- `POST /verification/tasks/{id}/submit` (tình nguyện viên: `confirmed | not_confirmed | unclear`)
- `POST /verification/tasks/{id}/resolve` (chuyên gia: kết luận cuối)
- `GET /verification/tasks/{id}/events` (nhật ký ai quyết định gì)

Không ai xác minh được báo cáo của chính mình. Mức tin cậy của người báo do server tính từ
số báo cáo đã được xác minh, không lấy theo lời khai của người báo.

### Cảnh báo, nhiệm vụ cộng đồng, điểm thưởng, thông báo (mục 17–21)

- **Cảnh báo** là điểm nóng được theo dõi theo thời gian: sau mỗi báo cáo và mỗi kết luận xác minh,
  điểm nóng được so với cảnh báo cùng loại trong 300 m; có thì cập nhật, không thì mở cảnh báo mới.
  Mức cảnh báo là mức cao nhất trong các báo cáo của nó. `GET /alerts`,
  `POST /alerts/{id}/verify` (chuyên gia: `verified | resolved | dismissed`).
- **Thông báo** (`GET /notifications?latitude=..&longitude=..` hoặc `?reporter_id=..`): cảnh báo mới,
  tăng mức, đã xử lý, điểm cần xác minh gần bạn, kết quả xác minh báo cáo của bạn. Câu chữ cố định,
  bình tĩnh; câu nào có "ổ dịch", "dịch … bùng phát" bị chặn trước khi lưu. Chưa có push/Zalo/SMS.
- **Điểm thưởng** (ghi sổ, mỗi hành động chỉ cộng một lần): +10 báo cáo có ảnh và GPS, không trùng,
  tối đa 5 lần mỗi ngày; +20 khi báo cáo được xác minh là đúng; +5 kiểm tra báo cáo của người khác;
  +15 ảnh sau xử lý; phần thưởng của nhiệm vụ khi hoàn thành. 5 huy hiệu tính từ báo cáo đã xác minh.
  `GET /community/profile/{id}`, `GET /community/leaderboard` (mã người được che).
- **Nhiệm vụ cộng đồng**: chuyên gia tạo (`POST /tasks`), ai cũng xem (`GET /tasks`); hoàn thành
  (`POST /tasks/{id}/complete`) khi người làm đã gửi ảnh sau xử lý cho đủ số điểm trong bán kính.
- **Chỉ số** `GET /dashboard/metrics?days=14`: tổng báo cáo, đã xác minh và tỷ lệ, cảnh báo đang mở,
  thời gian phản hồi (lúc xác minh − lúc nhận), tỷ lệ xử lý điểm nóng, giảm rủi ro trước/sau, báo cáo
  sau mưa, chuỗi theo ngày.
- `GET /map/points`: GeoJSON cho bản đồ công khai. `GET /observations/{id}`: xem một báo cáo.
  `POST /observations/{id}/feedback`: "Đánh dấu thông tin sai", lưu làm nhãn và đưa báo cáo đi xác minh.
  `POST /observations/{id}/analyze` (người xác minh): chạy lại model trên ảnh đã lưu.

Giao diện không lấy dữ liệu demo (dữ liệu demo vẫn nằm trong database cho `seed_demo.py`; API chỉ trả
khi gọi kèm `include_demo=true`).

### Dữ liệu của dự án OneAquaHealth

AquaPulse đọc API mở của chính dự án (`https://api.enora-oah.eu/api`, dùng bởi Resilience Map):

| Lấy gì | Dùng để làm gì |
|---|---|
| 5 thành phố thí điểm, 106 điểm quan trắc | Lớp bản đồ và danh sách trên trang chủ |
| 69 điểm do người dân tạo trong **Citizen Science App** | Cùng lớp bản đồ, ghi rõ nguồn từ app của dự án |
| Chỉ số rủi ro sức khỏe (mầm bệnh, ô nhiễm từ phân, gen kháng kháng sinh) | Hiển thị kèm ngày lấy mẫu và câu giải thích |
| Thông số đô thị 500 m, nitrat, thời tiết đo được | Bối cảnh cho từng điểm quan trắc |

- **Ranh giới rõ ràng:** số của họ là số đo phòng thí nghiệm, chỉ được hiển thị, **không trộn** vào điểm rủi ro,
  điểm nóng hay cảnh báo tính từ quan sát của người dân. Báo cáo của người dân chỉ được *liên kết* tới điểm
  quan trắc gần nhất kèm khoảng cách.
- `GET /oneaqua/cities`, `GET /oneaqua/sites[?city=CO&kind=research|citizen]`, `GET /oneaqua/sites/{code}`,
  `POST /oneaqua/sync` (chuyên gia). Server tự đồng bộ lúc khởi động và mỗi `AQUAPULSE_OAH_SYNC_HOURS` giờ
  (mặc định 24, `0` = tắt).

### Báo chí nói gì về kênh rạch (từ 01/01/2026)

Bộ nhập tin từ Google News RSS (`backend/app/press.py`): tiêu đề, nguồn, ngày, link; ghép tên kênh trong tiêu đề
vào tuyến của mình và gắn thẻ đơn giản (rác, nước đen, mùi hôi, cá chết, ngập, cải tạo, nước thải).

- Hiện trên trang hộ chiếu của từng tuyến; `GET /press?waterway=…`, `POST /press/sync` (chuyên gia).
  Server tự đồng bộ mỗi `AQUAPULSE_PRESS_SYNC_HOURS` giờ (mặc định 24, `0` = tắt); đổi mốc thời gian bằng
  `AQUAPULSE_PRESS_SINCE`.
- **Bài báo là tham khảo, không phải số đo**: không vào điểm rủi ro, điểm nóng, cảnh báo hay số liệu dashboard.
  Chỉ lưu tiêu đề, nguồn, ngày, link như một mục lục tin, không lưu nội dung bài.
- Một số tuyến báo chí hay nhắc (Xuyên Tâm, Văn Thánh, 19/5, Bà Lớn) chưa có đường kênh trong `db/data`, vẫn
  được giữ theo tên riêng.

### Quyền riêng tư (mục 22)

- Khuôn mặt được làm mờ (YuNet, `backend/models/`) trước khi ảnh được lưu hoặc gửi tới dịch vụ mô tả ảnh bên ngoài, như Kimi API.
  **Biển số xe chưa được làm mờ**: chưa có model phát hiện biển số Việt Nam dùng được.
- Ảnh được mã hoá lại, không còn EXIF/GPS của điện thoại. Ảnh đã lưu chỉ người xác minh xem được.
- Bản đồ và API công khai làm tròn vị trí khoảng 100 m, không trả `reporter_id`; bảng xếp hạng che mã.
- Người dân dùng mã ẩn danh sinh trên máy (`localStorage`), không cần tên hay số điện thoại.

### Triển khai (mục 23)

```bash
docker build -t aquapulse-api .          # từ thư mục gốc của repo
docker run -p 8000:8000 -e DATABASE_URL=... -e AQUAPULSE_REVIEWERS=...   -v aquapulse-photos:/data/photos aquapulse-api
```

- Repo có sẵn hai model ONNX dùng để suy luận và model làm mờ khuôn mặt YuNet, nên bản clone
  có đủ file model để build Docker. Checkpoint huấn luyện, dataset, ảnh và video local không được đưa lên.
  Xem [nguồn gốc model](ml/runs/README.md). Image chạy bằng user thường, không chứa `.env`.
- Database: PostgreSQL có PostGIS (Supabase hoặc Render Postgres bật extension). Backend tự chạy migration.
- Ảnh lưu ở `/data/photos`: cần gắn ổ đĩa bền (Render disk, volume). Chưa lưu lên Supabase Storage.
- Biến môi trường: xem [.env.example](.env.example), chỉ có tên biến và ví dụ không bí mật.
  **Không đưa khoá API hay token lên GitHub**; đặt chúng trong phần cấu hình secret của nơi triển khai.
  `SUPABASE_URL`, `SUPABASE_KEY`, `STORAGE_BUCKET`, `JWT_SECRET` trong kế hoạch chưa được code dùng.

## Dữ liệu và huấn luyện

```bash
python ml/prepare_vistext.py           # data/raw/vistext-mosquito -> data/{images,labels}
docker build -t aquapulse-ml ml        # ảnh Docker có PyTorch CUDA + Ultralytics
docker run -d --name aquapulse-train --gpus all --shm-size=4g \
  -v "$PWD:/workspace" aquapulse-ml bash /workspace/ml/train_all.sh
```

Huấn luyện chạy trong Docker vì Smart App Control trên Windows 11 chặn các DLL chưa ký số
của PyTorch. Container Linux không bị ảnh hưởng và vẫn dùng được GPU.

Kết quả đánh giá (`ml/runs/<tên>/eval/report.json`) ghi ngưỡng confidence chọn trên tập val,
precision/recall từng lớp, recall theo ảnh và độ hiệu chuẩn confidence.

## Kiểm thử

```bash
backend/.venv/Scripts/python.exe -m pytest backend    # cần docker compose up -d db cho test PostGIS
python -m pytest ml/tests                             # 22 test
python -m ruff check .
```

Trước buổi demo, chạy thử toàn bộ chức năng trên máy chủ đang chạy:

```bash
cd backend
python -m uvicorn app.main:app --port 8010   # cửa sổ khác
python scripts/demo_check.py
```

Script đi hết kịch bản demo (trang chủ, cảnh báo có bằng chứng, hộ chiếu hai ngôn ngữ, hỏi nhanh,
tình nguyện viên xác minh làm cảnh báo lên cam, ảnh thật qua model, OneAquaHealth, báo chí, điểm
thưởng, FHIR), in một dòng PASS/FAIL cho từng chức năng và tự xoá dữ liệu nó tạo ra. Ảnh chụp từng
cảnh: [docs/demo-frames/](docs/demo-frames/).

## Giấy phép và nguồn dữ liệu

- Model huấn luyện bằng Ultralytics YOLO11, giấy phép **AGPL-3.0**. Nếu chạy phục vụ người
  dùng, nhóm phải công bố mã nguồn hoặc mua giấy phép Enterprise.
- Ảnh huấn luyện từ [VisText-Mosquito](https://data.mendeley.com/datasets/rtsfh7jh7p/2)
  (CC BY 4.0). Nguồn từng ảnh ghi trong `data/sources.csv`; ảnh bị loại và lý do ghi trong
  `data/excluded.csv`.
