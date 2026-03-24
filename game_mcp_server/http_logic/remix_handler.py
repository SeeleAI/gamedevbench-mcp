import logging
from abc import ABC, abstractmethod
from typing import Dict, Any

import config
from http_logic.entity import GameRemixRequest
from tools.threejs_tools.storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)


class GameRemixHandlerInterface(ABC):

    @abstractmethod
    async def remix(self, req: GameRemixRequest) -> Dict[str, Any]:
        pass


class ThreeJsRemixHandlerInterface(GameRemixHandlerInterface):

    async def remix(self, req: GameRemixRequest) -> Dict[str, Any]:
        """
        将源画布的所有脚本文件复制到新画布。
        
        采用快速失败策略：遇到任何错误立即停止并返回失败。
        S3Storage 会自动根据 canvas_id 拼接 S3 路径。
        """
        try:
            # 1. 参数验证
            if not req.canvas_id or not req.remix_from_canvas_id or not req.canvas_id.strip() or not req.remix_from_canvas_id.strip():
                return {"code": -1}
            
            if req.canvas_id == req.remix_from_canvas_id:
                return {"code": -1}
            
            logger.info(f"开始复制代码: 从 {req.remix_from_canvas_id} 到 {req.canvas_id}")
            
            # 2. 获取源画布和目标画布的 S3 存储实例
            # S3Storage 会根据 canvas_id 自动拼接路径: TEST/THREEJS/{canvas_id}/
            source_storage = await get_s3_storage(req.remix_from_canvas_id)
            target_storage = await get_s3_storage(req.canvas_id)
            
            # 2.1 检查目标画布是否已有文件（如果已有文件则拒绝复制）
            target_success, target_message, target_existing_files = await target_storage.list_files()
            if not target_success:
                logger.error(f"无法检查目标画布文件列表: {target_message}")
                return {"code": -1}
            
            if target_existing_files:
                existing_file_names = [f["file_name"] for f in target_existing_files]
                logger.warning(
                    f"目标画布 {req.canvas_id} 已有 {len(target_existing_files)} 个文件，拒绝复制以避免覆盖: {existing_file_names}"
                )
                return {"code": -1}
            
            # 3. 列出源画布的所有文件
            success, message, files_data = await source_storage.list_files()
            if not success:
                logger.error(f"无法获取源画布文件列表: {message}")
                return {"code": -1}
            
            if not files_data:
                logger.warning(f"源画布 {req.remix_from_canvas_id} 没有文件")
                return {"code": -1}
            
            logger.info(f"找到 {len(files_data)} 个文件需要复制")
            logger.debug(f"文件列表: {[f['file_name'] for f in files_data]}")
            
            # 4. 逐个复制文件（使用 S3 copy_object API，直接桶内复制，快速失败策略：任何文件失败立即停止）
            copied_count = 0
            for file_info in files_data:
                file_name = file_info["file_name"]
                logger.debug(f"正在复制文件: {file_name}")
                
                # 使用 S3Storage 的 copy_file_from 方法（使用 S3 copy_object API，直接桶内复制）
                copy_success, copy_message, copy_data = await target_storage.copy_file_from(source_storage, file_name)
                if not copy_success:
                    logger.error(f"复制文件失败 {file_name}: {copy_message}")
                    return {"code": -1}
                
                copied_count += 1
                logger.debug(f"成功复制文件: {file_name}")
            
            logger.info(f"复制完成: 共复制 {copied_count} 个文件从 {req.remix_from_canvas_id} 到 {req.canvas_id}")
            return {"code": 0}
            
        except Exception as e:
            logger.error(f"复制过程出错: {str(e)}", exc_info=True)
            return {"code": -1}


class NotSupportRemixHandlerInterface(GameRemixHandlerInterface):

    async def remix(self, req: GameRemixRequest) -> Dict[str, Any]:
        logger.warning(f"not supported, current is {config.config.run_platform}")
        return {"code": -1}


def get_remix_handler() -> GameRemixHandlerInterface:
    if config.config.run_platform == config.RUN_PLATFORM_3JS:
        return ThreeJsRemixHandlerInterface()
    return NotSupportRemixHandlerInterface()
