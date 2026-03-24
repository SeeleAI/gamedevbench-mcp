import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GlobalEnv:
    server_addrs: Optional[str]
    username: Optional[str]
    password: Optional[str]
    namespace: Optional[str]
    poll_seconds: float


def parse_global_env() -> GlobalEnv:
    import config
    default_namespace = "c7d7a396-95fa-4f64-972f-d4eee0dddb40"
    if config.config.run_platform == config.RUN_PLATFORM_3JS:
        default_namespace = "ce423158-c110-48fa-af05-a6e6f28d0038"
    elif config.config.run_platform == config.RUN_PLATFORM_BLENDER:
        default_namespace = "fa4d051b-ee82-4972-8f41-0395167239c4"
    return GlobalEnv(
        server_addrs=os.environ.get("NACOS_SERVER_ADDRS",
                                    "k8s-monitor-nacos-df21617c3c-2320957018a0d2ea.elb.ap-southeast-1.amazonaws.com"),
        username=os.environ.get("NACOS_USERNAME", "nacos"),
        password=os.environ.get("NACOS_PASSWORD", "koko123"),
        namespace=os.environ.get("NACOS_NAMESPACE", default_namespace),
        poll_seconds=float(os.environ.get("NACOS_POLL_SECONDS", "10")),
    )
