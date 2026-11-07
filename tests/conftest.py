from speclint.profiles import Profile, load_profile
from speclint.spec_checks import SPEC_RULES


def item_only(name):
    """Single-item tests must not depend on whole-spec rules (every "ECU" would be an acronym finding)."""
    p = load_profile(name)
    return Profile(
        p.name, {k: v for k, v in p.severities.items() if k not in SPEC_RULES}
    )
