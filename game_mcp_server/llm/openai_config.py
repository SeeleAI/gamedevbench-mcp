import dataclasses


@dataclasses.dataclass
class OpenAIConfig:
    model: str
    api_key: str
    endpoint: str
    model_name: str


azure_gpt5_nano_config = OpenAIConfig(
    model="gpt-5-nano-unity-mcp",
    api_key="FEb",
    endpoint="https://seele-eastus2.openai.azure.com/openai/v1/",
    model_name="gpt-5-nano",
)

azure_gpt5_mini_config = OpenAIConfig(
    model="gpt-5-mini-unity-mcp",
    api_key="FEb",
    endpoint="https://seele-eastus2.openai.azure.com/openai/v1/",
    model_name="gpt-5-mini",
)
