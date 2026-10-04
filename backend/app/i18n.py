"""English for an API that thinks in Vietnamese.

AquaPulse is written for the people who live along the canals, so every label, question
and generated sentence is Vietnamese. The judges of the hackathon, and anyone outside
Vietnam, need the same screens in English.

Rather than duplicate every sentence builder, the translation happens once, at the API
boundary: `localize(payload, "en")` walks the JSON a route is about to return and swaps
the strings it recognises. Two kinds of string are recognised:

* fixed labels, options, notes and disclaimers -> PHRASES, matched exactly;
* sentences built around numbers -> PATTERNS, matched by regular expression.

Anything unrecognised is returned as it is: an untranslated Vietnamese sentence is a gap
to fill, never a broken one. tests/test_i18n.py walks the English payloads of the pages a
reader sees and fails when Vietnamese is left in them.

Proper names (a canal, a city, a headline, an OneAquaHealth site) are never translated;
SKIP_KEYS lists the fields that hold them.
"""
# ruff: noqa: RUF001 - Vietnamese text uses the en dash and its own quotation marks

from __future__ import annotations

import re
from typing import Any

DEFAULT = "vi"
LANGS = ("vi", "en")

# Fields that hold a name, an identifier or foreign text: never translated.
SKIP_KEYS = frozenset({
    "id", "code", "url", "waterway", "title", "city_name", "user", "reporter_id", "segment_id",
    "day", "date", "sampled_on", "observed_at", "created_at", "published_at", "query", "provider",
    "model", "geometry",
})
# Machine codes ("open", "yellow", "river_health") travel in other fields; they are ASCII, and
# every entry below is keyed by Vietnamese, so they pass through the walk untouched.


def normalize(lang: str | None) -> str:
    """Accepts "en", "EN", "en-GB"; anything else means Vietnamese."""
    code = (lang or DEFAULT).strip().lower()[:2]
    return code if code in LANGS else DEFAULT


