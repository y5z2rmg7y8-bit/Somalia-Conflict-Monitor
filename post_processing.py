import re
import logging

logger = logging.getLogger(__name__)

_PHRASE_REPLACEMENTS = [
    (r"\bunprecedented\b", "notable"),
    (r"\bmost significant\b", "notable"),
    (r"\bmost important\b", "notable"),
    (r"\bdeadliest\b", "lethal"),
    (r"\bheaviest\b", "substantial"),
    (r"\bmost serious\b", "serious"),
    (r"\bmost critical\b", "critical"),
    (r"\bmost notable\b", "notable"),
    (r"\bmost concerning\b", "concerning"),
    (r"\bsingle deadliest\b", "lethal"),
    (r"\bsingle largest\b", "large"),
    (r"the month's deadliest", "a lethal"),
    (r"the month's most\b", "a"),
    (r"\bthe primary theatre\b", "a major theatre"),
    (r"\bterritorial fragmentation\b", "political fragmentation"),
    (r"\bHarmacad\b", "Federal forces"),
    (r"\bSouth[\-\s]West State Special Police Forces\b", "South-West State Forces"),
    (r"\bSouthwest State Special Police Forces\b", "South-West State Forces"),
    (r"\bhighest monthly\b", "elevated monthly"),
]

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def filter_superlatives(text, dataset_start=None):
    """
    Scan brief text for superlative constructions and replace them.
    Logs every replacement to stdout and to the module logger.

    Args:
        text: raw brief text from Claude
        dataset_start: ISO date string e.g. "2023-04-01" — used to detect and
                       remove "since [month] [year]" claims outside the dataset window
    Returns:
        cleaned text (str)
    """
    changes = []

    # 1. Fixed phrase replacements
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        def _make_repl(repl, pat):
            def _repl(m):
                changes.append(f'  [{pat!r}] "{m.group(0)}" → "{repl}"')
                return repl
            return _repl
        text = re.sub(pattern, _make_repl(replacement, pattern), text, flags=re.IGNORECASE)

    # 2. "the most [adjective]" → adjective
    # Conservative: single-word match only; skips multi-word constructions
    def _remove_the_most(m):
        adjective = m.group(1)
        changes.append(f'  [the most + adj] "{m.group(0)}" → "{adjective}"')
        return adjective

    text = re.sub(r"\bthe most ([a-z]+)\b", _remove_the_most, text, flags=re.IGNORECASE)

    # 3. "since [Month] [Year]" outside dataset window → remove clause
    if dataset_start:
        try:
            ds_year = int(dataset_start[:4])
            ds_month_num = int(dataset_start[5:7])
            months_pat = "|".join(_MONTH_MAP.keys())

            def _filter_since(m):
                month_str = m.group(1).lower()
                year = int(m.group(2))
                month_num = _MONTH_MAP.get(month_str, 0)
                if year < ds_year or (year == ds_year and month_num < ds_month_num):
                    changes.append(
                        f'  [since out-of-dataset] "{m.group(0)}" → removed'
                        f' (before dataset start {dataset_start})'
                    )
                    return ""
                return m.group(0)

            text = re.sub(
                rf",?\s*since\s+({months_pat})\s+(\d{{4}})\b",
                _filter_since,
                text,
                flags=re.IGNORECASE,
            )
        except (ValueError, IndexError):
            pass

    # Report
    if changes:
        report = "\n".join(changes)
        print(f"\n[POST-PROCESSING] Superlative filter: {len(changes)} replacement(s):")
        print(report)
        logger.info("Superlative filter — %d change(s):\n%s", len(changes), report)
    else:
        print("\n[POST-PROCESSING] Superlative filter: no replacements needed.")

    return text


if __name__ == "__main__":
    sample = (
        "This was the most significant attack since April 2020. "
        "The deadliest incident occurred in Lower Shabelle, the primary theatre of operations. "
        "The single largest offensive involved unprecedented troop movements. "
        "It was the heaviest bombardment of the month's most intense period."
    )
    print("Input:")
    print(sample)
    cleaned = filter_superlatives(sample, dataset_start="2023-04-01")
    print("\nOutput:")
    print(cleaned)
