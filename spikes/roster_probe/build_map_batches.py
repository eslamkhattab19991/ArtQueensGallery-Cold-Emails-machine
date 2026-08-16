"""Split the not-yet-mapped organizations into four approval batches.

The map-first sweep: mapping costs ~1 credit per organization, chaining costs
~3 per artist, and batch 1 showed only half of all organizations carry an
extractable roster at all. Mapping everything first is therefore the cheapest
way to learn where the artists actually are, before committing the much larger
chaining budget to them.

Instagram-only rows are excluded: there is no website to map. They are reported
so the count is honest rather than silently short.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"
BATCH_COUNT = 4


def main() -> None:
    """Write map_batch_1..4.json covering every unmapped organization."""
    seeds = json.loads((OUT / "seeds.json").read_text(encoding="utf-8"))
    mapped = {int(path.stem.removeprefix("row_")) for path in (OUT / "maps").glob("row_*.json")}

    instagram_only = [org for org in seeds if not org.get("website")]
    remaining = [org for org in seeds if org.get("website") and org["row"] not in mapped]

    print(f"seeds total           {len(seeds)}")
    print(f"instagram-only        {len(instagram_only)}  (cannot be mapped)")
    print(f"already mapped        {len(mapped)}")
    print(f"remaining to map      {len(remaining)}")

    # Even split, remainder spread across the earlier batches.
    size, extra = divmod(len(remaining), BATCH_COUNT)
    start = 0
    for index in range(BATCH_COUNT):
        length = size + (1 if index < extra else 0)
        batch = remaining[start : start + length]
        start += length
        path = OUT / f"map_batch_{index + 1}.json"
        path.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
        rows = [org["row"] for org in batch]
        span = f"rows {rows[0]}-{rows[-1]}" if rows else "empty"
        print(f"  wrote {path.name}: {len(batch):>3} orgs  ({span})")


if __name__ == "__main__":
    main()