# --- fixed strings -----------------------------------------------------------------------
PHRASES: dict[str, str] = {
    # levels, confidence, trends, status
    "Xanh": "Green", "Vàng": "Yellow", "Cam": "Orange", "Đỏ": "Red",
    "cao": "high", "trung bình": "medium", "thấp": "low", "chưa có": "not available",
    "Cao": "High", "Trung bình": "Medium", "Thấp": "Low", "Chưa có": "Not available",
    "Tăng rõ": "Clearly rising", "Có thể đang tăng, chưa chắc": "Possibly rising, not certain",
    "Giảm rõ": "Clearly falling", "Ổn định": "Steady", "Chưa đủ dữ liệu": "Not enough data",
    "chưa đủ dữ liệu": "not enough data",
    "Chưa xác minh": "Not verified", "Đã xác minh": "Verified", "Đang chờ xác minh": "Waiting for verification",
    "Chờ người gửi xác nhận": "Waiting for the reporter to confirm", "Đang mở": "Open",
    "Đã xác nhận": "Confirmed", "Đã xử lý": "Resolved", "Đã đóng": "Closed",
    # observation status, as the map and the dashboard word it
    "Đã kiểm tra, không đúng": "Checked, not correct",
    "Đang xử lý": "Being handled", "Cần xác minh": "Needs verification",
    "Chờ người báo xác nhận": "Waiting for the reporter", "Theo dõi": "Watch",
    "Chờ xử lý": "Waiting to be handled",
    # what the detector can outline
    "Lốp xe cũ": "Old tyre", "Chai, vật chứa nhựa": "Bottles and plastic containers",
    "Chưa kiểm chứng: tập test chỉ có 3 lốp xe chụp thật.":
        "Unverified: the test set holds only 3 real photos of a tyre.",
    "Vỏ dừa": "Coconut shell", "Miệng cống": "Drain mouth",
    "Vật chứa nước": "Water container",
    # signals and categories
    "váng dầu": "oil sheen", "bọt": "foam", "mùi lạ": "unusual odour", "nước đổi màu": "discoloured water",
    "rác nổi": "floating litter", "cá chết": "dead fish", "nước đọng": "standing water",
    "vật chứa": "container", "lốp xe": "tyre", "rác hữu cơ": "organic waste",
    "nghi có lăng quăng": "suspected larvae", "ruồi tập trung": "fly cluster",
    "xác động vật": "dead animal", "nước bất thường": "unusual water",
    "nước đọng, điều kiện muỗi sinh sản": "standing water, mosquito breeding conditions",
    "ruồi, rác hữu cơ, vệ sinh": "flies, organic waste, sanitation",
    "Sông, kênh: mặt nước, bờ, rác nổi": "Rivers and canals: water surface, banks, floating litter",
    # press tags
    "rác": "litter", "nước đen": "black water", "mùi hôi": "bad smell", "ngập": "flooding",
    "cải tạo": "rehabilitation works", "nước thải": "wastewater", "Không nêu tên tuyến": "No waterway named",
    # alert verifier and advice
    "Cần nhóm tình nguyện viên xác minh tại hiện trường":
        "A volunteer team needs to verify this on site",
    "Cần chuyên gia môi trường lấy mẫu": "An environmental expert needs to take samples",
    "Cần chuyên gia xem": "An expert needs to review this",
    "Cần tình nguyện viên xác minh": "A volunteer needs to verify this",
    "Tránh tiếp xúc trực tiếp với nước cho đến khi có kết quả kiểm tra.":
        "Avoid direct contact with the water until test results are in.",
    "Đổ bỏ nước đọng, úp ngược hoặc đậy kín vật chứa quanh nhà.":
        "Empty standing water and turn over or cover containers around the house.",
    "Không chạm tay trần vào rác hay xác động vật; báo tổ dân phố hoặc đơn vị vệ sinh môi trường.":
        "Do not touch litter or dead animals with bare hands; tell your neighbourhood group or the "
        "sanitation service.",
    "Theo dõi và báo thêm nếu thấy thay đổi.": "Keep watching and report again if things change.",
    # notifications
    "Hệ thống chưa kết luận có muỗi truyền bệnh.":
        "The system has not concluded that disease-carrying mosquitoes are present.",
    "Hệ thống chưa kết luận về tác nhân gây bệnh.":
        "The system has not concluded anything about a disease agent.",
    "Hệ thống chưa kết luận nước bị nhiễm khuẩn hay độc tố.":
        "The system has not concluded that the water carries bacteria or toxins.",
    "Bạn có thể tham gia xác minh điểm này.": "You can help verify this point.",
    ", phần lớn ảnh chụp ban đêm": ", most photos were taken at night",
    "Có một điểm cần xác minh gần bạn. Bạn có thể nhận nhiệm vụ kiểm tra tại chỗ.":
        "A point near you needs verification. You can take on a field check.",
    # what a report is told about its group (app/vector_watch.py)
    "Có dấu hiệu bất thường trên mặt nước; cần xác minh tại hiện trường. Tránh tiếp xúc trực tiếp với "
    "nước cho đến khi có kết quả kiểm tra.":
        "There are unusual signs on the water; this needs verification on site. Avoid direct contact "
        "with the water until test results are in.",
    "Chưa thấy dấu hiệu bất thường rõ ở đoạn sông, kênh này.":
        "No clear unusual signs on this stretch of river or canal.",
    "Có điều kiện phù hợp cho muỗi sinh sản: nước đọng trong vật chứa. Nên đổ bỏ hoặc đậy kín.":
        "Conditions suit mosquito breeding: water standing in a container. Empty it or cover it.",
    "Chưa thấy điều kiện đáng kể cho muỗi sinh sản.":
        "No meaningful mosquito-breeding conditions seen.",
    "Nghi ngờ có hoạt động của côn trùng gần điểm nước đọng; cần người xác minh.":
        "Insect activity is suspected near the standing water; a person needs to verify it.",
    "Đã ghi nhận báo cáo côn trùng; cần người xác minh.":
        "An insect report was recorded; a person needs to verify it.",
    "Có dấu hiệu tập trung ruồi gần nguồn rác hữu cơ; cần kiểm tra vệ sinh môi trường.":
        "Flies are gathering near organic waste; the sanitation of the area needs checking.",
    "Chưa thấy dấu hiệu tập trung ruồi đáng kể.": "No meaningful fly cluster seen.",
    "Có dấu hiệu bất thường trên bề mặt nước; cần lấy mẫu hoặc xác minh chuyên môn.":
        "There are unusual signs on the water surface; sampling or expert verification is needed.",
    "Chưa thấy dấu hiệu bất thường rõ trên mặt nước.": "No clear unusual signs on the water surface.",
    "Có nước tù, rác hữu cơ hoặc cống tắc: điều kiện phù hợp cho muỗi Culex. Cần khơi thông, dọn rác.":
        "Stagnant water, organic waste or a blocked drain: conditions that suit Culex mosquitoes. Clear "
        "the drain and remove the waste.",
    "Chưa thấy điều kiện đáng kể cho muỗi Culex.": "No meaningful Culex conditions seen.",
    "Ghi nhận chuột gần khu vực; cần cộng đồng xác minh và xử lý nguồn thức ăn, nơi trú.":
        "Rats were reported nearby; the community needs to verify it and deal with the food and shelter "
        "they find there.",
    "Đã ghi nhận báo cáo chuột; cần cộng đồng xác minh.":
        "A rat report was recorded; the community needs to verify it.",
    "Ghi nhận xác động vật; không chạm tay trần, báo đơn vị vệ sinh môi trường.":
        "A dead animal was reported; do not touch it with bare hands, tell the sanitation service.",
    "Ghi nhận ốc hoặc sinh vật nước; chuyên gia sẽ xác định loài.":
        "A snail or aquatic creature was reported; an expert will identify the species.",
    "Đã ghi nhận để chuyên gia tham khảo; hệ thống không đánh giá tự động nhóm này.":
        "Recorded for an expert to look at; the system does not score this group automatically.",
    "Chưa đủ câu trả lời để đánh giá mặt nước; hãy trả lời màu, mùi, váng dầu, rác nổi và cá, tôm có "
    "sống không.":
        "Too few answers to judge the water; please answer about colour, odour, oil sheen, floating "
        "litter, and whether fish and shrimp are alive.",
    "Chưa đủ dữ liệu cho điểm nhóm này; nên hỏi thêm người báo.":
        "Too little data for this group's score; the reporter should be asked for more.",
    "Không có nước đọng: tối đa 0,3 (vật chứa khô có thể đọng nước sau mưa).":
        "No standing water: 0.3 at most (a dry container can fill after rain).",
    "Nước đọng trong lốp xe: +0,15.": "Water standing in a tyre: +0.15.",
    "Nước đọng trên 7 ngày, đủ một vòng đời muỗi: +0,10.":
        "Water standing for more than 7 days, a full mosquito life cycle: +0.10.",
    "Mục tiêu sức khỏe trẻ em: nếu có dấu hiệu bất thường, không để trẻ chơi hay lội nước.":
        "Children's-health goal: where there are unusual signs, keep children from playing or wading.",
    "Mục tiêu ngập lụt: ghi nhận để xem cùng lượng mưa của khu vực.":
        "Flooding goal: recorded to be read together with the area's rainfall.",
    "Mục tiêu đa dạng sinh học: ghi nhận cá, tôm, côn trùng sống giúp theo dõi sinh thái của đoạn kênh.":
        "Biodiversity goal: recording live fish, shrimp and insects helps follow the ecology of the "
        "stretch.",
    # risk components and what is missing from the formula (app/risk.py)
    "Bất thường môi trường": "Environmental anomaly",
    "Nguy cơ sinh sản vector": "Vector breeding risk",
    "Gần khu dân cư": "Near housing", "Thời tiết, mưa": "Weather and rain",
    "Tiếp xúc người, vật nuôi": "Contact with people or pets",
    "Gần nhà ở": "Near housing", "Gần trường học": "Near a school",
    "Gần khu vui chơi": "Near a playground",
    "Không mưa gần đây": "No rain recently", "Không tiếp xúc": "No contact",
    "Trẻ em chơi gần đó": "Children playing nearby",
    "Người hoặc vật nuôi tiếp xúc trực tiếp": "People or pets in direct contact",
    # why a component scored what it did
    "Không thấy dấu hiệu bất thường môi trường.": "No environmental anomaly seen.",
    "Chưa nguồn nào quan sát được rác, váng dầu, bọt hay xác động vật.":
        "No source observed litter, oil sheen, foam or a dead animal.",
    "Không thấy nước đọng hay vật chứa.": "No standing water and no container seen.",
    "Có vật chứa có thể đọng nước sau mưa.": "There is a container that could hold water after rain.",
    "Có nước đọng.": "There is standing water.",
    "Nước đọng trong lốp xe.": "Water standing in a tyre.",
    "Nước đọng cạnh rác hữu cơ.": "Water standing next to organic waste.",
    "Nước đọng trong vật chứa nhân tạo.": "Water standing in a man-made container.",
    "Người báo chưa cho biết gần nơi nào.": "The reporter did not say what it is near.",
    "Người báo chưa cho biết có ai tiếp xúc không.":
        "The reporter did not say whether anyone touched the water.",
    "Chưa có dữ liệu mưa (chưa nối dịch vụ thời tiết).":
        "No rain data (no weather service connected here).",
    "Có báo cáo ấu trùng.": "Larvae were reported.",
    "Có báo cáo ấu trùng, bắt buộc xác minh.": "Larvae were reported; verification is required.",
    # what to do next
    "Đổ bỏ nước đọng, úp ngược hoặc đậy kín vật chứa.":
        "Empty the standing water and turn the container over or cover it.",
    "Thu gom lốp xe cũ, hoặc che để không đọng nước mưa.":
        "Collect the old tyres, or cover them so rain cannot collect.",
    "Kiểm tra các vật chứa quanh đó sau mỗi trận mưa.":
        "Check the containers around it after every rainfall.",
    "Thu gom rác hữu cơ, báo tổ dân phố nếu rác tồn đọng.":
        "Clear the organic waste; tell the neighbourhood group if it keeps piling up.",
    "Báo trạm y tế phường để cán bộ đến kiểm tra.":
        "Tell the ward health station so staff can come and check.",
    "Báo cơ quan môi trường địa phương để lấy mẫu kiểm tra.":
        "Tell the local environmental authority so they can take samples.",
    "Báo cơ quan môi trường địa phương để kiểm tra nguồn nước.":
        "Tell the local environmental authority so they can check the water source.",
    "Không chạm tay trần; báo đơn vị vệ sinh môi trường để xử lý.":
        "Do not touch it with bare hands; tell the sanitation service to deal with it.",
    # what the level means
    "Chuyển cơ quan chuyên môn, sau khi đã có người xác minh":
        "Hand to the responsible authority, once a person has verified it",
    "Xác minh và hành động cộng đồng": "Verify, then act as a community",
    "Cần thêm quan sát": "More observations needed",
    "Nghi ngờ, chưa kết luận: cần xác minh tại hiện trường trước khi nâng mức cảnh báo.":
        "Suspected, nothing concluded: someone must verify on site before the level is raised.",
    "Ngưỡng cho bản thử, không phải ngưỡng y tế chính thức.":
        "Pilot thresholds, not official health thresholds.",
    # routing reasons (app/review.py)
    "Nghi ngờ lăng quăng.": "Larvae are suspected.",
    "Váng dầu.": "An oil sheen.",
    "Váng dầu cần cơ quan môi trường lấy mẫu.":
        "An oil sheen needs the environmental authority to take samples.",
    "Xác động vật.": "A dead animal.",
    "Xác động vật cần đơn vị vệ sinh môi trường xử lý.":
        "A dead animal needs the sanitation service to deal with it.",
    "Nước có mùi hóa chất.": "The water smells of chemicals.",
    "Mùi hóa chất cần chuyên gia môi trường.":
        "A chemical smell needs an environmental expert.",
    "Mức đỏ chỉ chuyển cơ quan chuyên môn sau khi chuyên gia xem.":
        "Red only goes to the authority after an expert has looked at it.",
    "Độ tin cậy cao, không có dấu hiệu bắt buộc xác minh.":
        "High confidence, and no sign that forces verification.",
    "Tín hiệu nước bất thường cần chuyên gia hoặc phòng thí nghiệm lấy mẫu.":
        "Unusual water signals need an expert or a laboratory to take samples.",
    "Cần người báo xác nhận trước khi nâng cảnh báo":
        "The reporter must confirm before the alert is raised",
    "Mức rủi ro từ Cam trở lên.": "The risk level is orange or above.",
    "Lốp xe chỉ do model phát hiện, mà lớp lốp xe chưa được kiểm chứng.":
        "Only the model saw the tyre, and the tyre class is unverified.",
    # what the sources said (app/fusion.py)
    "Người báo chưa trả lời câu hỏi nhanh nào; chỉ dựa vào AI.":
        "The reporter answered none of the quick questions; this rests on the AI alone.",
    "Model mô tả bối cảnh không chạy; rác hữu cơ, váng dầu, bọt chỉ dựa vào người báo.":
        "The description model did not run; organic waste, oil sheen and foam rest on the reporter "
        "alone.",
    "Không chạy model nhận diện vật chứa cho ảnh này: nó chỉ được huấn luyện cho vật chứa đọng "
    "nước, không dùng cho mặt nước sông, kênh.":
        "The container detector did not run on this photo: it was trained on containers holding "
        "water, not on the surface of a river or canal.",
    # the vision model's own guard rails (app/vision.py)
    "Không xác định loài muỗi hay tác nhân gây bệnh. Không suy đoán về nước nhiễm khuẩn hoặc phun "
    "hóa chất.":
        "No mosquito species and no disease agent are identified. Nothing is guessed about "
        "contamination or about spraying chemicals.",
    "Phần giải thích của AI đã bị lọc vì vượt phạm vi cho phép.":
        "The AI's explanation was filtered out for going beyond what the system may say.",
    # what the photo may show, and how the app asks about it (app/pipeline.py)
    "rác, lá mục": "litter and rotting leaves",
    "bọt trên mặt nước": "foam on the water",
    "xác động vật hoặc cá chết": "a dead animal or dead fish",
    "Bạn có thấy ánh cầu vồng hoặc mùi xăng dầu không?":
        "Did you see a rainbow film, or smell fuel?",
    "Bọt có đọng thành mảng, không tan không?":
        "Did the foam sit in patches without dissolving?",
    "Bạn có thấy xác động vật hay cá chết không?":
        "Did you see a dead animal or dead fish?",
    "Bạn có thấy rác hoặc lá mục trong nước không?":
        "Did you see litter or rotting leaves in the water?",
    # the disclaimers every result carries
    "Mô hình chỉ khoanh vùng vật có thể đọng nước.":
        "The model only outlines objects that could hold water.",
    "Nó không xác định có nước, lăng quăng hay muỗi trong ảnh.":
        "It does not establish that there is water, larvae or mosquitoes in the photo.",
    "Kết quả là sàng lọc dấu hiệu môi trường, không phải chẩn đoán y tế hay kết quả xét nghiệm.":
        "This is environmental screening, not a medical diagnosis or a laboratory result.",
    "Cần người có thẩm quyền xác minh trước khi hành động.":
        "Someone with the authority to do so must verify it before anyone acts.",
    "Kết quả là sàng lọc dấu hiệu môi trường, không phải chẩn đoán y tế hay kết quả xét nghiệm. "
    "Cần người có thẩm quyền xác minh trước khi hành động.":
        "This is environmental screening, not a medical diagnosis or a laboratory result. Someone with "
        "the authority to do so must verify it before anyone acts.",
    "Mô hình chỉ khoanh vùng vật có thể đọng nước. Nó không xác định có nước, lăng quăng hay muỗi "
    "trong ảnh.":
        "The model only outlines objects that could hold water. It does not establish that there is "
        "water, larvae or mosquitoes in the photo.",
    "Model thị giác chỉ mô tả bối cảnh và giải thích. Nó không quyết định mức rủi ro; phần đó do rule "
    "engine và người xác minh.":
        "The vision model only describes and explains the scene. It does not decide the risk level; the "
        "rule engine and the human verifier do.",
    "Ảnh được phân tích ngay trên máy chủ này, không gửi ra ngoài.":
        "The photo is analysed on this server and never sent anywhere else.",
    "Ảnh được gửi tới dịch vụ bên ngoài để phân tích.":
        "The photo is sent to an external service for analysis.",
    "Model nước mới huấn luyện trên 89 ảnh (mask mAP50 0,51 trên tập test) và chỉ học nước trong vật "
    "chứa. Chỉ dùng làm bằng chứng hỗ trợ, không thay câu trả lời của người dân.":
        "The water model was trained on 89 images (mask mAP50 0.51 on the test set) and only learnt "
        "water inside containers. It is supporting evidence, never a replacement for what a resident "
        "answers.",
    "Ảnh này không chạy model nhận diện vật chứa: model chỉ được huấn luyện trên vật chứa có thể đọng "
    "nước. Mặt nước, rác nổi, váng dầu do model mô tả và người báo đánh giá.":
        "The container detector did not run on this photo: it was only trained on containers that can "
        "hold water. The water surface, floating litter and oil sheen are judged by the description "
        "model and the reporter.",
    # passport, translator, press notes
    "Chỉ số dựa trên quan sát của người dân và model ảnh; không phải kết quả xét nghiệm nước, "
    "không kết luận nước an toàn hay độc hại.":
        "The indices come from residents' observations and image models; they are not water test "
        "results and never state that the water is safe or toxic.",
    "Người dân ghi nhận có hoặc không thấy cá, tôm, côn trùng sống; chưa định danh loài.":
        "Residents record whether they saw live fish, shrimp or insects; no species were identified.",
    "Open-Meteo (số đo, không phải dự báo)": "Open-Meteo (measurements, not a forecast)",
    "Sau mưa lớn, ưu tiên kiểm tra cửa xả và đoạn có báo cáo váng, mùi.":
        "After heavy rain, check the outfalls first, then the stretches with reports of sheen or odour.",
    "Không để trẻ chơi, lội nước ở đoạn này cho tới khi có kết quả xác minh.":
        "Keep children from playing or wading in this stretch until verification comes back.",
    "Cần tình nguyện viên xác minh cảnh báo đang mở tại hiện trường.":
        "A volunteer is needed to verify the open alert on site.",
    "Chưa có kết quả xét nghiệm vi sinh, hóa chất hay độc tố: ảnh và câu trả lời không thay được xét nghiệm.":
        "There are no microbiological, chemical or toxin test results: photos and answers cannot "
        "replace laboratory testing.",
    "Chưa biết tình trạng ngoài các thời điểm có người quan sát.":
        "Nothing is known about the times when nobody was observing.",
    "Chưa định danh loài; 'có thấy sinh vật sống' là ghi nhận bằng mắt của người dân.":
        "No species identification; \"saw living creatures\" is what residents saw with their own eyes.",
    "Thông tin sàng lọc môi trường, không phải khuyến nghị y tế. Khi có triệu chứng, hãy hỏi cơ sở y tế.":
        "Environmental screening information, not medical advice. If you have symptoms, ask a health "
        "service.",
    "Lượng mưa đo được theo ngày (Open-Meteo)": "Measured daily rainfall (Open-Meteo)",
    "Rửa tay bằng xà phòng sau khi chơi gần kênh; không để trẻ chạm vào rác nổi.":
        "Wash hands with soap after playing near the canal; keep children away from floating litter.",
    "Đóng cửa sổ hướng ra kênh lúc mùi nặng; báo thêm quan sát để hệ thống biết mùi kéo dài bao lâu.":
        "Close windows facing the canal when the smell is strong; send more observations so the system "
        "learns how long it lasts.",
    "Kiểm tra cửa xả cống và đoạn có báo cáo váng, mùi trước; chụp ảnh ban ngày để độ tin cậy cao hơn.":
        "Check the sewer outfalls and the stretches with sheen or odour reports first; photograph in "
        "daylight for higher confidence.",
    "Cần khảo sát sinh học của chuyên gia để kết luận về đa dạng sinh học.":
        "A biologist's survey is needed before anything can be concluded about biodiversity.",
    "Chưa có ai trả lời câu hỏi về cá, tôm, côn trùng sống ở các đoạn kênh.":
        "Nobody has answered the question about live fish, shrimp or insects on any stretch yet.",
    "Khi gửi quan sát, chọn mục tiêu 'Đa dạng sinh học' và trả lời có thấy sinh vật sống không.":
        "When sending an observation, pick the \"Biodiversity\" goal and say whether you saw living "
        "creatures.",
    "Bài báo là thông tin tham khảo, không phải số đo: không dùng để tính điểm rủi ro, điểm nóng hay "
    "cảnh báo. Nguồn: Google News RSS.":
        "Press articles are context, not measurement: they never enter a risk score, a hotspot or an "
        "alert. Source: Google News RSS.",
    "Số liệu do OneAquaHealth đo và công bố. AquaPulse chỉ hiển thị, không tính lại, không trộn vào "
    "điểm rủi ro từ quan sát của người dân.":
        "Figures measured and published by OneAquaHealth. AquaPulse only displays them: it does not "
        "recompute them and never mixes them into the risk scored from citizen observations.",
    # translator questions
    "Có nên cho trẻ chơi gần đây không?": "Should children play near here?",
    "Khu vực này có nguy cơ mùi hôi không?": "Is this stretch likely to smell?",
    "Sau trận mưa lớn, nơi nào cần kiểm tra trước?": "After heavy rain, where should we check first?",
    "Điểm nào đang ít dấu hiệu sự sống dưới nước nhất?":
        "Which stretch shows the least sign of life in the water?",
    # OneAquaHealth indicators
    "Mầm bệnh": "Pathogens", "Ô nhiễm từ phân": "Faecal pollution",
    "Gen kháng kháng sinh": "Antibiotic-resistance genes",
    "Chỉ số rủi ro sức khỏe tổng hợp": "Combined health-risk index",
    # Vector Watch: group names and their scope
    "Nguy cơ muỗi sinh sản": "Mosquito breeding risk",
    "Nước đọng, vật chứa (điều kiện muỗi Aedes sinh sản)":
        "Standing water and containers (Aedes breeding conditions)",
    "Nước tù, cống rãnh (điều kiện muỗi Culex)": "Stagnant water and drains (Culex conditions)",
    "Muỗi trưởng thành": "Adult mosquitoes", "Muỗi hoặc lăng quăng": "Mosquitoes or larvae",
    "Ruồi tập trung": "Fly cluster", "Ruồi, rác hữu cơ, vệ sinh": "Flies, organic waste, sanitation",
    "Chuột đô thị": "Urban rats", "Ngập lụt": "Flooding", "Ngập hoặc mưa lớn": "Flooding or heavy rain",
    "Tín hiệu nước bất thường": "Unusual water signals",
    "Váng, bọt, nước đổi màu, mùi lạ": "Sheen, foam, discoloured water, unusual odour",
    "Sinh vật nhỏ trong nước": "Small creatures in the water",
    "Ốc hoặc sinh vật nước": "Snails or aquatic creatures",
    "Ve và bọ chét": "Ticks and fleas", "Ruồi cát": "Sandflies", "Ruồi đen": "Black flies",
    "Vi khuẩn": "Bacteria", "Tảo độc cần xét nghiệm": "Toxic algae, laboratory testing required",
    "Nhóm khác (chỉ ghi nhận tham khảo)": "Other groups (recorded for reference only)",
    "Điểm đã xác minh, can thiệp": "Verified points and interventions",
    # Vector Watch: questions
    "Bạn quan tâm điều gì?": "What are you concerned about?",
    "Bạn thấy gì?": "What do you see?",
    "Có nước đọng không?": "Is there standing water?",
    "Nước đọng trong vật gì?": "What is holding the water?",
    "Nước đọng bao lâu chưa khô?": "How long has the water been standing?",
    "Thấy ở đâu?": "Where did you see it?",
    "Gần nơi nào?": "Near what?",
    "Gần chợ hoặc quán ăn không?": "Near a market or an eatery?",
    "Có rác hữu cơ gần đó không?": "Is there organic waste nearby?",
    "Có xác động vật hoặc phân gần đó không?": "Is there a dead animal or droppings nearby?",
    "Mưa gần đây?": "Rain recently?",
    "Mật độ (ước tính)": "Density (estimated)",
    "Nước có màu gì?": "What colour is the water?",
    "Có mùi lạ không?": "Any unusual smell?",
    "Có bọt không?": "Any foam?",
    "Có váng dầu, ánh cầu vồng trên mặt nước không?":
        "Is there an oil sheen or a rainbow film on the water?",
    "Rác nổi trên mặt nước?": "Floating litter on the surface?",
    "Có cá chết nổi không?": "Any dead fish floating?",
    "Có cá chết hoặc động vật tiếp xúc với nước không?":
        "Any dead fish, or animals in contact with the water?",
    "Có thấy cá, tôm, côn trùng sống không?": "Did you see live fish, shrimp or insects?",
    "Có thấy sinh vật nhỏ chuyển động trong nước không?":
        "Did you see small creatures moving in the water?",
    "Nước có rác, lá mục không?": "Is there litter or rotting leaves in the water?",
    "Nước tràn bờ hoặc ngập đường gần đó?": "Water over the bank, or a flooded street nearby?",
    "Người hoặc vật nuôi tiếp xúc?": "Did people or pets touch the water?",
    # Vector Watch: answer options
    "Có": "Yes", "Không": "No", "Không rõ": "Not sure", "Không chắc": "Not sure",
    "có": "yes", "không": "no",
    "Không chọn": "Not selected", "Không có": "None", "Khác": "Other", "Bình thường": "Normal",
    "Một ít": "A little", "Nhiều": "A lot", "Ít": "Few", "Vừa": "Some",
    "Dưới 1 ngày": "Less than a day", "1 đến 3 ngày": "1 to 3 days", "4 đến 7 ngày": "4 to 7 days",
    "Trên 7 ngày": "More than 7 days",
    "Xô, chậu, lu": "Bucket, basin, water jar", "Lốp xe": "Tyre", "Chậu cây": "Plant pot",
    "Hộp nhựa": "Plastic box", "Hốc cây": "Tree hollow", "Vũng nước": "Puddle", "Cống tắc": "Blocked drain",
    "Trong nhà": "Indoors", "Ngoài trời": "Outdoors", "Nhà ở": "Housing", "Trường học": "School",
    "Khu vui chơi": "Playground", "Gần cống": "Near a drain", "Gần rác": "Near rubbish",
    "Gần nước đọng": "Near standing water", "Xa khu dân cư": "Away from housing",
    "Không mưa": "No rain", "Mưa trong 48 giờ": "Rain in the last 48 hours",
    "Nâu, đen": "Brown or black", "Trắng đục": "Milky white", "Xanh bất thường": "Unusual green",
    "Có ánh cầu vồng": "Rainbow sheen", "Mùi thối": "Rotten smell", "Mùi cống": "Sewage smell",
    "Mùi hóa chất": "Chemical smell", "Nhiều côn trùng bay": "Many flying insects",
    "Xác động vật": "Dead animal", "Trẻ em chơi gần": "Children playing nearby",
    "Tiếp xúc trực tiếp": "Direct contact", "Người đi ngang": "People passing by", "Không ai": "Nobody",
    "Môi trường": "Environment", "Sức khỏe trẻ em": "Children's health", "Đa dạng sinh học": "Biodiversity",
    # Vector Watch: pipeline and verification
    "YOLO11n: vật chứa (lốp xe, chai, chậu, vỏ dừa, miệng cống)":
        "YOLO11n: containers (tyres, bottles, basins, coconut shells, drain mouths)",
    "YOLO11n: miệng cống": "YOLO11n: drain mouths",
    "YOLO11s-seg: nước": "YOLO11s-seg: water",
    "YOLO11s-seg: nước trong vật chứa": "YOLO11s-seg: water inside a container",
    "OpenCV: kiểm tra chất lượng ảnh": "OpenCV: image quality check",
    "OpenCV: kiểm tra chất lượng ảnh, ảnh trùng": "OpenCV: image quality and duplicate check",
    "PostGIS: gom cụm theo đoạn kênh": "PostGIS: clustering by canal stretch",
    "Qwen3-VL (tùy chọn): mô tả bề mặt nước": "Qwen3-VL (optional): describes the water surface",
    "Qwen3-VL (tùy chọn): mô tả bối cảnh": "Qwen3-VL (optional): describes the scene",
    "Qwen3-VL (tùy chọn): mô tả cụm côn trùng và bối cảnh":
        "Qwen3-VL (optional): describes the insect cluster and the scene",
    "Qwen3-VL (tùy chọn): mô tả mặt nước, váng, bọt":
        "Qwen3-VL (optional): describes the water, sheen and foam",
    "Qwen3-VL (tùy chọn): mô tả sơ bộ": "Qwen3-VL (optional): a first description",
    "Rule engine: điểm Aedes": "Rule engine: Aedes score",
    "Rule engine: điểm Culex, có số báo cáo lặp lại gần đó":
        "Rule engine: Culex score, with repeat reports nearby",
    "Rule engine: điểm ruồi": "Rule engine: fly score",
    "Rule engine: điểm quan sát chuột": "Rule engine: rat sighting score",
    "Rule engine: tín hiệu môi trường": "Rule engine: environmental signals",
    "Rule engine: liên kết với điều kiện môi trường": "Rule engine: links to environmental conditions",
    "Rule engine: điểm rủi ro, điểm sinh thái, mức liên quan sức khỏe người":
        "Rule engine: risk score, eco score, human-health relevance",
    "Không dùng model; chỉ ghi nhận.": "No model is used; the report is only recorded.",
    "Cộng đồng xác minh": "The community verifies",
    "Chuyên gia xác định loài": "An expert identifies the species",
    "Chuyên gia xem để tham khảo": "An expert reviews it for reference",
    "Chuyên gia hoặc phòng thí nghiệm: lấy mẫu": "An expert or a laboratory takes samples",
    "Chuyên gia hoặc đơn vị vệ sinh môi trường xử lý":
        "An expert or the sanitation service handles it",
    "Chuyên gia, bắt buộc": "An expert, always",
    "Chuyên gia, khi tín hiệu từ 0,5 trở lên": "An expert, once the signal reaches 0.5",
    "Người xác minh: bắt buộc": "A human verifier: always",
    "Người xác minh: khi nghi có lăng quăng": "A human verifier: when larvae are suspected",
    "Tình nguyện viên, bắt buộc": "A volunteer, always",
    "Tình nguyện viên, bắt buộc với mọi báo cáo": "A volunteer, for every report",
    "Tình nguyện viên khi mức cam, đỏ": "A volunteer at orange and red",
    "Tình nguyện viên, khi nghi có lăng quăng hoặc mức cam, đỏ":
        "A volunteer, when larvae are suspected or at orange and red",
    "Tình nguyện viên tại hiện trường; chuyên gia khi có váng dầu, mùi hóa chất hoặc cá chết":
        "A volunteer on site; an expert when there is an oil sheen, a chemical smell or dead fish",
    "Tình nguyện viên xác minh tại hiện trường, chuyên gia lấy mẫu":
        "A volunteer verifies on site, an expert takes samples",
    # Vector Watch: limits
    "Không có model nhận diện côn trùng; không tự xác định loài muỗi.":
        "There is no insect detector; the system never identifies a mosquito species by itself.",
    "Không xác định loài muỗi từ ảnh điện thoại; kết quả chỉ là nghi ngờ.":
        "A phone photo cannot identify a mosquito species; the result is only a suspicion.",
    "Không xác định loài muỗi; chỉ đánh giá điều kiện môi trường.":
        "No mosquito species is identified; only the environmental conditions are assessed.",
    "Ảnh chỉ cho thấy điều kiện sinh sản, không xác nhận có muỗi hay lăng quăng.":
        "A photo shows breeding conditions only; it does not confirm mosquitoes or larvae.",
    "Dùng lại model vật chứa và nước; chưa có dataset nước tù, cống riêng.":
        "Reuses the container and water models; there is no dataset for stagnant water or drains yet.",
    "Chưa có dataset cụm ruồi; dựa vào người báo và model mô tả.":
        "There is no fly-cluster dataset; this relies on the reporter and the description model.",
    "Không đếm được ruồi chính xác từ ảnh; mật độ là ước tính của người báo.":
        "Flies cannot be counted accurately from a photo; the density is the reporter's estimate.",
    "Chưa có model nhận diện chuột trong ảnh người dân chụp.":
        "There is no rat detector for photos taken by residents.",
    "Không xác định loài hay mầm bệnh; chỉ ghi nhận điểm quan sát.":
        "No species and no pathogen are identified; only the sighting is recorded.",
    "Chưa có dataset phân vùng váng, bọt; dựa vào người báo và model mô tả.":
        "There is no segmentation dataset for sheen or foam; this relies on the reporter and the "
        "description model.",
    "Không có model nhận diện váng dầu hay rác nổi đã huấn luyện; dựa vào người báo và model mô tả, "
    "model mô tả chỉ được gán 'nghi ngờ'.":
        "No trained detector exists for oil sheen or floating litter; this relies on the reporter and "
        "the description model, whose output is only ever marked \"suspected\".",
    "Chưa có classifier cho ốc; ảnh cận cảnh chuyển chuyên gia.":
        "There is no snail classifier; close-up photos go to an expert.",
    "Không xác định nguyên nhân chết từ ảnh.": "A photo cannot establish the cause of death.",
    "Không xác định vi khuẩn hay độc tố từ ảnh; chỉ phòng thí nghiệm xác nhận được.":
        "Bacteria and toxins cannot be identified from a photo; only a laboratory can confirm them.",
    "Không định danh loài tự động.": "No automatic species identification.",
    "Anopheles, ruồi cát, ruồi đen, ve, bọ chét, vi khuẩn, tảo độc: không xử lý tự động.":
        "Anopheles, sandflies, black flies, ticks, fleas, bacteria and toxic algae: nothing is "
        "processed automatically.",
    "Ảnh điện thoại không đủ để xác định các nhóm tầng C; cần xét nghiệm hoặc chuyên gia.":
        "A phone photo is not enough for tier C groups; testing or an expert is required.",
    "Ảnh và câu trả lời không xác định được vi khuẩn, hóa chất hay độc tố; chỉ lấy mẫu và phòng thí "
    "nghiệm xác nhận được. Đây không phải kết luận nước an toàn hay không an toàn.":
        "Photos and answers cannot identify bacteria, chemicals or toxins; only sampling and a "
        "laboratory can. This is not a statement that the water is safe or unsafe.",
    "YOLO11n trên VisText-Mosquito (1.640 ảnh). Lớp lốp xe chưa kiểm chứng trên ảnh thật. "
    "Model nước chỉ có 89 ảnh huấn luyện.":
        "YOLO11n trained on VisText-Mosquito (1,640 images). The tyre class is unverified on real "
        "photos. The water model was trained on only 89 images.",
}

