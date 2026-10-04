"""Dashboard data for the Vector Watch module: four map layers and a summary table.

Layers (module brief):
    mosquito_breeding  Aedes, Culex and mosquito/larvae reports
    fly_organic        flies, rodents, dead animals: sanitation
    water_anomaly      unusual water surface, aquatic species
    verified           reports a person verified, and places cleaned up since

Coordinates are rounded to 4 decimals (about 11 m) so the dashboard does not pin a
reporter's exact doorstep. Dismissed reports are left out. Reference-only reports
appear in the table without a risk score and join the verified layer after review.
"""

from __future__ import annotations

from typing import Any

from app.fusion import ObservationGroup
from app.vector_watch import CATALOG, LAYERS

COORDINATE_DECIMALS = 4

SIGNAL_LABELS = {
    "standing_water": "nước đọng", "artificial_container": "vật chứa", "used_tire": "lốp xe",
    "organic_waste": "rác hữu cơ", "oil_sheen": "váng dầu", "foam": "bọt",
    "mosquito_larvae": "nghi lăng quăng", "fly_cluster": "cụm ruồi", "dead_animal": "xác động vật",
}

STATUS_LABELS = {
    "needs_verification": "Cần xác minh",
    "needs_confirmation": "Chờ người báo xác nhận",
    "published": "Theo dõi",
    "pending": "Theo dõi",
    "verified": "Đã xác minh",
}


def status_label(row: dict[str, Any]) -> str:
    if row["status"] == "needs_verification" and row["vector_group"] == ObservationGroup.WATER_QUALITY_SIGNAL:
        return "Cần lấy mẫu"
    if row["status"] == "verified" and row["treated_at"] is not None:
        return "Đã xác minh, đã xử lý"
    return STATUS_LABELS.get(row["status"], row["status"])


def layer_of(row: dict[str, Any]) -> str:
    if row["vector_group"]:
        return CATALOG[ObservationGroup(row["vector_group"])].layer
    return "mosquito_breeding"  # reports stored before the module existed were all water/containers


def _feature(row: dict[str, Any]) -> dict[str, Any]:
    group = ObservationGroup(row["vector_group"]) if row["vector_group"] else None
    after = row["group_score_after"]
    before = (None if group == ObservationGroup.OTHER_REFERENCE else
              row["group_score"] if row["group_score"] is not None else row["risk"])
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(row["longitude"], COORDINATE_DECIMALS),
                                                       round(row["latitude"], COORDINATE_DECIMALS)]},
        "properties": {
            "id": str(row["id"]),
            "group": group.value if group else None,
            "group_label": CATALOG[group].label if group else "Nước đọng, vật chứa",
            "tier": CATALOG[group].tier if group else "A",
            "score": before,
            "score_after": after,
            "current_score": after if after is not None else before,
            "confidence": row["confidence"],
            "level": row["level"],
            "status": row["status"],
            "status_label": status_label(row),
            "signals": [SIGNAL_LABELS.get(s, s) for s in row["signals"]],
            "statement": row["statement"],
            "observed_at": row["observed_at"].isoformat(),
            "treated": row["treated_at"] is not None,
            "is_demo": row["is_demo"],
        },
    }


def build(rows: list[dict[str, Any]], hotspots: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    visible = [row for row in rows if row["status"] != "dismissed"]
    layers: dict[str, list[dict[str, Any]]] = {name: [] for name in LAYERS}
    features = []
    for row in visible:
        feature = _feature(row)
        features.append(feature)
        layer = layer_of(row)
        if layer in layers:
            layers[layer].append(feature)
        if row["status"] == "verified" or row["treated_at"] is not None:
            layers["verified"].append(feature)

    table = sorted(
        ({"id": f["properties"]["id"],
          "area": f"{f['geometry']['coordinates'][1]:.4f}, {f['geometry']['coordinates'][0]:.4f}",
          "group": f["properties"]["group_label"],
          "signals": ", ".join(f["properties"]["signals"]) or "-",
          "score": f["properties"]["current_score"],
          "score_before": f["properties"]["score"] if f["properties"]["treated"] else None,
          "confidence": f["properties"]["confidence"],
          "status": f["properties"]["status_label"]}
         for f in features),
        key=lambda r: -(r["score"] or 0),
    )
    return {
        "layers": {
            name: {"label": label, "count": len(layers[name]),
                   "geojson": {"type": "FeatureCollection", "features": layers[name]}}
            for name, label in LAYERS.items()
        },
        "hotspots": hotspots,
        "table": table,
        "reports": len(visible),
        "dismissed": len(rows) - len(visible),
    }
