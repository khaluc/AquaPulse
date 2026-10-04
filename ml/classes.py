"""YOLO class registry for AquaPulse datasets.

Append new classes at the end only: reordering or removing an entry changes
class ids and silently breaks every model trained on the old order.
"""

DETECT_CLASSES: list[str] = [
    "used_tire",
    "plastic_container",
    "plant_pot",
    "coconut_shell",
    "drain_inlet",
]

WATER_SEG_CLASSES: list[str] = [
    "water",
]
