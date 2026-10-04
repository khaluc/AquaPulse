"""Merge what the reporter said with what the models saw (flow steps O and P).

The plan (section 11) weights sources 0.5 YOLO / 0.3 vision model / 0.2 reporter and
adds `user_reliability` as a *value*. That makes "no water" and "water" from the same
trusted reporter score identically, and it cannot notice the plan's own conflict
example (reporter: no water; YOLO 0.82; Gemini 0.79 -> 0.75, no conflict raised).

Here each source *votes* on each signal - a probability that the signal is present -
and reliability scales how much the reporter's vote *weighs*. Weights are the plan's,
renormalised over the sources that can actually see a given signal: the detector
cannot see organic waste, so it neither helps nor drags that signal down.

Confidence C then answers "how much should we trust this assessment", from how well
the sources agree, how many of them took part, and the photo's quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from app.features import FeatureSet
from app.vision import VisionAnalysis

# --- what the reporter can tell us (section 4 schema, extended by section 12) ------


class YesNo(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class ContainerType(StrEnum):
    USED_TIRE = "used_tire"
    BUCKET_OR_JAR = "bucket_or_jar"
    FLOWER_POT = "flower_pot"
    BOTTLE_OR_CAN = "bottle_or_can"
    COCONUT_SHELL = "coconut_shell"
    BLOCKED_DRAIN = "blocked_drain"
    PLASTIC_BOX = "plastic_box"
    TREE_HOLE = "tree_hole"          # natural, but a classic Aedes site: counted as a container
    PUDDLE = "puddle"
    POND_OR_CANAL = "pond_or_canal"
    OTHER = "other"
    NONE = "none"
    UNKNOWN = "unknown"


# Section 4 asked one yes/no question ("gần nhà ở, trường học hoặc khu vui chơi?") but
# section 12 scores home 0.6 and school/playground 0.9, so the answer must say which.
class NearbyPlace(StrEnum):
    FAR = "far"
    HOME = "home"
    SCHOOL = "school"
    PLAYGROUND = "playground"
    UNKNOWN = "unknown"


# Section 12 distinguishes four levels of contact; section 4 only had two yes/no fields.
class Contact(StrEnum):
    NONE = "none"
    PASSING = "passing"
    CHILDREN_NEARBY = "children_nearby"
    DIRECT = "direct"
    UNKNOWN = "unknown"


# Section 4 had no rain question; section 12 needs it. Later a weather API can fill it.
class RecentRain(StrEnum):
    NONE = "none"
    WITHIN_48H = "within_48h"
    FLOOD_OR_HEAVY = "flood_or_heavy"
    UNKNOWN = "unknown"


class Odor(StrEnum):
    NONE = "none"
    ROTTEN = "rotten"
    SEWAGE = "sewage"
    CHEMICAL = "chemical"  # section 16: always goes to a person
    UNKNOWN = "unknown"


# --- Vector Watch module: which group the reporter is describing, and its form ------


class ObservationGroup(StrEnum):
    AEDES_BREEDING_RISK = "aedes_breeding_risk"            # tier A
    MOSQUITO_ACTIVITY = "mosquito_activity"                # tier A
    FLY_CLUSTER = "fly_cluster"                            # tier A
    WATER_QUALITY_SIGNAL = "water_quality_signal"          # tier A
    CULEX_ENVIRONMENTAL_RISK = "culex_environmental_risk"  # tier B
    RODENT_SIGHTING = "rodent_sighting"                    # tier B
    DEAD_ANIMAL = "dead_animal"                            # tier B
    AQUATIC_SPECIES = "aquatic_species"                    # tier B (freshwater snails)
    OTHER_REFERENCE = "other_reference"                    # tier C: recorded, not scored
    RIVER_HEALTH = "river_health"                          # the river "health station" (AquaPulse brief)


class ObservationGoal(StrEnum):
    """What the reporter cares about; it changes the explanation and the advice, not the score."""
    ENVIRONMENT = "environment"
    CHILD_HEALTH = "child_health"
    FLOODING = "flooding"
    BIODIVERSITY = "biodiversity"
    UNKNOWN = "unknown"


class TrashAmount(StrEnum):
    NONE = "none"
    LITTLE = "little"
    LOTS = "lots"
    UNKNOWN = "unknown"


class StandingDays(StrEnum):
    LESS_THAN_1 = "lt_1"
    DAYS_1_3 = "d1_3"
    DAYS_4_7 = "d4_7"
    MORE_THAN_7 = "gt_7"  # long enough for a mosquito generation
    UNKNOWN = "unknown"


class InsectSeen(StrEnum):
    ADULT_MOSQUITO = "adult_mosquito"
    SMALL_ORGANISMS_IN_WATER = "small_organisms_in_water"
    MANY_FLYING_INSECTS = "many_flying_insects"
    UNSURE = "unsure"
    UNKNOWN = "unknown"


class SeenWhere(StrEnum):
    NEAR_STANDING_WATER = "near_standing_water"
    NEAR_DRAIN = "near_drain"
    NEAR_GARBAGE = "near_garbage"
    INDOORS = "indoors"
    OUTDOORS = "outdoors"
    UNKNOWN = "unknown"


class Amount(StrEnum):
    FEW = "few"
    SOME = "some"
    MANY = "many"
    UNKNOWN = "unknown"


class WaterColor(StrEnum):
    NORMAL = "normal"
    UNUSUAL_GREEN = "unusual_green"
    BROWN_BLACK = "brown_black"
    MILKY_WHITE = "milky_white"
    RAINBOW_SHEEN = "rainbow_sheen"
    UNSURE = "unsure"
    UNKNOWN = "unknown"


class ReporterLevel(StrEnum):
    NEW = "new"
    TRUSTED = "trusted"      # several earlier reports were verified
    VOLUNTEER = "volunteer"  # verified volunteer


REPORTER_RELIABILITY: dict[ReporterLevel, float] = {
    ReporterLevel.NEW: 0.5,
    ReporterLevel.TRUSTED: 0.8,
    ReporterLevel.VOLUNTEER: 1.0,
}

OBSERVATION_TYPES = {
    "standing_water", "mosquito_activity", "mosquito_larvae", "fly_cluster", "foam",
    "oil_sheen", "bad_odor", "organic_waste", "dead_animal", "rat_sighting",
}


class ReportAnswers(BaseModel):
    """Quick answers from the reporter. Every field is optional: people skip questions."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    observation_types: list[str] = []
    water_stagnant: YesNo = YesNo.UNKNOWN
    container_type: ContainerType = ContainerType.UNKNOWN
    organic_waste: YesNo = YesNo.UNKNOWN
    moving_organisms: YesNo = YesNo.UNKNOWN  # "Có thấy sinh vật nhỏ chuyển động không?"
    nearby_place: NearbyPlace = NearbyPlace.UNKNOWN
    contact: Contact = Contact.UNKNOWN
    recent_rain: RecentRain = RecentRain.UNKNOWN
    odor: Odor = Odor.UNKNOWN
    reporter_level: ReporterLevel = ReporterLevel.NEW
    # Vector Watch: the group chosen first, then only that group's questions are asked.
    observation_group: ObservationGroup | None = None
    standing_days: StandingDays = StandingDays.UNKNOWN
    leaf_litter: YesNo = YesNo.UNKNOWN
    insect_seen: InsectSeen = InsectSeen.UNKNOWN
    seen_where: SeenWhere = SeenWhere.UNKNOWN
    density: Amount = Amount.UNKNOWN            # mosquitoes, flies or rodents seen
    dead_animal_or_feces: YesNo = YesNo.UNKNOWN
    near_food_place: YesNo = YesNo.UNKNOWN      # market, eatery
    water_color: WaterColor = WaterColor.UNKNOWN
    foam: YesNo = YesNo.UNKNOWN
    dead_fish_or_animal_contact: YesNo = YesNo.UNKNOWN
    # River and canal form: only what people can see or smell.
    observation_goal: ObservationGoal = ObservationGoal.UNKNOWN
    oil_sheen: YesNo = YesNo.UNKNOWN            # "Có váng dầu, ánh cầu vồng trên mặt nước không?"
    floating_trash: TrashAmount = TrashAmount.UNKNOWN
    aquatic_life: YesNo = YesNo.UNKNOWN         # "Có thấy cá, tôm, côn trùng sống không?"
    dead_fish: YesNo = YesNo.UNKNOWN            # "Có cá chết nổi không?"
    overflow: YesNo = YesNo.UNKNOWN             # "Nước tràn bờ hoặc ngập đường gần đó?"

    @field_validator("observation_types")
    @classmethod
    def _known_types(cls, value: list[str]) -> list[str]:
        unknown = set(value) - OBSERVATION_TYPES
        if unknown:
            raise ValueError(f"observation_types không hợp lệ: {sorted(unknown)}")
        return value


