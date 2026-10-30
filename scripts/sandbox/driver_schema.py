"""Closed structured response schema for the retained Claude driver launcher."""

DRIVER_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": ["done", "skipped", "failed", "NEEDS_DECISION", "OUTSIDE_SCOPE", "IRREVERSIBLE_ACTION"],
        },
        "evidence": {"type": "string"},
        "final_report": {
            "type": ["object", "null"],
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "label": {"type": "string", "enum": ["verified", "inferred", "guess"]},
                            "source": {"type": "string"},
                        },
                        "required": ["text", "label", "source"],
                        "additionalProperties": False,
                    },
                },
                "did_not_verify": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string"},
                            "tag": {"type": "string", "enum": ["resolved", "unverifiable"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["item", "tag", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["claims", "did_not_verify"],
            "additionalProperties": False,
        },
    },
    "required": ["outcome", "evidence", "final_report"],
    "additionalProperties": False,
}