# --- sentences built around numbers ------------------------------------------------------
# Each rule is (pattern, replacement). \g<n> keeps the number; _decimal fixes 0,74 -> 0.74.
_RULES: list[tuple[str, str]] = [
    # translator: certainty and data used
    (r"^Thấp: không có quan sát nào trong 7 ngày qua\.$",
     "Low: no observations at all in the last 7 days."),
    (r"^(?P<label>\w[\w ]*) \(độ tin cậy trung bình (?P<c>[\d.,]+), (?P<n>\d+) quan sát trong 7 ngày\)\.$",
     "{label} (mean confidence {c}, {n} observations in 7 days)."),
    ((r"^(?P<n>\d+) quan sát của người dân trong 30 ngày \((?P<p>\d+) người, (?P<c>\d+) đã xác nhận tại "
     r"hiện trường\)$"),
     "{n} citizen observations in 30 days ({p} people, {c} confirmed on site)"),
    (r"^(?P<n>\d+) cảnh báo đang mở$", "{n} open alerts"),
    (r"^Hộ chiếu rủi ro của (?P<n>\d+) đoạn kênh$", "Risk passports of {n} canal stretches"),
    (r"^Dựa trên (?P<n>\d+) quan sát trong 7 ngày trên toàn tuyến kênh\.$",
     "Based on {n} observations over 7 days across all stretches."),
    # translator: children
    ((r"^Chưa đủ dữ liệu cho (?P<seg>.+?): không có quan sát nào trong 7 ngày\. Không nên để trẻ lội hay "
     r"chơi dưới nước kênh khi chưa biết tình trạng\.$"),
     ("Not enough data for {seg}: no observations in 7 days. Children should not wade or play in canal "
      "water while its state is unknown.")),
    ((r"^Chưa nên\. (?P<seg>.+?) có (?P<n>\d+) quan sát bất thường trong 7 ngày(?P<h> \(\d+ lần ghi nhận "
     r"váng dầu, mùi lạ hoặc cá chết\))?(?P<a>, và đang có cảnh báo chưa xác minh)?\. Có thể chơi trên "
     r"bờ, xa mép nước; không lội, không chạm nước\.$"),
     ("Not yet. {seg} has {n} unusual observations in 7 days{h}{a}. Playing on the bank, away from the "
      "edge, is fine; no wading, no touching the water.")),
    ((r"^Chưa thấy dấu hiệu bất thường ở (?P<seg>.+?) trong 7 ngày\. Trẻ có thể chơi trên bờ; vẫn không "
     r"nên lội hay uống nước kênh, vì nước kênh đô thị chưa được kiểm tra\.$"),
     ("No unusual signs at {seg} in the last 7 days. Children can play on the bank; still no wading and "
      "no drinking, because urban canal water is not tested.")),
    (r"^\((?P<n>\d+) lần ghi nhận váng dầu, mùi lạ hoặc cá chết\)$",
     "({n} reports of oil sheen, unusual odour or dead fish)"),
    (r"^, và đang có cảnh báo chưa xác minh$", ", and an alert there is still unverified"),
    (r"^Mùi thường nặng hơn sau mưa lớn, khi cống xả ra kênh\.$",
     "The smell is usually stronger after heavy rain, when the sewers discharge into the canal."),
    # translator: odour
    ((r"^Có\. (?P<n>\d+) trong (?P<m>\d+) quan sát 30 ngày qua ghi nhận mùi lạ\.(?P<rain> Mùi thường nặng "
     r"hơn sau mưa lớn, khi cống xả ra kênh\.)? Xu hướng báo cáo bất thường: (?P<t>.+?)\.$"),
     ("Yes. {n} of {m} observations in the last 30 days reported an unusual smell.{rain} Trend in "
      "unusual reports: {t}.")),
    ((r"^Chưa có quan sát nào trong (?P<m>\d+) quan sát 30 ngày qua ghi nhận mùi lạ\. Xu hướng báo cáo "
     r"bất thường: (?P<t>.+?)\.$"),
     ("None of the {m} observations in the last 30 days reported an unusual smell. Trend in unusual "
      "reports: {t}.")),
    (r"^Chưa có quan sát nào ở (?P<seg>.+?) để trả lời\. Xu hướng báo cáo bất thường: (?P<t>.+?)\.$",
     "There are no observations at {seg} to answer with. Trend in unusual reports: {t}."),
    # translator: after rain, biodiversity
    (r"^Nên kiểm tra theo thứ tự: (?P<list>.+)\.$", "Check in this order: {list}."),
    ((r"^(?P<seg>.+?): chỉ (?P<a>\d+)/(?P<b>\d+) quan sát thấy cá, tôm hay côn trùng sống(?P<eco>, điểm "
     r"sinh thái [\d.,]+)?\. Đây là số người dân nhìn thấy, không phải khảo sát loài\.$"),
     ("{seg}: only {a} of {b} observations saw live fish, shrimp or insects{eco}. This is what residents "
      "saw, not a species survey.")),
    (r"^, điểm sinh thái (?P<x>[\d.,]+)$", ", eco score {x}"),
    (r"^(?P<n>\d+) quan sát bất thường trong 7 ngày$", "{n} unusual observations in 7 days"),
    ((r"^Người báo chưa chọn nhóm; hệ thống đoán là '(?P<group>.+)'\.$"),
     "The reporter chose no group; the system guessed \"{group}\"."),
    (r"^mưa (?P<x>[\d.,]+) mm$", "{x} mm of rain"),
    (r"^chưa có ai quan sát tuần này$", "nobody observed this week"),
    (r"^ít dấu hiệu$", "few signs"),
    # passport explanation
    (r"^Chưa đủ dữ liệu để nói xu hướng: (?P<n>\d+) báo cáo bất thường trong 14 ngày\.$",
     "Not enough data to state a trend: {n} unusual reports in 14 days."),
    ((r"^Trong 7 ngày qua, đoạn này có (?P<n>\d+) báo cáo bất thường, (?P<dir>tăng|giảm|không đổi)"
     r"(?P<pct> \d+%)? so với 7 ngày trước \((?P<m>\d+)\)\. (?P<label>.+?)\.$"),
     ("Over the last 7 days this stretch had {n} unusual reports, {dir}{pct} against the 7 days before "
      "({m}). {label}.")),
    (r"^Dấu hiệu gặp nhiều nhất: (?P<list>.+)\.$", "Most frequent signs: {list}."),
    (r"^Độ tin cậy (?P<label>cao|trung bình|thấp|chưa có)(?P<why> vì .+)?\.$",
     "Confidence is {label}{why}."),
    (r"^vì (?P<why>.+)$", ", because {why}"),
    (r"^phần lớn quan sát được gửi vào ban đêm, ảnh khó thấy màu nước và váng$",
     "most observations were sent at night, when colour and sheen are hard to see"),
    (r"^chỉ (?P<n>\d+) người báo$", "only {n} people reported"),
    (r"^chưa có ai xác minh tại hiện trường$", "nobody has verified on site"),
    (r"^Nên bổ sung (?P<n>\d+) quan sát ban ngày trước khi phát cảnh báo chính thức\.$",
     "Add {n} daytime observations before issuing a formal alert."),
    ((r"^Mưa lớn (?P<x>[\d.,]+) mm ngày (?P<d>[\d/]+) \(số đo Open-Meteo\); (?P<n>\d+) báo cáo gửi trong "
     r"48 giờ sau đó\.$"),
     "Heavy rain of {x} mm on {d} (Open-Meteo measurement); {n} reports sent in the 48 hours after."),
    (r"^(?P<n>\d+) báo cáo có trẻ em chơi gần hoặc người tiếp xúc trực tiếp với nước\.$",
     "Children playing nearby or people in direct contact with the water: {n} reports."),
    # OneAquaHealth
    ((r"^OneAquaHealth đo chỉ số rủi ro sức khỏe (?P<x>[\d.,]+) tại điểm này \(lấy mẫu (?P<d>[\d/]+)\): "
     r"mức (?P<w>cao|trung bình|thấp)\.$"),
     "OneAquaHealth measured a health-risk index of {x} at this site (sampled {d}): {w}."),
    ((r"^Thành phần: Mầm bệnh (?P<a>[\d.,]+), Ô nhiễm từ phân (?P<b>[\d.,]+), Gen kháng kháng sinh "
     r"(?P<c>[\d.,]+)\. Đây là kết quả phòng thí nghiệm của dự án, không phải kết quả của AquaPulse\.$"),
     ("Components: pathogens {a}, faecal pollution {b}, antibiotic-resistance genes {c}. These are the "
      "project's laboratory results, not AquaPulse's.")),
    (r"^Trong bán kính 500 m: (?P<a>[\d.,]+)% bề mặt bê tông hóa, (?P<b>[\d.,]+)% cây xanh\.$",
     "Within 500 m: {a}% sealed surface, {b}% tree cover."),
    (r"^Trạm xử lý nước thải gần nhất cách (?P<x>[\d.,]+) km\.$",
     "The nearest wastewater treatment plant is {x} km away."),
    (r"^Chưa có số đo rủi ro sức khỏe tại điểm này\.$",
     "No health-risk measurement exists for this site yet."),
    # the result panel's sentences with numbers
    ((r"^Ảnh cho thấy khả năng có (?P<what>.+?), độ tin cậy (?P<pct>\d+)%\. (?P<ask>.+)$"),
     "The photo suggests {what}, {pct}% confidence. {ask}"),
    ((r"^Có dấu hiệu: (?P<list>.+)\.$"), "Signs seen: {list}."),
    ((r"^Cần thêm thông tin trước khi nâng cảnh báo: (?P<list>.+)$"),
     "More information is needed before raising the alert: {list}"),
    ((r"^Điểm tạm tính (?P<score>[\d.,]+) từ Cam trở lên nhưng chỉ dựa trên (?P<share>[\d.,]+) "
      r"dữ liệu của công thức\.$"),
     ("A provisional score of {score} reaches orange, but rests on only {share} of the "
      "formula's data.")),
    ((r"^Chỉ model mô tả bối cảnh thấy (?P<list>.+?); chưa tính vào điểm\.$"),
     "Only the description model saw {list}; it does not enter the score."),
    ((r"^Model mô tả bối cảnh báo (?P<list>.+?)\.$"), "The description model reported {list}."),
    ((r"^Độ tin cậy thấp \((?P<c>[\d.,]+)\) nhưng rủi ro không thấp\.$"),
     "Confidence is low ({c}) while the risk is not."),
    ((r"^Điểm (?P<score>[\d.,]+) đủ mức (?P<level>.+?), giữ ở vàng vì chưa có người xác minh tại "
      r"hiện trường\.$"),
     "A score of {score} would reach {level}; it stays yellow because nobody has verified on site."),
    ((r"^Cảnh báo mức (?P<level>.+?) \(R = (?P<r>[\d.,]+)\)\.$"),
     "The alert is at {level} (R = {r})."),
    ((r"^Độ tin cậy thấp \(C = (?P<c>[\d.,]+) < (?P<floor>[\d.,]+)\)\.$"),
     "Confidence is low (C = {c} < {floor})."),
    ((r"^Độ tin cậy trung bình \(C = (?P<c>[\d.,]+)\); nhờ người báo xác nhận\.$"),
     "Confidence is medium (C = {c}); the reporter is asked to confirm."),
    ((r"^Nhóm '(?P<group>.+?)': (?P<statement>.+)$"), "Group \"{group}\": {statement}"),
    ((r"^Nhóm '(?P<group>.+?)' cần chuyên gia\.$"), "Group \"{group}\" needs an expert."),
    ((r"^Tín hiệu nước bất thường (?P<score>[\d.,]+): đề xuất lấy mẫu\.$"),
     "Unusual water signals at {score}: sampling is suggested."),
    ((r"^Hai model mâu thuẫn về (?P<what>.+?)\. Cần người xác minh\.$"),
     "The two models disagree about {what}. A person must verify it."),
    ((r"^Người báo nói không có (?P<what>.+?), nhưng AI thấy có\. Cần người báo xác nhận\.$"),
     "The reporter said there is no {what}, but the AI saw one. The reporter is asked to confirm."),
    ((r"^Người báo nói có (?P<what>.+?), nhưng AI không thấy\. Cần người báo xác nhận\.$"),
     "The reporter reported {what}, but the AI did not see it. The reporter is asked to confirm."),
    ((r"^model nhận diện (?P<detector>.+?), model mô tả (?P<vision>.+)$"),
     "the detector says {detector}, the description model says {vision}"),
    # segment names: "Đoạn 2 · km 2,2-4,4" is generated, not a place name
    (r"^Đoạn (?P<n>\d+) · km (?P<a>[\d.,]+)–(?P<b>[\d.,]+)$", "Stretch {n} · km {a}-{b}"),
    (r"^Bằng chứng: (?P<source>.+)\.$", "Evidence: {source}."),
    (r"^(?P<n>\d+) người khác nhau gửi ảnh$", "{n} different people sent photos"),
    (r"^(?P<n>\d+) báo cáo đã được xác nhận tại hiện trường$", "{n} reports confirmed on site"),
    (r"^AI chỉ gán nghi ngờ ở (?P<n>\d+) ảnh, chưa kết luận$",
     "the AI marked {n} photos as suspected only, concluding nothing"),
    ((r"^Độ tin cậy (?P<label>cao|trung bình|thấp|chưa có)(?P<num> \([\d.,]+\))?"
      r"(?P<night>, phần lớn ảnh chụp ban đêm)?\.$"),
     "Confidence {label}{num}{night}."),
    (r"^khu vực này có (?P<n>\d+) báo cáo về (?P<what>.+?) trong 72 giờ qua\.$",
     "this area has {n} reports of {what} in the last 72 hours."),
    # alerts, notifications (the stored message keeps its Vietnamese wording in the database)
    (r"^Cảnh báo mức (?P<lvl>vàng|cam|đỏ): (?P<rest>.+)$", "{lvl} alert: {rest}"),
    (r"^(?P<n>\d+) quan sát trong bán kính (?P<r>\d+) m ghi nhận (?P<s>.+?) trong (?P<h>\d+) giờ\.$",
     "{n} observations within {r} m reported {s} over {h} hours."),
    (r"^(?P<n>\d+) báo cáo từ (?P<p>\d+) người trong khu vực\.$",
     "{n} reports from {p} people in the area."),
]
PATTERNS = [(re.compile(p), r) for p, r in _RULES]