# --- fusion ------------------------------------------------------------------------

SIGNALS: tuple[str, ...] = (
    "standing_water", "artificial_container", "used_tire", "organic_waste",
    "oil_sheen", "foam", "mosquito_larvae", "fly_cluster", "dead_animal",
)

# The plan's source weights. The reporter's weight is 0.2 at the reliability of a new
# reporter (0.5) and grows with reliability, instead of reliability being a vote.
SOURCE_WEIGHT = {"detector": 0.5, "vision": 0.3, "reporter": 0.2}
BASE_RELIABILITY = REPORTER_RELIABILITY[ReporterLevel.NEW]

PRESENT_AT = 0.5

# When a model looked and found nothing, that is weak evidence of absence, not proof:
# the detector misses ~5% of photos with containers, the water model ~35% of water.
DETECTOR_ABSENT_VOTE = 0.15
WATER_MODEL_ABSENT_VOTE = 0.35

# Vision model votes by stated certainty. Symmetric around 0.5, so "not seen, low
# certainty" barely moves the result and "seen, high certainty" moves it most.
VISION_VOTE = {
    (True, "high"): 0.85, (True, "medium"): 0.7, (True, "low"): 0.55,
    (False, "low"): 0.45, (False, "medium"): 0.3, (False, "high"): 0.15,
}

