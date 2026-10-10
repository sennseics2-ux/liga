"""Build/check localization exports from the single editable pt-PT.json catalogue."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate translation key: {key}")
        result[key] = value
    return result


def build_outputs():
    catalogue = json.loads(
        (ROOT / "static" / "pt-PT.json").read_text(encoding="utf-8"),
        object_pairs_hook=unique_keys,
    )
    for key, value in catalogue.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Empty/non-text translation: {key}")
        if set(PLACEHOLDER.findall(key)) != set(PLACEHOLDER.findall(value)):
            raise ValueError(f"Mismatched interpolation variables: {key}")
        if any(char in key + value for char in ("\t", "\r", "\n")):
            raise ValueError(f"Catalogue entries must fit one TSV row: {key}")
    source = (ROOT / "tools" / "i18n.template.js").read_text(encoding="utf-8")
    result = source.replace(
        "__DICTIONARY__", json.dumps(catalogue, ensure_ascii=False, separators=(",", ":"))
    )
    table = "# Generated from static/pt-PT.json; edit that catalogue and run tools/build_i18n.py.\n"
    table += "".join(f"{key}\t{value}\n" for key, value in catalogue.items())
    return {ROOT / "static" / "i18n.js": result, ROOT / "translations-pt.tsv": table}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated files need updating")
    args = parser.parse_args()
    outputs = build_outputs()
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, value in outputs.items()
                 if not path.exists() or path.read_text(encoding="utf-8") != value]
        if stale:
            parser.exit(1, "Out-of-date localization exports: " + ", ".join(stale) + "\n")
        print("Localization exports are current")
    else:
        for path, value in outputs.items():
            path.write_text(value, encoding="utf-8")
        print("Built static/i18n.js and translations-pt.tsv from static/pt-PT.json")


if __name__ == "__main__":
    main()
