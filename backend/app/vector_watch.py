"""AquaPulse Vector Watch: vectors and health-risk indicators, one group at a time.

One place for everything the module needs per group: its tier, the questions the
form asks, how it is processed, its score, who verifies it, which dashboard layer it
belongs to, and what the result may and may not claim. The form (GET
/vector-watch/catalog) and the dashboard read from here, so they cannot drift apart.

Tiers:
    A  in the MVP          Aedes breeding conditions, mosquito/larvae reports,
                           fly clusters, unusual water surface
    B  can be added        Culex conditions, rodents, dead animals, freshwater snails
    C  reference only      Anopheles, sand flies, black flies, ticks and fleas,
                           bacteria, toxic algae: recorded, never scored

The group formulas are the module brief's. Two departures, for failures measured on
the earlier formulas (sections 12 and 16):

* no `raw_score * confidence`: that turned an orange report green for a new reporter.
  The confidence C stays next to the score;
* a factor nobody observed is left out and the other weights renormalised, instead
  of counting as 0 ("no rain data" is not "no rain"). A score resting on less than
  MIN_KNOWN_WEIGHT of its formula is flagged as insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.features import FeatureSet
from app.fusion import (
    Amount,
    Contact,
    ContainerType,
    Fusion,
    NearbyPlace,
    ObservationGoal,
    ObservationGroup,
    Odor,
    RecentRain,
    ReportAnswers,
    SeenWhere,
    StandingDays,
    TrashAmount,
    WaterColor,
    YesNo,
)

G = ObservationGroup
MIN_KNOWN_WEIGHT = 0.6
POSITIVE_AT = 0.5

# --- the questions ------------------------------------------------------------------

YES_NO = [("yes", "Có"), ("no", "Không"), ("unknown", "Không rõ")]
QUESTIONS: dict[str, dict[str, object]] = {
    "water_stagnant": {"label": "Có nước đọng không?", "options": YES_NO},
    "container_type": {"label": "Nước đọng trong vật gì?", "options": [
        ("used_tire", "Lốp xe"), ("bottle_or_can", "Chai, lon"), ("bucket_or_jar", "Xô, chậu, lu"),
        ("plastic_box", "Hộp nhựa"), ("tree_hole", "Hốc cây"), ("flower_pot", "Chậu cây"),
        ("blocked_drain", "Cống tắc"), ("puddle", "Vũng nước"), ("other", "Khác"), ("unknown", "Không rõ")]},
    "leaf_litter": {"label": "Nước có rác, lá mục không?", "options": YES_NO},
    "standing_days": {"label": "Nước đọng bao lâu chưa khô?", "options": [
        ("lt_1", "Dưới 1 ngày"), ("d1_3", "1 đến 3 ngày"), ("d4_7", "4 đến 7 ngày"), ("gt_7", "Trên 7 ngày"),
        ("unknown", "Không rõ")]},
    "moving_organisms": {"label": "Có thấy sinh vật nhỏ chuyển động trong nước không?", "options": YES_NO},
    "insect_seen": {"label": "Bạn thấy gì?", "options": [
        ("adult_mosquito", "Muỗi trưởng thành"), ("small_organisms_in_water", "Sinh vật nhỏ trong nước"),
        ("many_flying_insects", "Nhiều côn trùng bay"), ("unsure", "Không chắc")]},
    "seen_where": {"label": "Thấy ở đâu?", "options": [
        ("near_standing_water", "Gần nước đọng"), ("near_drain", "Gần cống"), ("near_garbage", "Gần rác"),
        ("indoors", "Trong nhà"), ("outdoors", "Ngoài trời"), ("unknown", "Không rõ")]},
    "density": {"label": "Mật độ (ước tính)", "options": [
        ("few", "Ít"), ("some", "Vừa"), ("many", "Nhiều"), ("unknown", "Không rõ")]},
    "organic_waste": {"label": "Có rác hữu cơ gần đó không?", "options": YES_NO},
    "dead_animal_or_feces": {"label": "Có xác động vật hoặc phân gần đó không?", "options": YES_NO},
    "odor": {"label": "Có mùi lạ không?", "options": [
        ("none", "Không"), ("rotten", "Mùi thối"), ("sewage", "Mùi cống"), ("chemical", "Mùi hóa chất"),
        ("unknown", "Không rõ")]},
    "near_food_place": {"label": "Gần chợ hoặc quán ăn không?", "options": YES_NO},
    "water_color": {"label": "Nước có màu gì?", "options": [
        ("normal", "Bình thường"), ("unusual_green", "Xanh bất thường"), ("brown_black", "Nâu, đen"),
        ("milky_white", "Trắng đục"), ("rainbow_sheen", "Có ánh cầu vồng"), ("unsure", "Không chắc")]},
    "foam": {"label": "Có bọt không?", "options": YES_NO},
    "dead_fish_or_animal_contact": {"label": "Có cá chết hoặc động vật tiếp xúc với nước không?", "options": YES_NO},
    "recent_rain": {"label": "Mưa gần đây?", "options": [
        ("none", "Không mưa"), ("within_48h", "Mưa trong 48 giờ"), ("flood_or_heavy", "Ngập hoặc mưa lớn"),
        ("unknown", "Không rõ")]},
    "nearby_place": {"label": "Gần nơi nào?", "options": [
        ("far", "Xa khu dân cư"), ("home", "Nhà ở"), ("school", "Trường học"), ("playground", "Khu vui chơi"),
        ("unknown", "Không rõ")]},
    "contact": {"label": "Người hoặc vật nuôi tiếp xúc?", "options": [
        ("none", "Không ai"), ("passing", "Người đi ngang"), ("children_nearby", "Trẻ em chơi gần"),
        ("direct", "Tiếp xúc trực tiếp"), ("unknown", "Không rõ")]},
    # River and canal form (AquaPulse brief): what people can see, smell and recognise.
    "observation_goal": {"label": "Bạn quan tâm điều gì?", "options": [
        ("environment", "Môi trường"), ("child_health", "Sức khỏe trẻ em"), ("flooding", "Ngập lụt"),
        ("biodiversity", "Đa dạng sinh học"), ("unknown", "Không chọn")]},
    "oil_sheen": {"label": "Có váng dầu, ánh cầu vồng trên mặt nước không?", "options": YES_NO},
    "floating_trash": {"label": "Rác nổi trên mặt nước?", "options": [
        ("none", "Không có"), ("little", "Một ít"), ("lots", "Nhiều"), ("unknown", "Không rõ")]},
    "aquatic_life": {"label": "Có thấy cá, tôm, côn trùng sống không?", "options": YES_NO},
    "dead_fish": {"label": "Có cá chết nổi không?", "options": YES_NO},
    "overflow": {"label": "Nước tràn bờ hoặc ngập đường gần đó?", "options": YES_NO},
}
COMMON_QUESTIONS = ("nearby_place", "contact", "recent_rain")


# --- the catalog ------------------------------------------------------------------------

@dataclass(frozen=True)
class GroupSpec:
    id: ObservationGroup
    tier: str
    label: str
    domain: str   # vector | sanitation | water_quality | aquatic | reference
    layer: str    # dashboard layer
    questions: tuple[str, ...]
    processing: tuple[str, ...]
    data_now: str  # what data and models exist today, stated plainly
    verification: str
    always_verify: bool
    expert: bool
    positive: str
    negative: str
    limitation: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id.value, "tier": self.tier, "label": self.label, "domain": self.domain,
            "layer": self.layer, "questions": list(self.questions) + list(COMMON_QUESTIONS),
            "processing": list(self.processing), "data_now": self.data_now,
            "verification": self.verification, "always_verify": self.always_verify, "expert": self.expert,
            "limitation": self.limitation,
        }


CATALOG: dict[ObservationGroup, GroupSpec] = {spec.id: spec for spec in (
    GroupSpec(
        G.RIVER_HEALTH, "A", "Sông, kênh: mặt nước, bờ, rác nổi", "water_quality", "water_anomaly",
        ("observation_goal", "water_color", "odor", "foam", "oil_sheen", "floating_trash", "aquatic_life",
         "dead_fish", "overflow"),
        ("OpenCV: kiểm tra chất lượng ảnh, ảnh trùng", "Qwen3-VL (tùy chọn): mô tả mặt nước, váng, bọt",
         "Rule engine: điểm rủi ro, điểm sinh thái, mức liên quan sức khỏe người",
         "PostGIS: gom cụm theo đoạn kênh", "Tình nguyện viên xác minh tại hiện trường, chuyên gia lấy mẫu"),
        "Không có model nhận diện váng dầu hay rác nổi đã huấn luyện; dựa vào người báo và model mô tả, "
        "model mô tả chỉ được gán 'nghi ngờ'.",
        "Tình nguyện viên tại hiện trường; chuyên gia khi có váng dầu, mùi hóa chất hoặc cá chết", False, False,
        "Có dấu hiệu bất thường trên mặt nước; cần xác minh tại hiện trường. "
        "Tránh tiếp xúc trực tiếp với nước cho đến khi có kết quả kiểm tra.",
        "Chưa thấy dấu hiệu bất thường rõ ở đoạn sông, kênh này.",
        "Ảnh và câu trả lời không xác định được vi khuẩn, hóa chất hay độc tố; chỉ lấy mẫu và phòng "
        "thí nghiệm xác nhận được. Đây không phải kết luận nước an toàn hay không an toàn.",
    ),
    GroupSpec(
        G.AEDES_BREEDING_RISK, "A", "Nước đọng, vật chứa (điều kiện muỗi Aedes sinh sản)",
        "vector", "mosquito_breeding",
        ("water_stagnant", "container_type", "leaf_litter", "standing_days", "moving_organisms"),
        ("OpenCV: kiểm tra chất lượng ảnh", "YOLO11n: vật chứa (lốp xe, chai, chậu, vỏ dừa, miệng cống)",
         "YOLO11s-seg: nước trong vật chứa", "Qwen3-VL (tùy chọn): mô tả bối cảnh",
         "Rule engine: điểm Aedes", "Người xác minh: khi nghi có lăng quăng"),
        "YOLO11n trên VisText-Mosquito (1.640 ảnh). Lớp lốp xe chưa kiểm chứng trên ảnh thật. "
        "Model nước chỉ có 89 ảnh huấn luyện.",
        "Tình nguyện viên, khi nghi có lăng quăng hoặc mức cam, đỏ", False, False,
        "Có điều kiện phù hợp cho muỗi sinh sản: nước đọng trong vật chứa. Nên đổ bỏ hoặc đậy kín.",
        "Chưa thấy điều kiện đáng kể cho muỗi sinh sản.",
        "Ảnh chỉ cho thấy điều kiện sinh sản, không xác nhận có muỗi hay lăng quăng.",
    ),
    GroupSpec(
        G.MOSQUITO_ACTIVITY, "A", "Muỗi hoặc lăng quăng", "vector", "mosquito_breeding",
        ("insect_seen", "seen_where", "density"),
        ("Qwen3-VL (tùy chọn): mô tả sơ bộ", "Rule engine: liên kết với điều kiện môi trường",
         "Người xác minh: bắt buộc"),
        "Không có model nhận diện côn trùng; không tự xác định loài muỗi.",
        "Tình nguyện viên, bắt buộc với mọi báo cáo", True, False,
        "Nghi ngờ có hoạt động của côn trùng gần điểm nước đọng; cần người xác minh.",
        "Đã ghi nhận báo cáo côn trùng; cần người xác minh.",
        "Không xác định loài muỗi từ ảnh điện thoại; kết quả chỉ là nghi ngờ.",
    ),
    GroupSpec(
        G.FLY_CLUSTER, "A", "Ruồi tập trung", "sanitation", "fly_organic",
        ("density", "organic_waste", "dead_animal_or_feces", "odor", "near_food_place"),
        ("Qwen3-VL (tùy chọn): mô tả cụm côn trùng và bối cảnh", "Rule engine: điểm ruồi"),
        "Chưa có dataset cụm ruồi; dựa vào người báo và model mô tả.",
        "Tình nguyện viên khi mức cam, đỏ", False, False,
        "Có dấu hiệu tập trung ruồi gần nguồn rác hữu cơ; cần kiểm tra vệ sinh môi trường.",
        "Chưa thấy dấu hiệu tập trung ruồi đáng kể.",
        "Không đếm được ruồi chính xác từ ảnh; mật độ là ước tính của người báo.",
    ),
    GroupSpec(
        G.WATER_QUALITY_SIGNAL, "A", "Váng, bọt, nước đổi màu, mùi lạ", "water_quality", "water_anomaly",
        ("water_color", "foam", "odor", "dead_fish_or_animal_contact"),
        ("Qwen3-VL (tùy chọn): mô tả bề mặt nước", "Rule engine: tín hiệu môi trường",
         "Chuyên gia hoặc phòng thí nghiệm: lấy mẫu"),
        "Chưa có dataset phân vùng váng, bọt; dựa vào người báo và model mô tả.",
        "Chuyên gia, khi tín hiệu từ 0,5 trở lên", False, True,
        "Có dấu hiệu bất thường trên bề mặt nước; cần lấy mẫu hoặc xác minh chuyên môn.",
        "Chưa thấy dấu hiệu bất thường rõ trên mặt nước.",
        "Không xác định vi khuẩn hay độc tố từ ảnh; chỉ phòng thí nghiệm xác nhận được.",
    ),
    GroupSpec(
        G.CULEX_ENVIRONMENTAL_RISK, "B", "Nước tù, cống rãnh (điều kiện muỗi Culex)", "vector",
        "mosquito_breeding",
        ("water_stagnant", "container_type", "leaf_litter", "odor", "organic_waste"),
        ("YOLO11n: miệng cống", "YOLO11s-seg: nước", "Rule engine: điểm Culex, có số báo cáo lặp lại gần đó"),
        "Dùng lại model vật chứa và nước; chưa có dataset nước tù, cống riêng.",
        "Tình nguyện viên khi mức cam, đỏ", False, False,
        "Có nước tù, rác hữu cơ hoặc cống tắc: điều kiện phù hợp cho muỗi Culex. Cần khơi thông, dọn rác.",
        "Chưa thấy điều kiện đáng kể cho muỗi Culex.",
        "Không xác định loài muỗi; chỉ đánh giá điều kiện môi trường.",
    ),
    GroupSpec(
        G.RODENT_SIGHTING, "B", "Chuột đô thị", "sanitation", "fly_organic",
        ("density", "seen_where", "organic_waste"),
        ("Rule engine: điểm quan sát chuột", "Cộng đồng xác minh"),
        "Chưa có model nhận diện chuột trong ảnh người dân chụp.",
        "Tình nguyện viên, bắt buộc", True, False,
        "Ghi nhận chuột gần khu vực; cần cộng đồng xác minh và xử lý nguồn thức ăn, nơi trú.",
        "Đã ghi nhận báo cáo chuột; cần cộng đồng xác minh.",
        "Không xác định loài hay mầm bệnh; chỉ ghi nhận điểm quan sát.",
    ),
    GroupSpec(
        G.DEAD_ANIMAL, "B", "Xác động vật", "sanitation", "fly_organic",
        ("dead_animal_or_feces", "odor", "dead_fish_or_animal_contact"),
        ("Chuyên gia hoặc đơn vị vệ sinh môi trường xử lý",),
        "Không dùng model; chỉ ghi nhận.",
        "Chuyên gia, bắt buộc", True, True,
        "Ghi nhận xác động vật; không chạm tay trần, báo đơn vị vệ sinh môi trường.",
        "Ghi nhận xác động vật; không chạm tay trần, báo đơn vị vệ sinh môi trường.",
        "Không xác định nguyên nhân chết từ ảnh.",
    ),
    GroupSpec(
        G.AQUATIC_SPECIES, "B", "Ốc hoặc sinh vật nước", "aquatic", "water_anomaly",
        ("water_color",),
        ("Chuyên gia xác định loài",),
        "Chưa có classifier cho ốc; ảnh cận cảnh chuyển chuyên gia.",
        "Chuyên gia, bắt buộc", True, True,
        "Ghi nhận ốc hoặc sinh vật nước; chuyên gia sẽ xác định loài.",
        "Ghi nhận ốc hoặc sinh vật nước; chuyên gia sẽ xác định loài.",
        "Không định danh loài tự động.",
    ),
    GroupSpec(
        G.OTHER_REFERENCE, "C", "Nhóm khác (chỉ ghi nhận tham khảo)", "reference", "reference",
        (),
        ("Chuyên gia xem để tham khảo",),
        "Anopheles, ruồi cát, ruồi đen, ve, bọ chét, vi khuẩn, tảo độc: không xử lý tự động.",
        "Chuyên gia, bắt buộc", True, True,
        "Đã ghi nhận để chuyên gia tham khảo; hệ thống không đánh giá tự động nhóm này.",
        "Đã ghi nhận để chuyên gia tham khảo; hệ thống không đánh giá tự động nhóm này.",
        "Ảnh điện thoại không đủ để xác định các nhóm tầng C; cần xét nghiệm hoặc chuyên gia.",
    ),
)}

TIER_C_EXAMPLES = ("Anopheles", "Ruồi cát", "Ruồi đen", "Ve và bọ chét", "Vi khuẩn", "Tảo độc cần xét nghiệm")

LAYERS = {
    "mosquito_breeding": "Nguy cơ muỗi sinh sản",
    "fly_organic": "Ruồi, rác hữu cơ, vệ sinh",
    "water_anomaly": "Tín hiệu nước bất thường",
    "verified": "Điểm đã xác minh, can thiệp",
}


def catalog() -> dict[str, object]:
    return {
        "groups": [spec.as_dict() for spec in CATALOG.values()],
        "questions": {k: {"label": v["label"], "options": [{"value": o, "label": t} for o, t in v["options"]]}
                      for k, v in QUESTIONS.items()},
        "common_questions": list(COMMON_QUESTIONS),
        "tier_c_examples": list(TIER_C_EXAMPLES),
        "layers": LAYERS,
    }


# --- scoring ------------------------------------------------------------------------

# Shared with the section 12 tables, so one answer means the same thing everywhere.
RAIN = {RecentRain.NONE: 0.2, RecentRain.WITHIN_48H: 0.7, RecentRain.FLOOD_OR_HEAVY: 0.9}
PROXIMITY = {NearbyPlace.FAR: 0.2, NearbyPlace.HOME: 0.6, NearbyPlace.SCHOOL: 0.9, NearbyPlace.PLAYGROUND: 0.9}
CONTACT = {Contact.NONE: 0.1, Contact.PASSING: 0.4, Contact.CHILDREN_NEARBY: 0.8, Contact.DIRECT: 1.0}
AMOUNT = {Amount.FEW: 0.3, Amount.SOME: 0.6, Amount.MANY: 1.0}
BAD_ODORS = (Odor.ROTTEN, Odor.SEWAGE, Odor.CHEMICAL)
UNUSUAL_COLORS = (WaterColor.UNUSUAL_GREEN, WaterColor.BROWN_BLACK, WaterColor.MILKY_WHITE,
                  WaterColor.RAINBOW_SHEEN)

AEDES_WEIGHTS = {"standing_water": 0.35, "artificial_container": 0.25, "organic_waste": 0.15,
                 "recent_rain": 0.15, "residential_proximity": 0.10}
AEDES_TIRE_BONUS = 0.15
# Mosquitoes cannot breed without water, but the brief's weighted sum still reached 0.65
# with standing_water = 0 (container, rain, homes nearby): a site cleaned up on the
# demo only dropped from 0.70 to 0.61. Without standing water the score is capped at the
# section 12 "dry container" value.
AEDES_DRY_CAP = 0.3
AEDES_LONG_STANDING_BONUS = 0.10  # * addition: the form asks it; 7+ days fits a mosquito generation
CULEX_WEIGHTS = {"stagnant_dirty_water": 0.30, "organic_waste": 0.25, "bad_odor": 0.20,
                 "drainage_problem": 0.15, "repeated_reports": 0.10}
FLY_WEIGHTS = {"fly_cluster": 0.35, "organic_waste": 0.30, "dead_animal_or_fecal_waste": 0.20, "bad_odor": 0.15}
WATER_WEIGHTS = {"unusual_color": 0.30, "foam": 0.25, "oil_sheen": 0.25, "bad_odor": 0.20}
# River "Risk score": signs of pollution or decline a person can see or smell.
RIVER_RISK_WEIGHTS = {"oil_sheen": 0.20, "unusual_color": 0.20, "bad_odor": 0.20, "foam": 0.15,
                      "floating_trash": 0.15, "dead_fish": 0.10}
TRASH = {TrashAmount.NONE: 0.0, TrashAmount.LITTLE: 0.5, TrashAmount.LOTS: 1.0}
# River "Human-health relevance": who is near the water, and what is in it.
RIVER_HUMAN_WEIGHTS = {"contact": 0.5, "proximity": 0.3, "hazard": 0.2}
ECO_MIN_PARTS = 2
# * additions: the brief gives no formula for these two groups.
MOSQUITO_WEIGHTS = {"density": 0.5, "near_water": 0.5}
RODENT_WEIGHTS = {"density": 0.6, "near_drain_or_garbage": 0.4}
REPEATED_REPORTS_FULL = 3  # nearby reports of the same group in 7 days for repeated_reports = 1


@dataclass(frozen=True)
class GroupScore:
    value: float | None
    parts: dict[str, float | None]
    known_weight: float
    insufficient: bool
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "value": None if self.value is None else round(self.value, 3),
            "parts": {k: None if v is None else round(v, 3) for k, v in self.parts.items()},
            "known_weight": round(self.known_weight, 2),
            "insufficient": self.insufficient,
            "notes": list(self.notes),
        }


def _weighted(parts: dict[str, float | None], weights: dict[str, float], notes=()) -> GroupScore:
    known = {k: v for k, v in parts.items() if v is not None}
    known_weight = sum(weights[k] for k in known)
    value = sum(weights[k] * v for k, v in known.items()) / known_weight if known_weight else None
    return GroupScore(value, parts, known_weight, known_weight < MIN_KNOWN_WEIGHT, tuple(notes))


def _signal(fusion: Fusion, name: str) -> float | None:
    """How likely the signal is present; a sign only the vision model saw counts as 0."""
    fused = fusion.signals.get(name)
    if fused is None or fused.probability is None:
        return None
    return 0.0 if fused.unconfirmed else fused.probability


def _yes_no(value: YesNo) -> float | None:
    return {YesNo.YES: 1.0, YesNo.NO: 0.0}.get(value)


def _odor(answers: ReportAnswers) -> float | None:
    if answers.odor is Odor.UNKNOWN:
        return None
    return 1.0 if answers.odor in BAD_ODORS else 0.0


def aedes_score(fusion: Fusion, answers: ReportAnswers) -> GroupScore:
    score = _weighted({
        "standing_water": _signal(fusion, "standing_water"),
        "artificial_container": _signal(fusion, "artificial_container"),
        "organic_waste": _signal(fusion, "organic_waste"),
        "recent_rain": RAIN.get(answers.recent_rain),
        "residential_proximity": PROXIMITY.get(answers.nearby_place),
    }, AEDES_WEIGHTS)
    if score.value is None:
        return score
    value, notes = score.value, []
    water = fusion.present("standing_water")
    if not water and value > AEDES_DRY_CAP:
        value = AEDES_DRY_CAP
        notes.append("Không có nước đọng: tối đa 0,3 (vật chứa khô có thể đọng nước sau mưa).")
    if water and fusion.present("used_tire"):
        value += AEDES_TIRE_BONUS
        notes.append("Nước đọng trong lốp xe: +0,15.")
    if water and answers.standing_days is StandingDays.MORE_THAN_7:
        value += AEDES_LONG_STANDING_BONUS
        notes.append("Nước đọng trên 7 ngày, đủ một vòng đời muỗi: +0,10.")
    return GroupScore(min(value, 1.0), score.parts, score.known_weight, score.insufficient, tuple(notes))


def culex_score(fusion: Fusion, answers: ReportAnswers, features: FeatureSet,
                nearby_reports: int | None) -> GroupScore:
    water = _signal(fusion, "standing_water")
    dirty_signs = [answers.odor in (Odor.ROTTEN, Odor.SEWAGE) if answers.odor is not Odor.UNKNOWN else None,
                   answers.water_color is WaterColor.BROWN_BLACK if answers.water_color is not WaterColor.UNKNOWN
                   else None,
                   _yes_no(answers.leaf_litter), fusion.present("organic_waste") or None]
    if water is None or all(sign is None for sign in dirty_signs):
        stagnant_dirty = None
    else:
        stagnant_dirty = water if any(dirty_signs) else 0.0
    drainage = 1.0 if (
        answers.container_type is ContainerType.BLOCKED_DRAIN
        or answers.seen_where is SeenWhere.NEAR_DRAIN
        or features.confidence("drain_inlet") > 0
    ) else 0.0  # the detector looked for drain inlets and found none
    repeated = None if nearby_reports is None else min(nearby_reports / REPEATED_REPORTS_FULL, 1.0)
    return _weighted({
        "stagnant_dirty_water": stagnant_dirty,
        "organic_waste": _signal(fusion, "organic_waste"),
        "bad_odor": _odor(answers),
        "drainage_problem": drainage,
        "repeated_reports": repeated,
    }, CULEX_WEIGHTS)


def fly_score(fusion: Fusion, answers: ReportAnswers) -> GroupScore:
    return _weighted({
        "fly_cluster": _signal(fusion, "fly_cluster"),
        "organic_waste": _signal(fusion, "organic_waste"),
        "dead_animal_or_fecal_waste": _signal(fusion, "dead_animal"),
        "bad_odor": _odor(answers),
    }, FLY_WEIGHTS)


def water_signal_score(fusion: Fusion, answers: ReportAnswers) -> GroupScore:
    if answers.water_color in (WaterColor.UNKNOWN, WaterColor.UNSURE):
        color = None
    else:
        color = 1.0 if answers.water_color in UNUSUAL_COLORS else 0.0
    return _weighted({
        "unusual_color": color,
        "foam": _signal(fusion, "foam"),
        "oil_sheen": _signal(fusion, "oil_sheen"),
        "bad_odor": _odor(answers),
    }, WATER_WEIGHTS)


def mosquito_score(fusion: Fusion, answers: ReportAnswers) -> GroupScore:
    where = {SeenWhere.NEAR_STANDING_WATER: 1.0, SeenWhere.NEAR_DRAIN: 0.7}.get(
        answers.seen_where, None if answers.seen_where is SeenWhere.UNKNOWN else 0.3)
    water = _signal(fusion, "standing_water")
    near_water = None if where is None and water is None else max(where or 0.0, water or 0.0)
    return _weighted({"density": AMOUNT.get(answers.density), "near_water": near_water}, MOSQUITO_WEIGHTS)


def rodent_score(answers: ReportAnswers) -> GroupScore:
    if answers.seen_where is SeenWhere.UNKNOWN:
        near = None
    else:
        near = 1.0 if answers.seen_where in (SeenWhere.NEAR_DRAIN, SeenWhere.NEAR_GARBAGE) else 0.0
    return _weighted({"density": AMOUNT.get(answers.density), "near_drain_or_garbage": near}, RODENT_WEIGHTS)


def _color(answers: ReportAnswers) -> float | None:
    if answers.water_color in (WaterColor.UNKNOWN, WaterColor.UNSURE):
        return None
    return 1.0 if answers.water_color in UNUSUAL_COLORS else 0.0


def river_risk_score(fusion: Fusion, answers: ReportAnswers) -> GroupScore:
    return _weighted({
        "oil_sheen": _signal(fusion, "oil_sheen"),
        "unusual_color": _color(answers),
        "bad_odor": _odor(answers),
        "foam": _signal(fusion, "foam"),
        "floating_trash": TRASH.get(answers.floating_trash),
        "dead_fish": _yes_no(answers.dead_fish),
    }, RIVER_RISK_WEIGHTS)


def river_eco_score(fusion: Fusion, answers: ReportAnswers) -> float | None:
    """Ecological condition, 1 = looks healthy: life in the water, little litter, normal colour and
    smell. A plain mean of what is known; None with fewer than ECO_MIN_PARTS answers."""
    oil = _signal(fusion, "oil_sheen")
    color, odor = _color(answers), _odor(answers)
    parts = [
        {YesNo.YES: 1.0, YesNo.NO: 0.3}.get(answers.aquatic_life),
        {TrashAmount.NONE: 1.0, TrashAmount.LITTLE: 0.6, TrashAmount.LOTS: 0.1}.get(answers.floating_trash),
        None if color is None else 1.0 - 0.8 * color,
        None if odor is None else 1.0 - 0.8 * odor,
        None if oil is None else 1.0 - 0.9 * oil,
        {YesNo.YES: 0.0}.get(answers.dead_fish),
    ]
    known = [part for part in parts if part is not None]
    return sum(known) / len(known) if len(known) >= ECO_MIN_PARTS else None


def river_human_relevance(fusion: Fusion, answers: ReportAnswers) -> float | None:
    hazards = [v for v in (_signal(fusion, "oil_sheen"), _odor(answers), _yes_no(answers.dead_fish)) if v is not None]
    return _weighted({
        "contact": CONTACT.get(answers.contact),
        "proximity": PROXIMITY.get(answers.nearby_place),
        "hazard": max(hazards) if hazards else None,
    }, RIVER_HUMAN_WEIGHTS).value


GOAL_NOTES = {
    ObservationGoal.CHILD_HEALTH: "Mục tiêu sức khỏe trẻ em: nếu có dấu hiệu bất thường, không để trẻ chơi hay "
                                  "lội nước.",
    ObservationGoal.FLOODING: "Mục tiêu ngập lụt: ghi nhận để xem cùng lượng mưa của khu vực.",
    ObservationGoal.BIODIVERSITY: "Mục tiêu đa dạng sinh học: ghi nhận cá, tôm, côn trùng sống giúp theo dõi "
                                  "sinh thái của đoạn kênh.",
}


@dataclass(frozen=True)
class VectorWatchResult:
    group: ObservationGroup
    group_chosen: bool
    scores: dict[str, GroupScore]
    vector_breeding_risk: float | None
    environmental_signal: float | None
    human_contact_risk: float | None
    statement: str
    notes: list[str] = field(default_factory=list)
    eco_score: float | None = None

    @property
    def spec(self) -> GroupSpec:
        return CATALOG[self.group]

    @property
    def group_score(self) -> float | None:
        score = self.scores.get(self.group.value)
        return None if score is None else score.value

    def as_dict(self) -> dict[str, object]:
        spec = self.spec
        return {
            "risk_domain": spec.domain,
            "vector_group": self.group.value,
            "group_label": spec.label,
            "tier": spec.tier,
            "group_chosen": self.group_chosen,
            "layer": spec.layer,
            "group_score": None if self.group_score is None else round(self.group_score, 3),
            "vector_breeding_risk": _round(self.vector_breeding_risk),
            "environmental_signal": _round(self.environmental_signal),
            "human_contact_risk": _round(self.human_contact_risk),
            "eco_score": _round(self.eco_score),
            "scores": {k: v.as_dict() for k, v in self.scores.items()},
            "statement": self.statement,
            "limitation": spec.limitation,
            "verification": spec.verification,
            "notes": self.notes,
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def infer_group(fusion: Fusion) -> ObservationGroup:
    """When the reporter did not pick a group (the /detect demo): the strongest sign wins."""
    if fusion.present("mosquito_larvae"):
        return G.MOSQUITO_ACTIVITY
    if fusion.present("oil_sheen") or fusion.present("foam"):
        return G.WATER_QUALITY_SIGNAL
    if fusion.present("fly_cluster"):
        return G.FLY_CLUSTER
    if fusion.present("dead_animal"):
        return G.DEAD_ANIMAL
    return G.AEDES_BREEDING_RISK


def evaluate(
    fusion: Fusion,
    answers: ReportAnswers,
    features: FeatureSet,
    nearby_reports: int | None = None,
) -> VectorWatchResult:
    chosen = answers.observation_group
    group = chosen or infer_group(fusion)
    scores = {
        G.AEDES_BREEDING_RISK.value: aedes_score(fusion, answers),
        G.CULEX_ENVIRONMENTAL_RISK.value: culex_score(fusion, answers, features, nearby_reports),
        G.FLY_CLUSTER.value: fly_score(fusion, answers),
        G.WATER_QUALITY_SIGNAL.value: water_signal_score(fusion, answers),
    }
    if group is G.MOSQUITO_ACTIVITY:
        scores[group.value] = mosquito_score(fusion, answers)
    if group is G.RODENT_SIGHTING:
        scores[group.value] = rodent_score(answers)
    eco = human = None
    if group is G.RIVER_HEALTH:
        scores[group.value] = river_risk_score(fusion, answers)
        eco = river_eco_score(fusion, answers)
        human = river_human_relevance(fusion, answers)

    vector_groups = (G.AEDES_BREEDING_RISK.value, G.CULEX_ENVIRONMENTAL_RISK.value, G.MOSQUITO_ACTIVITY.value)
    vector_values = [scores[g].value for g in vector_groups
                     if g in scores and scores[g].value is not None and not scores[g].insufficient]
    water = scores[G.WATER_QUALITY_SIGNAL.value]

    spec = CATALOG[group]
    primary = scores.get(group.value)
    notes = []
    if not chosen:
        notes.append(f"Người báo chưa chọn nhóm; hệ thống đoán là '{spec.label}'.")
    if group is G.RIVER_HEALTH and answers.observation_goal in GOAL_NOTES:
        notes.append(GOAL_NOTES[answers.observation_goal])
    if group is G.RIVER_HEALTH and (primary is None or primary.value is None):
        # No answer about the water yet: say nothing about it rather than guess.
        statement = ("Chưa đủ câu trả lời để đánh giá mặt nước; hãy trả lời màu, mùi, váng dầu, rác nổi "
                     "và cá, tôm có sống không.")
    elif primary is None or primary.value is None:
        # Recorded-only groups, or a chosen group with no answers yet: the report is the finding.
        statement = spec.positive
    else:
        statement = spec.positive if primary.value >= POSITIVE_AT else spec.negative
        if primary.insufficient:
            notes.append("Chưa đủ dữ liệu cho điểm nhóm này; nên hỏi thêm người báo.")

    return VectorWatchResult(
        group=group,
        group_chosen=chosen is not None,
        scores=scores,
        vector_breeding_risk=max(vector_values) if vector_values else None,
        environmental_signal=None if water.insufficient else water.value,
        human_contact_risk=human if group is G.RIVER_HEALTH else CONTACT.get(answers.contact),
        statement=statement,
        notes=notes,
        eco_score=eco,
    )
