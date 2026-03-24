from pathlib import Path
from typing import Iterable, Union, Dict, Optional
from datetime import datetime, timedelta
import re
import os
import time
import json
import io
import logging

logger = logging.getLogger(__name__)
state_file = ".state.json"


def _log_error(context: str, exc: BaseException) -> None:
    """
    使用 logger 记录错误与堆栈，不抛出到上层。
    """
    try:
        # logger.exception 会自动附带堆栈
        logger.exception("%s: %s", context, exc)
    except Exception:
        # 避免日志记录中的二次异常影响主流程
        pass


def collect_custom_logs(
    source_directory: Union[str, Path],
    output_filename: str = "total-log.txt",
    recursive: bool = False,
    state_filename: Optional[str] = None,
    days: Optional[int] = None,
) -> Path:
    """
    收集指定文件夹下文件名为 "*-custom-log.txt" 的日志，并合并保存到 total-log.txt。

    - 默认仅遍历指定目录的第一层；若 recursive=True 则递归子目录。
    - 合并顺序按最后修改时间 (mtime) 升序，方便从旧到新阅读。
    - 增量收集：记录每个源日志的已处理字节偏移，仅追加新增内容到 total-log。
    - 不写入任何分隔头；从源文件名提取 uuid（如 "<uuid>-custom-log.txt"），
      并在每行时间戳后追加 "[uuid]"，例如：
      "[2025-09-26 16:46:39.155] message" -> "[2025-09-26 16:46:39.155][<uuid>] message"。

    参数:
        source_directory: 需要扫描的目录。
        output_filename: 输出文件名，默认 "total-log.txt"。可为绝对路径或相对 source_directory 的路径。
        recursive: 是否递归扫描子目录。

    仅收集时间范围:
        - 若提供 days，则仅合并最近 days 天内的日志条目（按行首时间戳判断）。
          为保持条目完整，若某条日志时间戳过期，则其后的续行一并跳过至下一条时间戳。

    返回:
        输出文件 Path 对象。
    """
    base_dir = Path(source_directory)
    if not base_dir.exists() or not base_dir.is_dir():
        raise FileNotFoundError(f"Directory not found or not a directory: {base_dir}")

    output_path = Path(output_filename)
    if not output_path.is_absolute():
        output_path = base_dir / output_path

    # 选择搜索模式
    pattern = "**/*-custom-log.txt" if recursive else "*-custom-log.txt"

    # 收集匹配文件并剔除潜在的输出文件自身
    candidates: Iterable[Path] = (
        p for p in base_dir.glob(pattern) if p.is_file() and p.resolve() != output_path.resolve()
    )

    # 按修改时间排序（从旧到新）
    sorted_logs = sorted(candidates, key=lambda p: p.stat().st_mtime)

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ts_pattern = re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\]")
    cutoff = None
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)

    # 状态文件，记录每个源日志文件的上次处理偏移，避免重复收集
    # 状态文件统一为全局 state_file
    state_path = output_path.parent / state_file

    try:
        with state_path.open("r", encoding="utf-8") as sf:
            state: Dict[str, Dict[str, int]] = json.load(sf) or {}
    except Exception:
        state = {}


    # 收集所有待写入的日志条目到内存，排序后统一写入
    log_entries = []
    try:
        for log_file in sorted_logs:
            try:
                m_uuid = re.match(r"^(?P<uuid>.+)-custom-log\.txt$", log_file.name)
                if not m_uuid:
                    file_uuid = None
                else:
                    file_uuid = m_uuid.group("uuid")

                file_key = str(log_file.resolve())
                prev = state.get(file_key) or {}
                prev_offset = int(prev.get("offset", 0))

                file_size = log_file.stat().st_size
                effective_offset = prev_offset if prev_offset <= file_size else 0

                with log_file.open("rb") as bf:
                    bf.seek(effective_offset)
                    if effective_offset > 0:
                        _ = bf.readline()

                    encoding = "utf-8-sig" if effective_offset == 0 else "utf-8"
                    tf = io.TextIOWrapper(bf, encoding=encoding, errors="replace", newline="")

                    current_buffer = None
                    keep_current_entry = False
                    entry_ts = None

                    for raw_line in tf:
                        is_ts = ts_pattern.match(raw_line) is not None

                        if is_ts:
                            # 刷新上一条聚合的日志（仅在上一条需要保留时）
                            if current_buffer is not None and keep_current_entry and entry_ts is not None:
                                log_entries.append((entry_ts, current_buffer))

                            line = raw_line
                            keep_entry = True
                            entry_ts = None
                            if cutoff is not None:
                                try:
                                    m = ts_pattern.match(line)
                                    if m:
                                        raw_ts = m.group("ts")
                                        if "." in raw_ts:
                                            base, frac = raw_ts.split(".", 1)
                                            frac6 = (frac + "000000")[:6]
                                            norm = f"{base}.{frac6}"
                                            fmt = "%Y-%m-%d %H:%M:%S.%f"
                                        else:
                                            norm = raw_ts
                                            fmt = "%Y-%m-%d %H:%M:%S"
                                        ts = datetime.strptime(norm, fmt)
                                        entry_ts = ts
                                        if ts < cutoff:
                                            keep_entry = False
                                except Exception:
                                    keep_entry = True

                            keep_current_entry = keep_entry

                            if keep_current_entry:
                                if file_uuid:
                                    m = ts_pattern.match(line)
                                    if m:
                                        prefix = f"[{m.group('ts')}][{file_uuid}]"
                                        line = prefix + line[m.end():]
                                current_buffer = line.rstrip("\n")
                                # 解析时间戳
                                if entry_ts is None:
                                    m = ts_pattern.match(line)
                                    if m:
                                        raw_ts = m.group("ts")
                                        if "." in raw_ts:
                                            base, frac = raw_ts.split(".", 1)
                                            frac6 = (frac + "000000")[:6]
                                            norm = f"{base}.{frac6}"
                                            fmt = "%Y-%m-%d %H:%M:%S.%f"
                                        else:
                                            norm = raw_ts
                                            fmt = "%Y-%m-%d %H:%M:%S"
                                        try:
                                            entry_ts = datetime.strptime(norm, fmt)
                                        except Exception:
                                            entry_ts = None
                            else:
                                current_buffer = None
                                entry_ts = None
                        else:
                            continuation = raw_line.strip("\n")
                            if continuation == "":
                                continue
                            if not keep_current_entry:
                                continue
                            if current_buffer is None:
                                current_buffer = continuation.strip()
                            else:
                                if not current_buffer.endswith(" "):
                                    current_buffer += " "
                                current_buffer += continuation.strip()

                    # 文件结束时刷新最后一条（仅在需要保留时）
                    if current_buffer is not None and keep_current_entry and entry_ts is not None:
                        log_entries.append((entry_ts, current_buffer))

                    tf.detach()
                    new_offset = bf.tell()
                    state[file_key] = {"offset": int(new_offset)}
            except Exception as e:
                _log_error(f"collect_custom_logs processing [{log_file}]", e)
                continue
        # 按时间戳排序所有条目
        log_entries.sort(key=lambda x: x[0])
        with output_path.open("a", encoding="utf-8") as out_f:
            for _, entry in log_entries:
                out_f.write(entry + "\n")
    except Exception as e:
        _log_error("collect_custom_logs open/write", e)

    # 原子写入状态文件
    tmp_state = state_path.with_suffix(state_path.suffix + ".tmp")
    try:
        with tmp_state.open("w", encoding="utf-8") as sf:
            json.dump(state, sf, ensure_ascii=False)
        os.replace(tmp_state, state_path)
    finally:
        if tmp_state.exists():
            try:
                tmp_state.unlink(missing_ok=True)
            except Exception:
                pass

    return output_path


