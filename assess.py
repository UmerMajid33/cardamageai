"""What the model is asked to see, and what shape the answer must take.

The model's job is perception only: which part, what kind of damage, how bad,
and what operation fixes it. It is never asked for a price. Pricing happens in
pricing.py, from rates.json, so every figure in an estimate is traceable to a
line someone can argue with.
"""

PARTS = [
    "front_bumper", "rear_bumper", "bonnet", "boot_lid",
    "front_left_door", "front_right_door", "rear_left_door", "rear_right_door",
    "front_left_fender", "front_right_fender",
    "rear_left_quarter", "rear_right_quarter", "roof",
    "windscreen", "rear_windscreen", "side_window",
    "headlight_left", "headlight_right", "taillight_left", "taillight_right",
    "wing_mirror_left", "wing_mirror_right", "grille",
    "wheel", "tyre", "side_skirt", "underbody", "other",
]

ACTIONS = [
    "polish", "touch_up", "dent_repair", "paint", "panel_replace",
    "part_replace", "glass_replace", "realign", "structural_inspection",
]

DAMAGE_TYPES = [
    "scratch", "scuff", "dent", "crack", "shatter", "tear", "puncture",
    "paint_transfer", "paint_loss", "misalignment", "detached", "deformation",
    "burn", "corrosion",
]

SYSTEM = """\
You are an experienced panel-beater and vehicle damage assessor looking at a
photograph taken at the scene of an accident. Report only what is visible.

## What you are doing

For every piece of damage you can actually see, identify which part it is on,
what kind of damage it is, how severe, and what operation would repair it.

You do not estimate cost. You never mention money. Pricing is calculated
elsewhere from your findings, so a part named wrongly or a severity inflated
becomes a wrong number that someone may rely on.

## Severity

- minor    - cosmetic only. Paintwork or surface, panel straight, part working.
- moderate - the panel is deformed or the part is damaged but still located and
             functioning. Needs real repair work, not just finishing.
- severe   - the part is destroyed, detached, torn, shattered, or pushed out of
             position. Replacement or structural work.

## Being honest about what you cannot see

One photograph shows one side of one moment. Say so:

- If the image is blurred, too dark, too far away, or cropped so that damage
  runs out of frame, set photo_quality accordingly and say what a better photo
  would need to show. A confident report from an unusable photo is worse than
  no report.
- Only report damage you can see in THIS image. Do not infer the far side of
  the car, the underside, or the engine bay.
- Where impact suggests damage likely continues out of sight - a hard front
  corner hit implying radiator support or suspension - put that in
  hidden_damage_risk rather than inventing a finding for it.
- confidence is per finding, 0 to 1. Something half in shadow gets a low number.

## Safety

If anything visible suggests the vehicle is unsafe to drive - fluid pooling or
running, a wheel sitting at the wrong angle, a deployed airbag, a shattered
windscreen, a detached or dragging part, lighting destroyed - list it in
safety_flags in plain words. This is the part a person acts on first.

## If it is not a damaged vehicle

If the photo is not of a vehicle, or shows a vehicle with no visible damage,
set is_vehicle and has_visible_damage truthfully and return no findings. Do not
invent damage to be helpful.
"""

_FINDING = {
    "type": "object",
    "properties": {
        "part": {"type": "string", "enum": PARTS},
        "part_label": {
            "type": "string",
            "description": "the part in plain words, e.g. 'front bumper, left corner'",
        },
        "damage_type": {"type": "string", "enum": DAMAGE_TYPES},
        "severity": {"type": "string", "enum": ["minor", "moderate", "severe"]},
        "repair_action": {"type": "string", "enum": ACTIONS},
        "extent": {
            "type": "string",
            "description": "rough size or spread, e.g. 'about 30cm across the lower edge'",
        },
        "confidence": {"type": "number"},
        "note": {"type": "string", "description": "what you actually see, one sentence"},
    },
    "required": ["part", "part_label", "damage_type", "severity", "repair_action",
                 "extent", "confidence", "note"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "is_vehicle": {"type": "boolean"},
        "has_visible_damage": {"type": "boolean"},
        "photo_quality": {"type": "string", "enum": ["good", "fair", "poor"]},
        "quality_note": {
            "type": "string",
            "description": "empty if good; otherwise what a better photo would show",
        },
        "vehicle_type": {
            "type": "string",
            "description": "car, van, motorcycle, lorry, or 'unknown'",
        },
        "vehicle_note": {
            "type": "string",
            "description": "colour and body style if visible; never guess a plate",
        },
        "view": {
            "type": "string",
            "description": "which angle this is, e.g. 'front three-quarter, left'",
        },
        "findings": {"type": "array", "items": _FINDING},
        "safety_flags": {"type": "array", "items": {"type": "string"}},
        "hidden_damage_risk": {
            "type": "string",
            "description": "what may be damaged out of frame, or empty",
        },
        "summary": {
            "type": "string",
            "description": "two or three sentences a non-mechanic would understand",
        },
    },
    "required": ["is_vehicle", "has_visible_damage", "photo_quality", "quality_note",
                 "vehicle_type", "vehicle_note", "view", "findings", "safety_flags",
                 "hidden_damage_risk", "summary"],
    "additionalProperties": False,
}

USER_PROMPT = (
    "Assess the damage visible in this photograph. Report only what you can "
    "see, and be explicit about anything the image does not let you judge."
)
