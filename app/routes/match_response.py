from app.models.enums import MatchStatus


def match_to_dict(match_id, counterpart_field: str, counterpart_id, match_score, match_reasoning, is_non_obvious, status) -> dict:
    return {
        "match_id": str(match_id),
        counterpart_field: str(counterpart_id),
        "match_score": match_score,
        "match_reasoning": match_reasoning,
        "is_non_obvious": is_non_obvious,
        "status": status,
    }


def partition_and_sort(results: list[dict]) -> tuple[list[dict], int]:
    """Split out rejected matches (counted, not shown) and sort the rest by match_score desc."""
    rejected = [r for r in results if r["status"] == MatchStatus.rejected.value]
    suggested = [r for r in results if r["status"] != MatchStatus.rejected.value]
    suggested.sort(key=lambda r: r["match_score"] if r["match_score"] is not None else float("-inf"), reverse=True)
    return suggested, len(rejected)
