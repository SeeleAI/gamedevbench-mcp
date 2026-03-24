from remote_config.registry import nacos_binding
from remote_config.schemas.base_type_config import TextConfig


@nacos_binding(data_id="ad_integration_usage.md")
class AdIntegrationSdkUsageConfig(TextConfig):
    pass
