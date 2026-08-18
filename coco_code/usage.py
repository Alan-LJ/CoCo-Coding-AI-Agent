from __future__ import annotations

from dataclasses import dataclass


# DeepSeek API list prices, USD per one million tokens (2026-08-07).
DEEPSEEK_V4_FLASH_INPUT_PER_M = 0.14
DEEPSEEK_V4_FLASH_CACHE_HIT_PER_M = 0.0028
DEEPSEEK_V4_FLASH_OUTPUT_PER_M = 0.28

KIMI_K3_INPUT_PER_M = 20.0
KIMI_K3_CACHE_HIT_PER_M = 2.0
KIMI_K3_OUTPUT_PER_M = 100.0


@dataclass(frozen=True)
class ModelPricing:
    display_name: str
    currency_symbol: str
    input_per_m: float
    cache_hit_per_m: float
    output_per_m: float

    def cost(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> float:
        uncached_input = input_tokens + cache_creation_tokens
        return (
            uncached_input * self.input_per_m
            + cache_read_tokens * self.cache_hit_per_m
            + output_tokens * self.output_per_m
        ) / 1_000_000


DEEPSEEK_V4_FLASH_PRICING = ModelPricing(
    display_name="DeepSeek V4 Flash",
    currency_symbol="$",
    input_per_m=DEEPSEEK_V4_FLASH_INPUT_PER_M,
    cache_hit_per_m=DEEPSEEK_V4_FLASH_CACHE_HIT_PER_M,
    output_per_m=DEEPSEEK_V4_FLASH_OUTPUT_PER_M,
)

KIMI_K3_PRICING = ModelPricing(
    display_name="Kimi K3",
    currency_symbol="¥",
    input_per_m=KIMI_K3_INPUT_PER_M,
    cache_hit_per_m=KIMI_K3_CACHE_HIT_PER_M,
    output_per_m=KIMI_K3_OUTPUT_PER_M,
)


def pricing_for_model(model: str) -> ModelPricing | None:
    normalized = model.lower().replace("_", "-")
    if "deepseek-v4-flash" in normalized:
        return DEEPSEEK_V4_FLASH_PRICING
    if "kimi-k3" in normalized or normalized == "k3":
        return KIMI_K3_PRICING
    return None


@dataclass(frozen=True)
class UsageCost:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def usd(self) -> float:
        return DEEPSEEK_V4_FLASH_PRICING.cost(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens,
        )


def compact_token_count(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}m"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k"
    return str(tokens)


def format_usd(cost: float) -> str:
    if cost == 0:
        return "$0.0000"
    if cost < 0.0001:
        return f"${cost:.6f}"
    return f"${cost:.4f}"