CONTAINER_CLASSES = ("used_tire", "plastic_container", "plant_pot", "coconut_shell", "drain_inlet")

# Signals the models observe well enough for a disagreement with the reporter to mean
# something. Nobody expects a phone photo to show larvae, so the models staying silent
# about larvae is not a conflict with a reporter who saw them.
CONFLICT_SIGNALS = ("standing_water", "artificial_container")
CONFLICT_AI_YES = 0.7
CONFLICT_AI_NO = 0.25


@dataclass(frozen=True)
class FusedSignal:
    probability: float | None          # None when no source could observe it
    votes: dict[str, float]
    present: bool                      # counts towards the risk score
    unconfirmed: bool = False          # only the vision model saw it: flagged, not scored

    def as_dict(self) -> dict[str, object]:
        return {
            "probability": None if self.probability is None else round(self.probability, 3),
            "present": self.present,
            "unconfirmed": self.unconfirmed,
            "votes": {k: round(v, 3) for k, v in self.votes.items()},
        }


REPORTER_VS_MODELS = "reporter_vs_models"  # ask the reporter to confirm (section 11)
BETWEEN_MODELS = "between_models"          # a person must look (section 16)


@dataclass(frozen=True)
class Conflict:
    signal: str
    reporter_said: str
    models_said: str
    message: str
    kind: str = REPORTER_VS_MODELS

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class Fusion:
    signals: dict[str, FusedSignal]
    conflicts: list[Conflict]
    confidence: float
    confidence_parts: dict[str, float]
    sources_used: list[str]
    reporter_reliability: float
    notes: list[str] = field(default_factory=list)

    def present(self, name: str) -> bool:
        return self.signals[name].present

    @property
    def reporter_conflicts(self) -> list[Conflict]:
        return [c for c in self.conflicts if c.kind == REPORTER_VS_MODELS]

    @property
    def model_conflicts(self) -> list[Conflict]:
        return [c for c in self.conflicts if c.kind == BETWEEN_MODELS]

    @property
    def unconfirmed(self) -> list[str]:
        return [name for name, s in self.signals.items() if s.unconfirmed]

    def as_dict(self) -> dict[str, object]:
        return {
            "signals": {name: s.as_dict() for name, s in self.signals.items()},
            "conflicts": [c.as_dict() for c in self.conflicts],
            "confidence": round(self.confidence, 3),
            "confidence_parts": {k: round(v, 3) for k, v in self.confidence_parts.items()},
            "sources_used": self.sources_used,
            "reporter_reliability": self.reporter_reliability,
            "notes": self.notes,
        }


