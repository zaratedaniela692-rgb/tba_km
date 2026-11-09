"""Barracks category selection boundary; real UI selection is not implemented yet."""

from army_unit_types import DEFAULT_UNIT_TYPE, validate_unit_type


def select_army_type(unit_type):
    """Mock the category selection step without sending any game input."""
    try:
        validate_unit_type(unit_type)
    except ValueError:
        return {"status": "BLOCKED_UNKNOWN_UNIT_TYPE", "unit_type": unit_type, "actions_executed": False}
    if unit_type != DEFAULT_UNIT_TYPE:
        return {
            "status": "BLOCKED_CATEGORY_SELECTION_UNIMPLEMENTED",
            "unit_type": unit_type,
            "actions_executed": False,
        }
    return {
        "status": "DEFAULT_CATEGORY_ASSUMED",
        "unit_type": DEFAULT_UNIT_TYPE,
        "selection_confirmed": False,
        "actions_executed": False,
    }

def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Select a Barracks category; preview by default.")
    parser.add_argument("--unit-type", required=True, choices=sorted(SUPPORTED_TRAINING_UNIT_TYPES))
    parser.add_argument("--execute", action="store_true", help="click the category entry")
    parser.add_argument("--confirm", default="", help=f"type exactly: {CONFIRMATION_PHRASE}")
    args = parser.parse_args(argv)
    if args.execute and args.confirm != CONFIRMATION_PHRASE:
        parser.error(f"live selection requires --confirm \"{CONFIRMATION_PHRASE}\"")
    result = select_army_type(args.unit_type, execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = result["status"] in CONFIRMED_STATUSES or (not args.execute and result["status"] == "CATEGORY_WOULD_SELECT")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
