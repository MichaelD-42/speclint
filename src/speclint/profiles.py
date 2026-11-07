"""Rule profiles: which rules run and at which severity. Built-ins live in rules.toml; custom ones in a TOML file."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .checks import RULES

SEVERITIES = {"error", "warning", "info"}


@dataclass
class Profile:
    name: str
    severities: dict[str, str]  # active rule -> effective severity
    ears: bool = False


def load_profile(spec: str = "customer", ears: bool = False) -> Profile:
    """A built-in profile name or a path to a TOML file with a [profile] table. Bad input raises ValueError."""
    if spec in RULES["profiles"]:
        data = RULES["profiles"][spec]
    elif Path(spec).is_file():
        try:
            data = tomllib.loads(Path(spec).read_text(encoding="utf-8"))["profile"]
        except (tomllib.TOMLDecodeError, KeyError) as e:
            raise ValueError(f"{spec}: not a profile file ({e})") from e
    else:
        raise ValueError(
            f"unknown profile {spec!r} (built-in: {', '.join(RULES['profiles'])})"
        )
    if ears:  # the profile's own severity table may still override it
        data = {**data, "enable": [*data.get("enable", []), "ears-nonconforming"]}
    return Profile(spec, _resolve(spec, data, set()), ears)


def _resolve(name: str, data: dict, seen: set[str]) -> dict[str, str]:
    if name in seen:
        raise ValueError(f"profile extends cycle: {' -> '.join([*seen, name])}")
    seen = seen | {name}
    if base := data.get("extends"):
        if base not in RULES["profiles"]:
            raise ValueError(f"{name}: extends unknown profile {base!r}")
        sev = _resolve(base, RULES["profiles"][base], seen)
    else:
        sev = {}
    for key in ("rules", "enable", "disable"):
        _known(name, data.get(key, []))
    if "rules" in data:
        sev = {r: sev.get(r, RULES["rules"][r]["severity"]) for r in data["rules"]}
    sev |= {
        r: RULES["rules"][r]["severity"] for r in data.get("enable", []) if r not in sev
    }
    for r in data.get("disable", []):
        sev.pop(r, None)
    overrides = data.get("severity", {})
    _known(name, overrides)
    for r, s in overrides.items():
        if s not in SEVERITIES:
            raise ValueError(
                f"{name}: severity {s!r} for {r} is not one of {sorted(SEVERITIES)}"
            )
        if r in sev:
            sev[r] = s
    return sev


def _known(name: str, rules) -> None:
    if unknown := [r for r in rules if r not in RULES["rules"]]:
        raise ValueError(f"{name}: unknown rule(s) {', '.join(unknown)}")
