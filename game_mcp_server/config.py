"""
Configuration settings for the MCP for Unity Server.
This file contains all configurable parameters for the server.
"""

import os
import sys
import tempfile
from dataclasses import dataclass

SERVER_START_REMOTE_MODE = "remote"
SERVER_START_LOCAL_HTTP_MODE = "local-http"

RUN_PLATFORM_UNITY = "unity"
RUN_PLATFORM_3JS = "3js"
RUN_PLATFORM_BLENDER = "blender"


def _default_unity_exe() -> str:
    # Try environment first
    env_path = os.getenv("UNITY_MCP_UNITY_EXE")
    if env_path:
        return env_path
    # Fallback defaults by platform
    if sys.platform.startswith("win"):
        return r"C:\Users\logan\Documents\unity\6000.0.49f1\Editor\Unity.exe"
    if sys.platform == "darwin":
        return "/Applications/Unity/Hub/Editor/6000.0.49f1/Unity.app/Contents/MacOS/Unity"
    return "/opt/unity/Editor/Unity"


def _default_projects_dir() -> str:
    env_dir = os.getenv("UNITY_MCP_PROJECTS_DIR")
    # Default to system temp directory and create a subfolder inside
    base_dir = env_dir or os.path.join(tempfile.gettempdir(), "unity-mcp", "projects")
    try:
        os.makedirs(base_dir, exist_ok=True)
    except Exception:
        # In case of unexpected permission issues, fall back silently
        pass
    return base_dir

def _default_base_unity_project_dir() -> str:
    return os.getenv("UNITY_BASE_PROJECTS_DIR") or r"D:\lewis\code\unity_empty\Empty1\Empty_915"


# ========== S3 Global Configuration ==========
# S3 credentials for private bucket (Unity temp assets + 3JS scripts)
S3_PRIVATE_ACCESS_KEY_ID = os.environ.get(
    "S3_PRIVATE_ACCESS_KEY_ID", 
    "AK"
)
S3_PRIVATE_SECRET_ACCESS_KEY = os.environ.get(
    "S3_PRIVATE_SECRET_ACCESS_KEY", 
    "rN"
)

# S3 credentials for public bucket (Unity final assets)
S3_PUBLIC_ACCESS_KEY_ID = os.environ.get(
    "S3_PUBLIC_ACCESS_KEY_ID",
    "AK"
)
S3_PUBLIC_SECRET_ACCESS_KEY = os.environ.get(
    "S3_PUBLIC_SECRET_ACCESS_KEY",
    "VV"
)

# S3 bucket names and regions
S3_PRIVATE_BUCKET = "seelemedia-private"
S3_PUBLIC_BUCKET = "seelemedia"
S3_PRIVATE_REGION = "ap-southeast-1"
S3_PUBLIC_REGION = "us-east-1"


@dataclass
class S3Config:
    """Unified S3 configuration for Unity and ThreeJS"""
    private_bucket: str = S3_PRIVATE_BUCKET
    private_region: str = S3_PRIVATE_REGION
    private_access_key_id: str = S3_PRIVATE_ACCESS_KEY_ID
    private_secret_key: str = S3_PRIVATE_SECRET_ACCESS_KEY
    
    public_bucket: str = S3_PUBLIC_BUCKET
    public_region: str = S3_PUBLIC_REGION
    public_access_key_id: str = S3_PUBLIC_ACCESS_KEY_ID
    public_secret_key: str = S3_PUBLIC_SECRET_ACCESS_KEY


@dataclass
class ThreeJSConfig:
    """ThreeJS-specific configuration"""
    # Script storage path in private bucket
    # 支持通过环境变量 THREEJS_SCRIPT_BASE_PREFIX 直接设置，或通过环境变量自动选择
    # 优先级：THREEJS_SCRIPT_BASE_PREFIX > SERVER_ENV/ENV > 默认值
    # SERVER_ENV/ENV: prod -> PROD/THREEJS/, 其他 -> TEST/THREEJS/
    script_base_prefix: str = os.environ.get(
        "THREEJS_SCRIPT_BASE_PREFIX",
        "PROD/THREEJS/" if os.environ.get("SERVER_ENV", os.environ.get("ENV", "")).lower() == "prod" else "TEST/THREEJS/"
    )
    
    # 内置 Runtime 配置
    runtime_timeout: int = int(os.environ.get("THREEJS_RUNTIME_TIMEOUT", "30"))  # 默认30秒（内置执行更快）
    runtime_max_concurrent: int = int(os.environ.get("THREEJS_MAX_CONCURRENT", "2"))  # 默认2个并发（2Gi Pod 下更稳）
    
    # HTML Bundler API configuration
    # URL 通过 syn_base_url 动态构建（与 Unity 一致），支持环境变量 HTML_BUNDLER_API_URL 完全覆盖
    # 使用方式：os.environ.get("HTML_BUNDLER_API_URL", f"{config.syn_base_url}/gateway/api/html_bundler?...")
    # 这样在生产环境会自动使用 k8s 内部服务名（如 syn-gateway:8080），测试环境使用外部域名
    bundler_timeout: int = int(os.environ.get("HTML_BUNDLER_TIMEOUT", "60"))  # 默认60秒
    
    # HTML Bundler authentication
    bundler_token: str = os.environ.get("HTML_BUNDLER_TOKEN", "seele_koko_pwd")

    # ThreeJS Environment Service
    env_service_url: str = os.environ.get("THREEJS_ENV_SERVICE_URL", "")
    use_env: bool = os.environ.get("THREEJS_USE_ENV", "false").lower() == "true"
    env_auth_token: str = os.environ.get("THREEJS_ENV_AUTH_TOKEN", "")


