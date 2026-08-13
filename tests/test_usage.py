from coco_code.usage import (
    UsageCost,
    compact_token_count,
    format_usd,
    pricing_for_model,
)


def test_deepseek_v4_flash_cost_uses_cache_and_output_rates() -> None:
    cost = UsageCost(
        input_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost.usd == 0.4228


def test_usage_formatters() -> None:
    assert compact_token_count(61_100) == "61.1k"
    assert compact_token_count(1_000_000) == "1.0m"
    assert format_usd(0.0149) == "$0.0149"


def test_kimi_k3_cost_uses_its_official_cny_rates() -> None:
    pricing = pricing_for_model("kimi-k3")
    assert pricing is not None
    assert pricing.currency_symbol == "¥"
    assert pricing.cost(
        input_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        output_tokens=1_000_000,
    ) == 122.0
