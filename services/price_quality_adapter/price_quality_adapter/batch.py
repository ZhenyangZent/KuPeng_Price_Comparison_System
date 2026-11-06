from __future__ import annotations

from .repository import PriceQualityRepository


def build_quality_report(repository: PriceQualityRepository, *, page_size: int = 100) -> dict[str, object]:
    """Recalculate an in-memory report from an authorized copy; never mutate SQLite."""
    if page_size < 1 or page_size > 100:
        raise ValueError("page_size must be between 1 and 100")
    page = 1
    results: list[dict[str, object]] = []
    while True:
        search = repository.search("", page=page, limit=page_size)
        for item in search["items"]:
            quality = repository.quality(str(item["id"]))
            if quality is not None:
                results.append(quality)
        if page * page_size >= search["total"]:
            break
        page += 1
    return {
        "schema_version": "CDH-B08-BATCH-QUALITY-REPORT-1",
        "data_version": repository.data_version,
        "data_classification": repository.classification,
        "series_count": len(results),
        "series": results,
    }