__all__ = ["collect_custom_logs"]


def collect_timestamped_logs(
    source_directory: Union[str, Path],
    output_filename: str = "stack-total-log.txt",
    recursive: bool = False,
    days: Optional[int] = None,
) -> Path:
    """
    收集目录下形如 "{uuid}-{timestamp}-log.txt" 的日志文件，并按修改时间从旧到新合并到一个文件中。

    行为要点：
    - 默认仅遍历指定目录第一层；若 recursive=True 则递归子目录。
    - 按文件最后修改时间 (mtime) 升序合并。
    - 若提供 days，则尝试从文件名解析 timestamp（优先匹配以 4 位年份开头的部分），
      若解析成功且时间早于 cutoff，则跳过该文件；若解析失败则保留该文件。
    - 不对日志行做任何修改；直接按文件内容原样写入输出文件（覆盖写模式）。

    返回：输出文件 Path 对象。
    """
    base_dir = Path(source_directory)
    if not base_dir.exists() or not base_dir.is_dir():
        raise FileNotFoundError(f"Directory not found or not a directory: {base_dir}")

    output_path = Path(output_filename)
    if not output_path.is_absolute():
        output_path = base_dir / output_path

    pattern = "**/*-log.txt" if recursive else "*-log.txt"

    candidates = (p for p in base_dir.glob(pattern) if p.is_file() and p.resolve() != output_path.resolve())

    # 按修改时间排序
    sorted_logs = sorted(candidates, key=lambda p: p.stat().st_mtime)

    cutoff = None
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)

    # 匹配优先级：
    # 1) UUID + epoch 秒，例如: <uuid>-1761291448-log.txt
    # 2) 以 4 位年份开头的 timestamp 段，例如: <uuid>-2025-09-26T16:46:39-log.txt
    # 3) 最通用的 <uuid>-<ts>-log.txt
    uuid_epoch_pattern = re.compile(r"^(?P<uuid>[0-9a-fA-F-]{36})-(?P<ts>\d+)-log\.txt$")
    # ts_year_pattern = re.compile(r"^(?P<uuid>.+)-(?P<ts>\d{4}.*)-log\.txt$")
    # generic_pattern = re.compile(r"^(?P<uuid>.+)-(?P<ts>.+)-log\.txt$")

    # 尝试解析多种常见时间格式
    def _parse_ts(ts_raw: str) -> Optional[datetime]:
        fmts = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y%m%d%H%M%S",
            "%Y%m%d",
            "%Y-%m-%dT%H-%M-%S",
            "%Y-%m-%d_%H-%M-%S",
        ]
        # 尝试逐个格式解析（只尝试前面一部分以容忍额外的子秒或时区）
        for fmt in fmts:
            try:
                # 截取与格式长度相匹配的前缀再解析
                example_len = len(datetime.now().strftime(fmt))
                candidate = ts_raw[: example_len]
                return datetime.strptime(candidate, fmt)
            except Exception:
                continue
        return None


    # 增量合并：记录每个文件已复制的行数
    global state_file
    # 状态文件统一为全局 state_file
    state_path = output_path.parent / state_file
    try:
        with state_path.open("r", encoding="utf-8") as sf:
            state: Dict[str, Dict[str, int]] = json.load(sf) or {}
    except Exception:
        state = {}


    # 收集所有待写入日志条目到内存，排序后统一写入
    log_entries = []
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        line_ts_pattern = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\|")

        for log_file in sorted_logs:
            try:
                m = uuid_epoch_pattern.match(log_file.name)
                if not m:
                    continue
                # ts_raw = m.group("ts")
                file_uuid = m.group("uuid") if "uuid" in m.groupdict() else None

                file_key = str(log_file.resolve())
                prev = state.get(file_key) or {}
                prev_offset = int(prev.get("offset", 0))

                with log_file.open("r", encoding="utf-8", errors="replace") as src:
                    for idx, line in enumerate(src):
                        if idx < prev_offset:
                            continue
                        if days is not None:
                            lm = line_ts_pattern.match(line)
                            if not lm:
                                continue
                            ts_str = lm.group("ts")
                            try:
                                if "." in ts_str:
                                    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
                                    if not ts_str.endswith("Z"):
                                        fmt = "%Y-%m-%dT%H:%M:%S.%f"
                                else:
                                    fmt = "%Y-%m-%dT%H:%M:%SZ"
                                    if not ts_str.endswith("Z"):
                                        fmt = "%Y-%m-%dT%H:%M:%S"
                                ts = datetime.strptime(ts_str, fmt)
                                if cutoff is not None and ts < cutoff:
                                    continue
                            except Exception:
                                continue
                        # 跳过空白行
                        if not line.strip():
                            continue
                        # 提取时间戳对象
                        lm = line_ts_pattern.match(line)
                        entry_ts = None
                        if lm:
                            ts_str = lm.group("ts")
                            try:
                                if "." in ts_str:
                                    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
                                    if not ts_str.endswith("Z"):
                                        fmt = "%Y-%m-%dT%H:%M:%S.%f"
                                else:
                                    fmt = "%Y-%m-%dT%H:%M:%SZ"
                                    if not ts_str.endswith("Z"):
                                        fmt = "%Y-%m-%dT%H:%M:%S"
                                entry_ts = datetime.strptime(ts_str, fmt)
                            except Exception:
                                entry_ts = None
                        # 按时间戳排序，无时间戳则用文件 mtime
                        sort_key = entry_ts if entry_ts is not None else datetime.fromtimestamp(log_file.stat().st_mtime)
                        if file_uuid:
                            log_entries.append((sort_key, f"{file_uuid}|{line}"))
                        else:
                            log_entries.append((sort_key, line))
                    # 记录新偏移
                    state[file_key] = {"offset": idx + 1}
            except Exception as e:
                _log_error(f"collect_stack_logs processing [{log_file}]", e)
                continue
        # 按时间戳排序所有条目
        log_entries.sort(key=lambda x: x[0])
        with output_path.open("a", encoding="utf-8") as out_f:
            for _, entry in log_entries:
                out_f.write(entry)
    except Exception as e:
        _log_error("collect_stack_logs open/write", e)

    # 原子写入状态文件
    tmp_state = state_path.with_suffix(state_path.suffix + ".tmp")
    try:
        with tmp_state.open("w", encoding="utf-8") as sf:
            json.dump(state, sf, ensure_ascii=False)
        os.replace(tmp_state, state_path)
    finally:
        if tmp_state.exists():
            try:
                tmp_state.unlink(missing_ok=True)
            except Exception:
                pass

    return output_path


