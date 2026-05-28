from arb_study.clusters import normalize_cluster


def _market(venue: str, title: str, market_id: str, slug: str, outcomes: list[dict], description: str = ""):
    return {
        "sourceExchange": venue,
        "marketId": market_id,
        "id": market_id,
        "title": title,
        "slug": slug,
        "description": description,
        "resolutionDate": "2026-01-01T00:00:00.000Z",
        "contractAddress": "0xabc" if venue == "polymarket" else None,
        "outcomes": outcomes,
    }


def test_up_only_identity_cluster_is_valid() -> None:
    cluster = {
        "clusterId": "mcl_up_only",
        "canonicalTitle": "Will Brian Armstrong appear on the UpOnly podcast before 2027?",
        "relations": ["identity"],
        "confidence": 1,
        "markets": [
            _market(
                "polymarket",
                "Will Brian Armstrong appear on the UpOnly podcast by December 31?",
                "pm",
                "pm-up-only",
                [
                    {"outcomeId": "pm_yes", "label": "Brian Armstrong"},
                    {"outcomeId": "pm_no", "label": "Not Brian Armstrong"},
                ],
            ),
            _market(
                "kalshi",
                "Will Brian Armstrong be on UpOnly Podcast before Jan 2027?",
                "kx",
                "KXUPONLY-BRIAN",
                [
                    {"outcomeId": "KXUPONLY-BRIAN", "label": "Brian Armstrong"},
                    {"outcomeId": "KXUPONLY-BRIAN-NO", "label": "Not Brian Armstrong"},
                ],
            ),
        ],
        "rawMatches": [{"marketAId": "pm", "marketBId": "kx", "relation": "identity", "confidence": 1}],
    }

    matches = normalize_cluster(cluster)

    assert len(matches) == 1
    assert matches[0].polymarket.market_id == "pm"
    assert matches[0].kalshi.market_id == "kx"


def test_world_cup_round_of_16_does_not_match_knockout_stage() -> None:
    cluster = {
        "clusterId": "mcl_wc",
        "canonicalTitle": "Will Austria qualify from World Cup Group J?",
        "relations": ["identity"],
        "confidence": 0.95,
        "markets": [
            _market(
                "polymarket",
                "Will Austria advance to the knockout stages at the 2026 FIFA World Cup?",
                "pm_wc",
                "pm-austria",
                [
                    {"outcomeId": "pm_yes", "label": "Austria"},
                    {"outcomeId": "pm_no", "label": "Not Austria"},
                ],
                description="This resolves Yes if Austria advances to the Knockout Stage.",
            ),
            _market(
                "kalshi",
                "Will Austria qualify for FIFA World Cup Round of 16?",
                "kx_r16",
                "KXWCROUND-26RO16-AUT",
                [
                    {"outcomeId": "kx_yes", "label": "Austria"},
                    {"outcomeId": "kx_no", "label": "Not Austria"},
                ],
                description="This resolves Yes if Austria qualifies for the Round of 16.",
            ),
        ],
        "rawMatches": [{"marketAId": "pm_wc", "marketBId": "kx_r16", "relation": "identity", "confidence": 0.95}],
    }

    assert normalize_cluster(cluster) == []


def test_world_cup_winner_valid_with_resolution_warning() -> None:
    cluster = {
        "clusterId": "mcl_wc_winner",
        "canonicalTitle": "Will Portugal win the 2026 FIFA World Cup?",
        "relations": ["identity"],
        "confidence": 1,
        "markets": [
            _market(
                "polymarket",
                "Will Portugal win the 2026 FIFA World Cup?",
                "pm_pt",
                "pm-portugal",
                [
                    {"outcomeId": "pm_no", "label": "Not Portugal"},
                    {"outcomeId": "pm_yes", "label": "Portugal"},
                ],
            )
            | {"resolutionDate": "2026-07-20T00:00:00.000Z"},
            _market(
                "kalshi",
                "Will the Portugal win the 2026 Men's World Cup?",
                "kx_pt",
                "KXMENWORLDCUP-26-PT",
                [
                    {"outcomeId": "kx_no", "label": "Not Portugal"},
                    {"outcomeId": "kx_yes", "label": "Portugal"},
                ],
            )
            | {"resolutionDate": "2028-07-18T14:00:00.000Z"},
        ],
        "rawMatches": [{"marketAId": "pm_pt", "marketBId": "kx_pt", "relation": "identity", "confidence": 1}],
    }

    matches = normalize_cluster(cluster, max_resolution_drift_days=45)

    assert len(matches) == 1
    assert matches[0].resolution_date_warning is not None