@dataclass
class ServerConfig:
    """Main configuration class for the MCP server."""
    
    # Network settings
    unity_host: str = "localhost"
    unity_port: int = 6400
    mcp_port: int = 6500
    
    # Connection settings
    connection_timeout: float = 180.0  # default steady-state timeout; retries use shorter timeouts
    connect_timeout: float = 20.0      # initial connection timeout
    handshake_timeout: float = 3.0    # handshake timeout
    buffer_size: int = 16 * 1024 * 1024  # 16MB buffer
    # Framed receive behavior
    framed_receive_timeout: float = 10.0  # max seconds to wait while consuming heartbeats only
    max_heartbeat_frames: int = 16       # cap heartbeat frames consumed before giving up
    http_timeout = 10  # HTTP client timeout for remote connections
    callback_timeout = 900  # Callback timeout for long-running operations
    
    # Logging settings
    log_level: str = "INFO"
    log_format: str = "%(asctime)s.%(msecs)03d [%(asctime)s,%(msecs)03d] [%(levelname)s] [%(name)s:%(funcName)s] [%(filename)s:%(lineno)d] [trace:%(trace_id)s] [%(message)s]"
    
    # Server settings
    max_retries: int = 5
    retry_delay: float = 1.0
    # Backoff hint returned to clients when Unity is reloading (milliseconds)
    reload_retry_ms: int = 500
    # Number of polite retries when Unity reports reloading
    # 40 × 250ms ≈ 10s default window
    reload_max_retries: int = 3

    start_mode = SERVER_START_LOCAL_HTTP_MODE
    run_platform = os.environ.get("RUN_PLATFORM", RUN_PLATFORM_UNITY)
    # Unity executable path (env UNITY_MCP_UNITY_EXE overrides). Used by multi-manager to spawn editors.
    unity_exe_path: str = _default_unity_exe()

    # Directories
    unity_projects_dir: str = _default_projects_dir()
    unity_base_project_dir: str = _default_base_unity_project_dir()

    # Recovery behavior
    recovery_enabled: bool = True
    recovery_max_canvases: int = 20
    recovery_per_canvas_timeout_s: float = 0.5
    # Only consider projects whose status/port file updated within recent seconds
    recovery_recent_seconds: float = 300.0

    # Stop behavior
    stop_terminate_timeout_s: float = 10.0
    stop_kill_on_timeout: bool = False

    dify_base_url = os.environ.get("DIFY_BASE_URL", "http://47.129.113.173/v1")

    syn_base_url = os.environ.get("SYN_BASE_URL", "http://m-test-mcp.seeles.ai")
    # 本地未配置时用此默认
    app_base_url = os.environ.get("APP_BASE_URL", "https://test-api.seeles.ai")

    # Higress Asset MCP  endpoint 暂时没用
    higress_asset_mcp_url: str = "http://m-test-mcp.seeles.ai/mcp/asset-search"
    higress_canvas_config_mcp_url: str = "http://m-test-mcp.seeles.ai/mcp/canvas-config"

    # 用于测试的id
    test_canvas_id = "43c0de40-a1be-47fd-b768-8e5149a44cf7"
    test_trace_id = "43c0de40-a1be-47fd-b768-8e5149a44cf7|8793dc8b-3600-4487-a758-b055914ff20f|game_scene_creator-2ac851f24ef7cc9fc947b02d|test"

    # 自动将tool描述替换成nacos的配置，关掉就会用本地的
    enable_replace_tool_description = True
    
    # S3 configuration
    s3: S3Config = None
    
    # ThreeJS configuration
    threejs: ThreeJSConfig = None
    
    def __post_init__(self):
        if self.s3 is None:
            self.s3 = S3Config()
        if self.threejs is None:
            self.threejs = ThreeJSConfig()

# Create a global config instance
config = ServerConfig() 