def _reporter_votes(answers: ReportAnswers) -> dict[str, float]:
    votes: dict[str, float] = {}

    def set_yes_no(signal: str, value: YesNo) -> None:
        if value is YesNo.YES:
            votes[signal] = 1.0
        elif value is YesNo.NO:
            votes[signal] = 0.0

    set_yes_no("standing_water", answers.water_stagnant)
    set_yes_no("organic_waste", answers.organic_waste)
    set_yes_no("mosquito_larvae", answers.moving_organisms)
    set_yes_no("foam", answers.foam)
    set_yes_no("dead_animal", answers.dead_animal_or_feces)
    if answers.leaf_litter is YesNo.YES and "organic_waste" not in votes:
        votes["organic_waste"] = 1.0  # rotting leaves in the water are organic matter
    if answers.insect_seen is InsectSeen.SMALL_ORGANISMS_IN_WATER:
        votes["mosquito_larvae"] = 1.0
    set_yes_no("oil_sheen", answers.oil_sheen)
    if answers.dead_fish is YesNo.YES:
        votes["dead_animal"] = 1.0  # a "no" here says nothing about carcasses on the bank
    if answers.water_color is WaterColor.RAINBOW_SHEEN:
        votes["oil_sheen"] = 1.0
    if answers.observation_group is ObservationGroup.FLY_CLUSTER and answers.density is not Amount.UNKNOWN:
        votes["fly_cluster"] = {Amount.FEW: 0.4, Amount.SOME: 1.0, Amount.MANY: 1.0}[answers.density]

    container = answers.container_type
    if container is ContainerType.NONE:
        votes["artificial_container"] = 0.0
        votes["used_tire"] = 0.0
    elif container not in (ContainerType.UNKNOWN, ContainerType.PUDDLE, ContainerType.POND_OR_CANAL):
        votes["artificial_container"] = 1.0
        votes["used_tire"] = 1.0 if container is ContainerType.USED_TIRE else 0.0

    # Choosing an observation type is a "yes" for that signal.
    for observed in answers.observation_types:
        if observed in SIGNALS:
            votes[observed] = 1.0
    return votes


def _detector_votes(features: FeatureSet) -> dict[str, float]:
    containers = [features.confidence(name) for name in CONTAINER_CLASSES]
    votes = {
        "artificial_container": max(containers) if any(containers) else DETECTOR_ABSENT_VOTE,
        "used_tire": features.confidence("used_tire") or DETECTOR_ABSENT_VOTE,
    }
    if features.water_confidence is not None:
        # The water model ran: its best in-container patch, or weak evidence of absence.
        votes["standing_water"] = features.water_confidence or WATER_MODEL_ABSENT_VOTE
    return votes


def _vision_votes(vision: VisionAnalysis) -> dict[str, float]:
    votes = {
        name: VISION_VOTE.get((signal.detected, signal.certainty), 0.5)
        for name, signal in vision.signals.items()
    }
    container_type = vision.signals["artificial_container"].container_type
    if container_type == "used_tire":
        votes["used_tire"] = votes["artificial_container"]
    return votes