def prune_total_log(
    source_directory: Union[str, Path],
    output_filename: str = "total-log.txt",
    days: int = 30,
    max_remove_lines: Optional[int] = 1000,
) -> Dict[str, int]:
    """
    仅清理聚合日志文件（total-log.txt）中的旧日志行，原始 *-custom-log.txt 保持不变。

    行匹配规则：以 "[YYYY-MM-DD HH:MM:SS(.ffffff)]" 开头的时间戳行按时间判断，
    早于当前时刻 N 天的行会被删除。非匹配行（如分隔头）保留。

    参数:
        source_directory: total-log.txt 所在目录。
        output_filename: 聚合日志文件名（默认为 "total-log.txt"）。
        days: 保留最近 N 天内的日志，默认 30 天。

    增强特性:
        - max_remove_lines: 单次最多删除的行数（包含被删除时间戳行及其后续非时间戳续行）。
          为了保持日志条目完整性，若命中上限于某条日志中间，则会继续删除该条日志的续行，
          并在下一条时间戳行开始处停止，剩余行原样保留给下次清理。

    返回:
        {"removed": x, "kept": y}
    """
    base_dir = Path(source_directory)
    if not base_dir.exists() or not base_dir.is_dir():
        raise FileNotFoundError(f"Directory not found or not a directory: {base_dir}")

    total_log_path = Path(output_filename)
    if not total_log_path.is_absolute():
        total_log_path = base_dir / total_log_path

    if not total_log_path.exists():
        raise FileNotFoundError(f"total log not found: {total_log_path}")

    cutoff = datetime.now() - timedelta(days=days)
    ts_pattern = re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\]")

    temp_path = total_log_path.with_suffix(total_log_path.suffix + ".tmp")
    removed = 0
    kept = 0

    try:
        with total_log_path.open("r", encoding="utf-8", errors="replace") as in_f, temp_path.open(
            "w", encoding="utf-8"
        ) as out_f:
            skip_continuations = False
            reached_limit = False
            for line in in_f:
                if skip_continuations:
                    # 删除被标记的旧日志的后续非时间戳行，直到遇到下一条时间戳
                    if ts_pattern.match(line):
                        skip_continuations = False
                        if reached_limit:
                            # 达到上限且刚结束一条旧日志，后续全部原样保留
                            kept += 1
                            out_f.write(line)
                            # 将剩余行原样拷贝
                            for rest in in_f:
                                kept += 1
                                out_f.write(rest)
                            break
                        # 未达上限则继续常规处理（继续进入时间戳逻辑）
                        # 注意：不要 continue，这样下方通用逻辑会重新判断该时间戳行
                    else:
                        removed += 1
                        # 即使超过上限也会继续删除当前日志的续行，保持条目完整
                        continue

                if reached_limit:
                    kept += 1
                    out_f.write(line)
                    continue

                keep_line = True
                m = ts_pattern.match(line)
                if m:
                    raw_ts = m.group("ts")
                    if "." in raw_ts:
                        base, frac = raw_ts.split(".", 1)
                        frac6 = (frac + "000000")[:6]
                        norm = f"{base}.{frac6}"
                        fmt = "%Y-%m-%d %H:%M:%S.%f"
                    else:
                        norm = raw_ts
                        fmt = "%Y-%m-%d %H:%M:%S"
                    try:
                        ts = datetime.strptime(norm, fmt)
                        if ts < cutoff:
                            keep_line = False
                            skip_continuations = True
                    except Exception:
                        keep_line = True

                if keep_line:
                    kept += 1
                    out_f.write(line)
                else:
                    removed += 1
                    if max_remove_lines is not None and removed >= max_remove_lines:
                        reached_limit = True

        try:
            os.replace(temp_path, total_log_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

        return {"removed": removed, "kept": kept}
    except Exception as e:
        _log_error("prune_total_log", e)
        return {"removed": removed, "kept": kept}


__all__.append("prune_total_log")


def delete_total_log(
    source_directory: Union[str, Path],
    output_filename: str = "total-log.txt",
    max_retries: int = 10,
) -> bool:
    """
    删除聚合日志文件（例如 total-log.txt）。

    - 在 Windows 上若文件被占用，删除可能返回拒绝访问/共享冲突；本方法内置重试与退避。
    - 文件不存在视为成功。

    返回:
        True 表示删除成功或文件不存在；False 表示最终未能删除。
    """
    try:
        base_dir = Path(source_directory)
        if not base_dir.exists() or not base_dir.is_dir():
            raise FileNotFoundError(f"Directory not found or not a directory: {base_dir}")

        total_log_path = Path(output_filename)
        if not total_log_path.is_absolute():
            total_log_path = base_dir / total_log_path

        if not total_log_path.exists():
            return True

        for attempt in range(1, max_retries + 1):
            try:
                os.remove(total_log_path)
                return True
            except FileNotFoundError:
                return True
            except PermissionError as e:
                logger.warning(
                    "delete_total_log: unlink retry %d/%d due to PermissionError: %s",
                    attempt,
                    max_retries,
                    e,
                )
            except OSError as e:
                winerr = getattr(e, "winerror", None)
                if winerr in (5, 32):
                    # 5: Access denied, 32: Sharing violation
                    logger.warning(
                        "delete_total_log: unlink retry %d/%d due to WinError %s",
                        attempt,
                        max_retries,
                        winerr,
                    )
                else:
                    _log_error("delete_total_log", e)
                    return False

            time.sleep(min(0.2 * attempt, 2.0))

        logger.error(
            "delete_total_log: failed to delete %s after %d attempts",
            total_log_path,
            max_retries,
        )
        return False
    except Exception as e:
        _log_error("delete_total_log", e)
        return False


__all__.append("delete_total_log")


def run_log_maintenance_loop(
    source_directory: Union[str, Path],
    output_filename: str = "total-log.txt",
    collect_interval_seconds: int = 20,
    prune_days: int = 2,
) -> None:
    """
    公共时间循环：
    - 每分钟（超过 collect_interval_seconds）调用一次 collect_custom_logs
    - 每天（日期变更时）调用一次 prune_total_log

    参数:
        source_directory: 扫描目录。
        output_filename: 聚合日志输出文件名（相对 source_directory 或绝对路径）。
        collect_interval_seconds: 调用 collect 的时间间隔，默认 60 秒。
        prune_days: prune_total_log 的天数窗口，默认 30 天。
    """
    last_collect_at: datetime | None = None
    last_prune_date = datetime.now().date()
    first_run = True
    stack_log_filename = "stack-" + output_filename

    while True:
        now = datetime.now()

        if first_run:
            first_run = False
            delete_total_log(source_directory, output_filename=output_filename)
            delete_total_log(source_directory, output_filename=stack_log_filename)

        if last_collect_at is None or (now - last_collect_at).total_seconds() >= collect_interval_seconds:
            try:
                collect_custom_logs(source_directory, output_filename=output_filename, recursive=True, days=prune_days)
                collect_timestamped_logs(source_directory, output_filename=stack_log_filename, recursive=True, days=prune_days)
                last_collect_at = now

            except Exception as e:
                _log_error("run_log_maintenance_loop.collect_custom_logs", e)

        if last_prune_date != now.date():
            try:
                delete_total_log(source_directory, output_filename=output_filename)
                delete_total_log(source_directory, output_filename=stack_log_filename)
                last_prune_date = now.date()
            except Exception as e:
                _log_error("run_log_maintenance_loop.delete_total_log", e)

        time.sleep(10)


__all__.append("run_log_maintenance_loop")


if __name__ == "__main__":
    # collect_custom_logs("C:\\Users\\404\\Downloads")
    # run_log_maintenance_loop("C:\\Users\\404\\Downloads")
    run_log_maintenance_loop("C:\\Users\\Administrator\\.unity-mcp\\logs")