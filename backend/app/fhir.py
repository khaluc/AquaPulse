"""FHIR R4 export (track 7 of the brief): Observation, Location and RiskAssessment in a Bundle.

A citizen report becomes an Observation (status preliminary until verified), a canal
segment a Location (with its line as the standard location-boundary-geojson extension),
and a segment passport a RiskAssessment whose basis is the reports. No reporter id is
exported and point positions are rounded as on the public map (about 110 m).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

CODES = "urn:aquapulse:code"
STATUS = {"verified": "final", "dismissed": "cancelled"}
ANSWER_LABELS = {
    "water_color": "Màu nước", "odor": "Mùi", "foam": "Bọt", "oil_sheen": "Váng dầu",
    "floating_trash": "Rác nổi", "aquatic_life": "Cá, tôm, côn trùng sống", "dead_fish": "Cá chết",
    "overflow": "Nước tràn bờ", "contact": "Tiếp xúc", "nearby_place": "Gần nơi", "recent_rain": "Mưa gần đây",
    "observation_goal": "Mục tiêu quan sát",
}


def _concept(code: str, text: str) -> dict[str, Any]:
    return {"coding": [{"system": CODES, "code": code, "display": text}], "text": text}


def _decimal(code: str, text: str, value: float | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"code": _concept(code, text), "valueQuantity": {"value": round(value, 3), "unit": "1",
                                                            "system": "http://unitsofmeasure.org", "code": "1"}}


def location_for_segment(segment: dict[str, Any]) -> dict[str, Any]:
    geojson = json.dumps(segment["geometry"], ensure_ascii=False).encode()
    return {
        "resourceType": "Location",
        "id": segment["id"],
        "status": "active",
        "name": f"{segment['waterway']} · {segment['name']}",
        "physicalType": {"text": "Đoạn kênh"},
        "extension": [{
            "url": "http://hl7.org/fhir/StructureDefinition/location-boundary-geojson",
            "valueAttachment": {"contentType": "application/geo+json", "data": base64.b64encode(geojson).decode()},
        }],
    }


def observation(row: dict[str, Any], segment_id: str | None) -> dict[str, Any]:
    answers = row.get("answers") or {}
    components = [
        {"code": _concept(k, ANSWER_LABELS[k]), "valueCodeableConcept": {"text": str(v)}}
        for k, v in answers.items() if k in ANSWER_LABELS and v not in (None, "unknown")
    ]
    components += [c for c in (
        _decimal("risk-score", "Risk score", row.get("group_score")),
        _decimal("eco-score", "Eco score", row.get("eco_score")),
        _decimal("confidence", "Confidence score", row.get("confidence")),
        _decimal("human-health", "Human-health relevance", row.get("human_contact_risk")),
    ) if c]
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": str(row["id"]),
        "status": STATUS.get(row["status"], "preliminary"),
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                  "code": "survey", "display": "Survey"}],
                      "text": "Quan sát môi trường của người dân"}],
        "code": _concept(row.get("vector_group") or "observation", "AquaPulse citizen observation"),
        "effectiveDateTime": row["observed_at"].isoformat(),
        "interpretation": [{"text": f"Mức {row['level']} (sàng lọc, không phải kết luận xét nghiệm)"}],
        "component": components,
        "note": [{"text": "Đo bằng quan sát của người dân và model ảnh; không phải kết quả phòng thí nghiệm."}],
    }
    if segment_id:
        resource["subject"] = {"reference": f"Location/{segment_id}"}
    else:
        resource["extension"] = [{"url": "http://hl7.org/fhir/StructureDefinition/geolocation", "extension": [
            {"url": "latitude", "valueDecimal": round(row["latitude"], 3)},
            {"url": "longitude", "valueDecimal": round(row["longitude"], 3)}]}]
    return resource


def risk_assessment(passport: dict[str, Any], observation_ids: list[str]) -> dict[str, Any]:
    ix = passport["indices"]
    seg = passport["segment"]
    return {
        "resourceType": "RiskAssessment",
        "id": f"passport-{seg['id']}",
        "status": "preliminary",
        "subject": {"reference": f"Location/{seg['id']}"},
        "occurrenceDateTime": datetime.now(UTC).isoformat(),
        "method": {"text": "AquaPulse rule engine trên quan sát của người dân (không dùng mô hình dự báo)"},
        "basis": [{"reference": f"Observation/{i}"} for i in observation_ids],
        "prediction": [{
            "outcome": {"text": "Dấu hiệu ô nhiễm hoặc suy giảm quan sát được"},
            **({"probabilityDecimal": ix["risk"]} if ix["risk"] is not None else {}),
            "qualitativeRisk": {"text": f"Mức {passport['level']}"},
            "rationale": " ".join(passport["explanation"]),
        }],
        "mitigation": " ".join(passport["actions"]) or None,
        "note": [{"text": passport["limits"]}],
    }


def bundle(resources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": datetime.now(UTC).isoformat(),
        "entry": [{"fullUrl": f"urn:aquapulse:{r['resourceType']}/{r['id']}", "resource": r} for r in resources],
    }
