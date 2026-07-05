from __future__ import annotations

from textual.widgets import OptionList

from coco_code.config import ProviderConfig


def provider_label(provider: ProviderConfig) -> str:
    return f"{provider.name}  |  {provider.protocol}  |  {provider.model}"


class ProviderOptionList(OptionList):
    def __init__(self, providers: list[ProviderConfig]) -> None:
        self.providers = providers
        super().__init__(
            *(provider_label(provider) for provider in providers),
            id="provider-select",
        )
