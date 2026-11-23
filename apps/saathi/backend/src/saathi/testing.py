"""Test helpers: a profile with every question answered, for tests that need "nothing left to ask"."""

from __future__ import annotations

from typing import Any

from .profile import field_descriptors

_DEFAULTS = {"bool": False, "int": 0, "number": 0.0, "text": "patna", "state": "bihar"}
FARMER = {
    "age": 32, "gender": "male", "occupation": "farmer", "residence": "rural", "social_category": "general",
    "annual_family_income": 90_000, "has_bank_account": True, "owns_cultivable_land": True,
    "land_holding_hectares": 1.0, "ration_card": "none", "has_electricity_connection": True,
}  # fmt: skip


def answered(**overrides: Any) -> dict[str, Any]:
    """Every profile field with a plain "no" / zero / first-choice answer, then the overrides."""
    values = {
        f["name"]: f["options"][0] if f["type"] == "enum" else _DEFAULTS[f["type"]] for f in field_descriptors()
    }
    values.pop("disability_percent")  # 0 would be a real answer ("no disability"); keep it simple
    values["has_disability"] = False
    return {**values, **overrides}