# Words that appear inside a generated sentence, where an exact-match phrase would be too blunt.
INNER = {"tăng": "up", "giảm": "down", "không đổi": "unchanged",
         "vàng": "Yellow", "cam": "Orange", "đỏ": "Red"}


def _decimal(value: str) -> str:
    """0,74 -> 0.74: the sentence is English now, so the decimal mark follows it."""
    return re.sub(r"(\d),(\d)", r"\1.\2", value)


# English counts one thing at a time: "1 reports" would betray that a machine wrote the line.
_ONE = re.compile(r"\b1 (?P<mid>(?:[a-z]+ )*?)(?P<word>[a-z]+)s\b")


def _singular(sentence: str) -> str:
    out = _ONE.sub(lambda m: f"1 {m.group('mid')}{m.group('word')}", sentence)
    return out.replace("1 people", "1 person")


def _render(template: str, match: re.Match[str]) -> str:
    parts: dict[str, str] = {}
    for name, raw in match.groupdict().items():
        value = _decimal(raw or "").strip() if raw else ""
        parts[name] = INNER.get(value, text(value) if value else "")
        # The "vì ..." rule renders first and joins the reasons; the outer rule must not join again.
        if name == "why" and ", and " not in parts[name] and parts[name].count(", ") > 1:
            head, _, last = parts[name].rpartition(", ")
            parts[name] = f"{head}, and {last}"    # a reason list ends with "and" in English
        if raw and raw.startswith(" ") and parts[name] and not parts[name].startswith((",", " ")):
            parts[name] = " " + parts[name]  # an optional clause keeps the space before it
    return _singular(template.format(**parts))


