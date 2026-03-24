import datetime
import logging

from python_http_cuda_rpc.util import report

service_name = "unity-mcp-server"
logger = logging.getLogger(__name__)


def now_time() -> str:
    """获取UTC时间的ISO格式字符串（精确到秒）"""
    now = datetime.datetime.utcnow()
    return now.isoformat(timespec="seconds")


def report_llm(trace_id: str, start_time: str, llm_info):
    logger.info(f"report_llm({trace_id}, {start_time}, {llm_info})")
    try:
        report.report(
            canvas_trace_id=trace_id,
            source=service_name,
            start_time=start_time,
            end_time=now_time(),
            report_type='llm',
            status=0,  # 此处status可能因前面的异常被设为1
            llm_info=llm_info)
    except Exception as e:
        logger.warning(f"Failed to report {trace_id} error: {e}")
