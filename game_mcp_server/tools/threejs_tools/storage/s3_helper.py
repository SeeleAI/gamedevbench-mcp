"""
S3 storage helper functions for ThreeJS tools.
Provides singleton aioboto3.Session instance and S3Storage factory.
"""
import logging
import aioboto3
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from util.s3_util import S3Client

logger = logging.getLogger(__name__)

_aioboto3_session = None

_s3_client_instance: Optional['S3Client'] = None


def get_aioboto3_session():
    """
    Get the global singleton aioboto3.Session instance.
    
    aioboto3.Session is thread-safe and should be reused across the entire service
    to avoid unnecessary resource creation and connection overhead.
    
    Returns:
        aioboto3.Session: Shared aioboto3 session for S3 operations
    """
    global _aioboto3_session
    
    if _aioboto3_session is None:
        from config import config
        s3_cfg = config.s3
        
        logger.info("Initializing global aioboto3 Session singleton")
        _aioboto3_session = aioboto3.Session()
        logger.info("Global aioboto3 Session initialized successfully")
    
    return _aioboto3_session


async def get_s3_storage(canvas_id: Optional[str] = None):
    """
    Get S3Storage instance with optional canvas_id for project isolation.
    
    This function creates a new S3Storage instance each time it's called.
    The underlying aioboto3.Session is shared globally to avoid resource waste.
    S3Storage instances are lightweight (just configuration), so caching them
    is unnecessary and would cause memory leaks.
    
    This is used by ThreeJS tools (create_script, read_script, etc.) to manage
    script files in the private S3 bucket with project isolation.
    
    Args:
        canvas_id: Optional canvas ID for project isolation
        
    Returns:
        S3Storage: Configured S3Storage instance for ThreeJS scripts
    """
    from .s3_storage import S3Storage
    
    session = get_aioboto3_session()
    
    logger.debug(f"Creating S3Storage instance for canvas_id: {canvas_id or 'default'}")
    return S3Storage(canvas_id=canvas_id, session=session)


def get_s3_client():
    """
    Get the singleton S3Client instance from Unity's util module.
    
    This allows ThreeJS tools to reuse Unity's S3 capabilities for:
    - Converting private S3 URLs to public CDN URLs
    - Generating presigned URLs
    - Moving files between private and public buckets
    
    Example use case: Import Unity-generated assets into ThreeJS scenes
    
    Returns:
        S3Client: Unity's S3Client instance with full bucket access
    """
    global _s3_client_instance
    
    if _s3_client_instance is None:
        from util.s3_util import S3Client
        logger.info("Initializing S3Client instance (Unity S3 tool)")
        _s3_client_instance = S3Client()
        logger.info("S3Client initialized successfully")
    
    return _s3_client_instance