def text(value: str) -> str:
    """One Vietnamese string in, its English in, or the Vietnamese back when unknown."""
    stripped = value.strip()
    if not stripped:
        return value
    if stripped in PHRASES:
        return PHRASES[stripped]
    for pattern, template in PATTERNS:
        match = pattern.match(stripped)
        if match:
            return _render(template, match)
    if stripped.endswith(".") and stripped[:-1] in PHRASES:
        return PHRASES[stripped[:-1]] + "."
    # A paragraph (an alert message), then a list built from translatable parts
    # ("váng dầu (3 lần), mùi lạ (1 lần)", "1. Name: a, b").
    for joined in (_sentences(stripped), _list(stripped)):
        if joined is not None:
            return joined
    return value


def _sentences(value: str) -> str | None:
    """An alert message is five sentences; translate it only when every one is known."""
    parts = value.split(". ")
    if len(parts) < 2:
        return None
    out = []
    for i, part in enumerate(parts):
        piece = part if i == len(parts) - 1 else part + "."
        done = _known(piece)
        if done is None:
            return None
        out.append(done[:-1] if i < len(parts) - 1 and done.endswith(".") else done)
    return ". ".join(out)


_ITEM = re.compile(r"^(?P<head>\d+\. )?(?P<body>.+?)(?P<count> \((?P<n>\d+)(?P<times> lần)?\))?$")