def fuse(
    features: FeatureSet,
    answers: ReportAnswers | None,
    vision: VisionAnalysis | None,
    quality_warnings: int = 0,
    vision_expected: bool | None = None,
) -> Fusion:
    """`vision_expected`: whether the vision model was meant to run for this report.

    Coverage is counted against the sources that were expected, not all three: with the
    vision model switched off, no report could reach C > 0.85 (the best was 0.833), so
    section 16's "show the preliminary result" branch never happened.
    """
    answers = answers or ReportAnswers()
    reliability = REPORTER_RELIABILITY[answers.reporter_level]
    sources: dict[str, dict[str, float]] = {}
    if features.detector_ran:
        sources["detector"] = _detector_votes(features)
    if vision is not None:
        sources["vision"] = _vision_votes(vision)
    reporter = _reporter_votes(answers)
    if reporter:
        sources["reporter"] = reporter

    weights = dict(SOURCE_WEIGHT)
    weights["reporter"] = SOURCE_WEIGHT["reporter"] * reliability / BASE_RELIABILITY

    fused: dict[str, FusedSignal] = {}
    for signal in SIGNALS:
        votes = {src: v[signal] for src, v in sources.items() if signal in v}
        if not votes:
            fused[signal] = FusedSignal(None, {}, False)
            continue
        total = sum(weights[src] for src in votes)
        probability = sum(weights[src] * vote for src, vote in votes.items()) / total
        likely = probability >= PRESENT_AT
        # The vision model alone never raises the score: on real photos Qwen3-VL-2B
        # claimed oil sheen on clean water, which alone pushed a report to red.
        backed = any(vote >= PRESENT_AT for src, vote in votes.items() if src != "vision")
        fused[signal] = FusedSignal(probability, votes, likely and backed, likely and not backed)

    conflicts = _conflicts(fused)

    # Agreement: 1 minus the spread of votes, on signals that at least two sources saw
    # and at least one says is there. Sources agreeing that there is no oil, no larvae,
    # no waste is cheap: counted in, it lifted a report whose reporter contradicted both
    # models on water and on the container to C = 0.78.
    spreads = [
        max(s.votes.values()) - min(s.votes.values())
        for s in fused.values()
        if len(s.votes) >= 2 and max(s.votes.values()) >= PRESENT_AT
    ]
    agreement = 1 - sum(spreads) / len(spreads) if spreads else 0.5
    # Coverage counts the sources that were meant to run: the reporter, the detector when it
    # was used, and the vision model when it was asked for.
    expected = 1 + features.detector_ran + (vision is not None if vision_expected is None
                                            else bool(vision_expected))
    coverage = len(sources) / expected
    quality = 1.0 if quality_warnings == 0 else 0.8
    parts = {"agreement": agreement, "coverage": coverage, "image_quality": quality}
    confidence = 0.5 * agreement + 0.3 * coverage + 0.2 * quality

    notes = []
    if "reporter" not in sources:
        notes.append("Người báo chưa trả lời câu hỏi nhanh nào; chỉ dựa vào AI.")
    if vision is None:
        notes.append("Model mô tả bối cảnh không chạy; rác hữu cơ, váng dầu, bọt chỉ dựa vào người báo.")
    if not features.detector_ran:
        notes.append("Không chạy model nhận diện vật chứa cho ảnh này: nó chỉ được huấn luyện cho vật chứa "
                     "đọng nước, không dùng cho mặt nước sông, kênh.")

    return Fusion(fused, conflicts, confidence, parts, list(sources), reliability, notes)


def _conflicts(fused: dict[str, FusedSignal]) -> list[Conflict]:
    found = []
    for signal in CONFLICT_SIGNALS:
        votes = fused[signal].votes
        said = votes.get("reporter")
        model_votes = [v for src, v in votes.items() if src != "reporter"]
        label = "nước đọng" if signal == "standing_water" else "vật chứa"
        if said is not None and model_votes:
            if said == 0.0 and max(model_votes) >= CONFLICT_AI_YES:
                found.append(Conflict(signal, "không", "có",
                                      f"Người báo nói không có {label}, nhưng AI thấy có. Cần người báo xác nhận."))
            elif said == 1.0 and max(model_votes) <= CONFLICT_AI_NO:
                found.append(Conflict(signal, "có", "không",
                                      f"Người báo nói có {label}, nhưng AI không thấy. Cần người báo xác nhận."))

        # Section 16: the detector (or water model) and the vision model disagreeing.
        detector, vision = votes.get("detector"), votes.get("vision")
        if detector is not None and vision is not None and (
            (detector >= CONFLICT_AI_YES and vision <= CONFLICT_AI_NO)
            or (vision >= CONFLICT_AI_YES and detector <= CONFLICT_AI_NO)
        ):
            found.append(Conflict(
                signal, "-", f"model nhận diện {detector:.2f}, model mô tả {vision:.2f}",
                f"Hai model mâu thuẫn về {label}. Cần người xác minh.", BETWEEN_MODELS,
            ))
    return found
