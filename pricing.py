"""Turn findings into money.

Deterministic on purpose. Given the same findings this returns the same numbers
every time, and every number traces back to a line in rates.json. Nothing here
asks a model anything.
"""

import json
from pathlib import Path

RATES_PATH = Path(__file__).parent / "rates.json"


def load_rates(path=RATES_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _round_to(value, step=5):
    return int(round(value / step) * step)


def price_finding(finding, rates):
    """One repair line: labour + paint + parts, as a low/high band."""
    action = rates["actions"][finding["repair_action"]]
    hours = action["hours"][finding["severity"]]

    labour = hours * rates["labour_rate_per_hour"]
    paint = action["paint_panels"] * rates["paint_material_per_panel"]

    if action["needs_part"]:
        part_low, part_high = rates["parts"].get(
            finding["part"], rates["parts"]["other"])
    else:
        part_low = part_high = 0

    return {
        "part": finding["part"],
        "part_label": finding["part_label"],
        "operation": action["label"],
        "severity": finding["severity"],
        "hours": hours,
        "labour": _round_to(labour),
        "paint": _round_to(paint),
        "parts_low": _round_to(part_low),
        "parts_high": _round_to(part_high),
        "low": _round_to(labour + paint + part_low),
        "high": _round_to(labour + paint + part_high),
        "needs_quote": finding["repair_action"] == "structural_inspection",
    }


def estimate(findings, rates=None):
    """Full estimate for a set of findings."""
    rates = rates or load_rates()
    lines = [price_finding(f, rates) for f in findings]

    subtotal_low = sum(line["low"] for line in lines)
    subtotal_high = sum(line["high"] for line in lines)

    sundries_low = subtotal_low * rates["sundries_percent"] / 100
    sundries_high = subtotal_high * rates["sundries_percent"] / 100

    pre_tax_low = subtotal_low + sundries_low
    pre_tax_high = subtotal_high + sundries_high

    tax_low = pre_tax_low * rates["tax_percent"] / 100
    tax_high = pre_tax_high * rates["tax_percent"] / 100

    return {
        "currency": rates["currency"],
        "lines": lines,
        "subtotal_low": _round_to(subtotal_low),
        "subtotal_high": _round_to(subtotal_high),
        "sundries_percent": rates["sundries_percent"],
        "sundries_low": _round_to(sundries_low),
        "sundries_high": _round_to(sundries_high),
        "tax_percent": rates["tax_percent"],
        "tax_low": _round_to(tax_low),
        "tax_high": _round_to(tax_high),
        "total_low": _round_to(pre_tax_low + tax_low),
        "total_high": _round_to(pre_tax_high + tax_high),
        "labour_rate": rates["labour_rate_per_hour"],
        "total_hours": round(sum(line["hours"] for line in lines), 1),
        # A structural line means the real figure comes from a workshop, not us.
        "needs_workshop_quote": any(line["needs_quote"] for line in lines),
    }