def _item(part: str) -> str | None:
    """One entry of a list: "2. Đoạn 2: mưa 30 mm, 1 cảnh báo đang mở" or "váng dầu (3 lần)"."""
    match = _ITEM.match(part.strip())
    if match is None:
        return None
    body, head = match.group("body"), match.group("head") or ""
    count = "" if not match.group("count") else (
        f" ({match.group('n')} times)" if match.group("times") else f" ({match.group('n')})")
    if ": " in body:  # "<place>: <reason>, <reason>" - the place is a name, the reasons are not
        place, reasons = body.split(": ", 1)
        done = _known(reasons)
        return None if done is None else f"{head}{text(_decimal(place))}: {done}{count}"
    done = _known(body)
    return None if done is None else head + done + count


def _known(value: str) -> str | None:
    """The English of a fragment, or None when nothing in this module recognises it."""
    done = text(value)
    return done if done != value or value in PHRASES else None


def _list(value: str) -> str | None:
    """Translate a joined list only when every part is known: half an English list is worse.

    Entries may hold commas of their own ("sent at night, when colour is hard to see"), so the
    longest run of comma-separated pieces that translates as one entry wins.
    """
    for sep, glue in (("; ", "; "), (", ", ", "), (" và ", " and ")):
        if sep not in value:
            continue
        pieces, out, i = value.split(sep), [], 0
        while i < len(pieces):
            for end in range(len(pieces), i, -1):
                if i == 0 and end == len(pieces):
                    continue  # the whole string: text() has already tried that, and would recurse
                done = _item(sep.join(pieces[i:end]))
                if done is not None:
                    out.append(done)
                    i = end
                    break
            else:
                return None
        return glue.join(out)
    return None


def localize(payload: Any, lang: str) -> Any:
    """Walk a response and translate the strings meant for a reader."""
    if normalize(lang) != "en":
        return payload
    return _walk(payload, None)


def _walk(node: Any, key: str | None) -> Any:
    if isinstance(node, dict):
        return {k: _walk(v, k) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, key) for v in node]
    if isinstance(node, str) and key not in SKIP_KEYS:
        return text(node)
    return node
