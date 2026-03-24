#!/usr/bin/env python3
"""
Google Gemini solver for gamedev benchmark tasks.
Uses Gemini CLI (https://github.com/google-gemini/gemini-cli) for task completion.
"""

import asyncio
import json
import time
import os
from pathlib import Path
from contextlib import contextmanager
from datetime import timedelta
from typing import Optional

from gamedevbench.src.base_solver import BaseSolver
from gamedevbench.src.utils.data_types import SolverResult, TokenUsage
from gamedevbench.src.utils.prompts import create_system_prompt, create_task_prompt


class GeminiSolver(BaseSolver):
    """Solver that uses Google Gemini CLI to complete game development tasks."""

    # Solver capabilities (required by BaseSolver)
    SUPPORTS_MCP = True
    SUPPORTS_SYSTEM_PROMPT = False
    MCP_SERVER_ALIAS = os.environ.get("GAMEDEVBENCH_MCP_SERVER_ALIAS", "game")
    LEGACY_MCP_SERVER_ALIASES = ("threejs",)

    def __init__(
        self,
        timeout_seconds: int = 600,
        debug: bool = False,
        use_yolo: bool = True,  # Auto-approve all actions
        model: Optional[str] = None,  # Model name to use with --model flag
        use_mcp: bool = False,
        use_runtime_video: bool = False,
    ):
        """Initialize the Gemini solver.

        Args:
            timeout_seconds: Maximum time to wait for completion
            debug: Enable verbose output
            use_yolo: Use --yolo flag to auto-approve all actions
            model: Model name to pass via --model flag (optional)
            use_mcp: Whether to use MCP tools (ensures the game MCP server is configured via Gemini CLI)
            use_runtime_video: Whether to append Godot runtime video instructions to prompts
        """
        # Call parent constructor (handles MCP validation)
        super().__init__(timeout_seconds, debug, use_mcp, use_runtime_video)

        # Gemini-specific parameters
        self.use_yolo = use_yolo
        self.model = model
        self.cli_bin = os.environ.get("GEMINI_CLI_BIN", "gemini")

    def _build_subprocess_env(self) -> dict:
        """Build environment for Gemini CLI with Vertex global defaults."""
        env = os.environ.copy()
        # Prefer explicitly exported values; default to global if unset.
        env.setdefault("GOOGLE_CLOUD_LOCATION", "global")
        env.setdefault("VERTEXAI_LOCATION", "global")
        # Force Gemini CLI to use project-local config instead of ~/.gemini.
        project_root = Path(__file__).resolve().parents[2]
        env.setdefault("GEMINI_CLI_HOME", str(project_root / ".gemini"))

        # Keep proxies for internet access, but always bypass localhost MCP.
        for key in ("NO_PROXY", "no_proxy"):
            cur = env.get(key, "")
            required = ["127.0.0.1", "localhost"]
            items = [x.strip() for x in cur.split(",") if x.strip()]
            for host in required:
                if host not in items:
                    items.append(host)
            env[key] = ",".join(items)

        # Vertex auth requires project id. Infer from service-account file if missing.
        if env.get("GOOGLE_APPLICATION_CREDENTIALS") and not env.get("GOOGLE_CLOUD_PROJECT"):
            cred_path = env["GOOGLE_APPLICATION_CREDENTIALS"]
            try:
                with open(cred_path, "r", encoding="utf-8") as f:
                    cred = json.load(f)
                project_id = cred.get("project_id")
                if project_id:
                    env["GOOGLE_CLOUD_PROJECT"] = project_id
            except Exception:
                # Best effort only; Gemini CLI will surface a clear auth error if still missing.
                pass

        return env

    @staticmethod
    def _get_excluded_mcp_tools() -> list[str]:
        """Return MCP tool names hidden from Gemini by default."""
        excluded_tools = os.environ.get(
            "GAMEDEVBENCH_MCP_EXCLUDE_TOOLS",
            "read_console,publish_game_version,run_playability_test",
        )
        return [tool.strip() for tool in excluded_tools.split(",") if tool.strip()]

    @staticmethod
    def _filter_excluded_mcp_tools(tool_names: list[str], excluded_tools: list[str]) -> list[str]:
        """Apply the same tool exclusion policy used by the stdio bridge."""
        excluded = set(excluded_tools)
        return [name for name in tool_names if name not in excluded]

    @staticmethod
    def is_rate_limit_error(error_message: str) -> bool:
        """Check if the error message indicates API rate limit or quota exceeded."""
        error_lower = error_message.lower()
        rate_limit_keywords = [
            "rate limit",
            "rate_limit",
            "ratelimit",
            "quota exceeded",
            "quota_exceeded",
            "429",
            "too many requests",
            "resource exhausted",
            "resource_exhausted",
        ]
        return any(keyword in error_lower for keyword in rate_limit_keywords)

    async def _ensure_mcp_server_configured(self) -> bool:
        """Ensure the target MCP server is configured in Gemini CLI.

        Checks if server exists, adds it if missing.

        Returns:
            True if server is configured, False otherwise
        """
        env = self._build_subprocess_env()
        run_canvas_id = env.get("GAMEDEVBENCH_RUN_CANVAS_ID", "").strip()
        run_trace_id = env.get("GAMEDEVBENCH_RUN_TRACE_ID", "").strip()

        # Tools we want hidden from MCP discovery by default.
        # Override with env var, e.g. GAMEDEVBENCH_MCP_EXCLUDE_TOOLS="read_console,publish_game_version".
        excluded_tools = ",".join(self._get_excluded_mcp_tools())

        # Check if server is already configured by listing MCP servers
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_bin, "mcp", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout = (stdout_bytes or b"").decode(errors="ignore")
            stderr = (stderr_bytes or b"").decode(errors="ignore")
            mcp_text = f"{stdout}\n{stderr}"

            stale_aliases = [
                alias for alias in self.LEGACY_MCP_SERVER_ALIASES
                if alias != self.MCP_SERVER_ALIAS and alias in mcp_text
            ]
            expected_env_tokens = []
            if run_canvas_id:
                expected_env_tokens.append(f"GAMEDEVBENCH_RUN_CANVAS_ID={run_canvas_id}")
            if run_trace_id:
                expected_env_tokens.append(f"GAMEDEVBENCH_RUN_TRACE_ID={run_trace_id}")
            env_matches = all(token in mcp_text for token in expected_env_tokens)
            requires_run_scoped_reconfigure = bool(run_canvas_id)

            # If the stdio bridge is present with expected exclude flag, reuse it only
            # when no stale legacy aliases remain configured in Gemini CLI home.
            if (
                self.MCP_SERVER_ALIAS in mcp_text
                and "stdio" in mcp_text
                and "mcp_http_stdio_bridge.py" in mcp_text
                and "--exclude-tools" in mcp_text
                and excluded_tools in mcp_text
                and env_matches
                and not stale_aliases
                and not requires_run_scoped_reconfigure
            ):
                if self.debug:
                    print(f"MCP server {self.MCP_SERVER_ALIAS} stdio bridge is already configured")
                return True

            # Reconfigure the MCP server as stdio bridge.
            if self.debug:
                print(
                    f"Configuring MCP server {self.MCP_SERVER_ALIAS} as stdio bridge "
                    "(to http://127.0.0.1:6601/mcp)..."
                )

            project_root = Path(__file__).resolve().parents[2]
            bridge_script = project_root / "gamedevbench" / "src" / "mcp_http_stdio_bridge.py"

            # Best-effort cleanup of the current alias plus legacy aliases from previous runs.
            aliases_to_remove = [self.MCP_SERVER_ALIAS, *stale_aliases]
            for alias in aliases_to_remove:
                rm_proc = await asyncio.create_subprocess_exec(
                    self.cli_bin,
                    "mcp",
                    "remove",
                    alias,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                await rm_proc.communicate()

            proc = await asyncio.create_subprocess_exec(
                self.cli_bin,
                "mcp",
                "add",
                "--scope",
                "user",
                "--timeout",
                "60000",
                self.MCP_SERVER_ALIAS,
                "uv",
                "run",
                "--directory",
                str(project_root),
                "python",
                str(bridge_script),
                "--url",
                "http://127.0.0.1:6601/mcp",
                "--exclude-tools",
                excluded_tools,
                *(
                    ["--env", f"GAMEDEVBENCH_RUN_CANVAS_ID={run_canvas_id}"]
                    if run_canvas_id
                    else []
                ),
                *(
                    ["--env", f"GAMEDEVBENCH_RUN_TRACE_ID={run_trace_id}"]
                    if run_trace_id
                    else []
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await proc.communicate()

            if proc.returncode == 0:
                if self.debug:
                    print(f"MCP server {self.MCP_SERVER_ALIAS} added successfully")
                return True
            else:
                if self.debug:
                    print(f"Failed to add MCP server (exit code: {proc.returncode})")
                return False

        except Exception as e:
            if self.debug:
                print(f"Error configuring MCP server: {e}")
            return False

    @contextmanager
    def _local_no_proxy_scope(self):
        """Temporarily disable proxy env vars so local MCP HTTP checks bypass proxies."""
        proxy_keys = [
            "HTTPS_PROXY",
            "https_proxy",
            "HTTP_PROXY",
            "http_proxy",
            "ALL_PROXY",
            "all_proxy",
        ]
        old = {k: os.environ.get(k) for k in proxy_keys + ["NO_PROXY", "no_proxy"]}
        try:
            for k in proxy_keys:
                os.environ.pop(k, None)
            os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
            os.environ["no_proxy"] = "127.0.0.1,localhost,::1"
            yield
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    async def _probe_mcp_tools(self, url: str = "http://127.0.0.1:6601/mcp") -> tuple[bool, list[str], str]:
        """Probe external MCP endpoint and return (connected, tool_names, error_msg)."""
        try:
            from mcp.client.streamable_http import streamablehttp_client
            from mcp.client.session import ClientSession
        except Exception as e:
            return False, [], f"mcp client import failed: {e}"

        try:
            with self._local_no_proxy_scope():
                async with streamablehttp_client(url=url) as streams:
                    try:
                        read, write, _ = streams
                    except Exception:
                        read, write = streams
                    async with ClientSession(
                        read,
                        write,
                        read_timeout_seconds=timedelta(seconds=15),
                    ) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        names = [t.name for t in tools.tools]
                        return True, names, ""
        except Exception as e:
            return False, [], str(e)

    def _runtime_mcp_tool_names(self, raw_tool_names: list[str]) -> list[str]:
        """Return the Gemini runtime-visible MCP tool names for the configured server alias."""
        prefix = f"mcp_{self.MCP_SERVER_ALIAS}_"
        return [f"{prefix}{name}" for name in raw_tool_names]

    async def solve_task_async(self) -> SolverResult:
        """Solve the task in the current directory using Gemini CLI."""
        config = self.load_config()
        if not config:
            return SolverResult(
                success=False,
                message="Could not load task configuration",
                duration_seconds=0.0,
            )

        start_time = time.time()
        task_prompt = create_task_prompt(
            config,
            use_runtime_video=self.use_runtime_video,
            use_mcp=self.use_mcp,
            include_edit_flow=False,
        )
        # Historical behavior kept for reference:
        # Gemini CLI previously received a pseudo system prompt via the main user prompt.
        # Now that GEMINI.md is confirmed to flow into Gemini's actual system context,
        # repeating those instructions here is redundant and makes the task prompt noisy.
        #
        # pseudo_system_prompt = create_system_prompt(self.use_mcp)
        # prompt = (
        #     "Follow the following system-level instructions with high priority.\n\n"
        #     "<system_instructions>\n"
        #     f"{pseudo_system_prompt}\n"
        #     "</system_instructions>\n\n"
        #     "<task>\n"
        #     f"{task_prompt}\n"
        #     "</task>"
        # )
        prompt = task_prompt

        # Ensure MCP server is configured if requested
        if self.use_mcp:
            mcp_configured = await self._ensure_mcp_server_configured()
            if not mcp_configured and self.debug:
                print("Warning: Could not configure MCP server. Continuing without external MCP tools.")
            # Debug probe + prompt augmentation with discovered tool inventory.
            connected, tool_names, probe_err = await self._probe_mcp_tools()
            visible_tool_names = self._filter_excluded_mcp_tools(
                tool_names,
                self._get_excluded_mcp_tools(),
            )
            if self.debug:
                if connected:
                    runtime_tool_names = self._runtime_mcp_tool_names(visible_tool_names)
                    print(
                        f"MCP probe success: {self.MCP_SERVER_ALIAS} reachable, "
                        f"raw_tools={len(tool_names)} visible_tools={len(visible_tool_names)}"
                    )
                    print("MCP raw tools: " + ", ".join(tool_names))
                    print("MCP visible tools: " + ", ".join(visible_tool_names))
                    print("MCP runtime tools: " + ", ".join(runtime_tool_names))
                else:
                    print(f"MCP probe failed: {probe_err}")
            if connected and visible_tool_names:
                runtime_tool_names = self._runtime_mcp_tool_names(visible_tool_names)
                prompt += (
                    "\n\nExternal MCP context:\n"
                    "Runtime MCP tool names for this run: " + ", ".join(runtime_tool_names) + "\n"
                    "Call MCP tools only by the exact runtime names listed above. "
                    "Use these MCP tools when they improve task certainty or execution reliability. "
                    "For required deliverables, treat local workspace files as the source of truth and verify them before completion. "
                    "If an MCP call fails or is clearly not applicable, fall back to generic local file/shell operations."
                )

        if self.debug:
            print("=" * 60)
            print("SENDING PROMPT TO GEMINI CLI:")
            print("=" * 60)
            print(prompt)
            print("=" * 60)

        try:
            # Build gemini command
            cmd = [self.cli_bin]
            env = self._build_subprocess_env()

            if self.use_yolo:
                cmd.append("--yolo")

            if self.model:
                cmd.extend(["--model", self.model])

            if self.debug:
                cmd.extend(["--output-format", "stream-json"])

            cmd.extend(["-p", prompt])

            if self.debug:
                print(f"\nRunning: {' '.join(cmd[:3])} -p \"...\"")
                print("\nGEMINI TRAJECTORY:")
                print("=" * 60)

            # Run Gemini CLI
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=os.getcwd(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                duration = time.time() - start_time
                return SolverResult(
                    success=False,
                    message=f"Gemini CLI timed out after {self.timeout_seconds}s",
                    duration_seconds=duration,
                )

            duration = time.time() - start_time
            stdout = (stdout_bytes or b"").decode(errors="ignore")
            stderr = (stderr_bytes or b"").decode(errors="ignore")

            if self.debug:
                if stdout:
                    print(stdout)
                if stderr:
                    print(f"\nStderr: {stderr}")
                print(f"\n\nDuration: {duration:.2f} seconds")
                print(f"Exit code: {proc.returncode}")
                print("=" * 60)

            # Parse token usage and model info if available (from JSON output)
            token_usage = self._parse_token_usage(stdout)
            model_used = self._parse_model_name(stdout) or "gemini"

            # Calculate cost
            cost_usd = 0.0
            if token_usage:
                cost_usd = token_usage.calculate_cost(model_used)

            if self.debug and token_usage:
                print(f"Tokens: input={token_usage.input_tokens}, output={token_usage.output_tokens}, total={token_usage.total_tokens}")
                print(f"Cost: ${cost_usd:.4f}")

            # Check for errors in stderr
            combined_output = stdout if not stderr else f"{stdout}\n{stderr}"

            return SolverResult(
                success=proc.returncode == 0,
                message="Task completed" if proc.returncode == 0 else f"Gemini CLI exited with code {proc.returncode}",
                duration_seconds=duration,
                stdout=stdout,
                stderr=stderr,
                token_usage=token_usage,
                model=model_used,
                cost_usd=cost_usd,
            )

        except FileNotFoundError:
            return SolverResult(
                success=False,
                message=f"Gemini CLI not found: {self.cli_bin}. Install/configure your Gemini CLI binary.",
                duration_seconds=0.0,
            )
        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e)
            is_rate_limited = self.is_rate_limit_error(error_msg)

            if self.debug:
                print(f"\nERROR INVOKING GEMINI CLI: {error_msg}")
                if is_rate_limited:
                    print("⚠️  DETECTED RATE LIMIT/QUOTA ERROR")
                print("=" * 60)

            return SolverResult(
                success=False,
                message=f"Error invoking Gemini CLI: {error_msg}",
                duration_seconds=duration,
                is_rate_limited=is_rate_limited,
            )

    def _parse_token_usage(self, output: str) -> Optional[TokenUsage]:
        """Parse JSON output to extract token usage information.

        Gemini CLI with --output-format stream-json outputs events like:
        {"type": "usage", "input_tokens": 123, "output_tokens": 456}
        """
        total_input = 0
        total_output = 0
        total_cached = 0

        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)

                # Look for usage information in various formats
                if event.get("type") == "usage":
                    total_input += event.get("input_tokens", 0)
                    total_output += event.get("output_tokens", 0)
                    total_cached += event.get("cached_tokens", 0)

                # Also check for usage nested in other events
                usage = event.get("usage", {})
                if usage:
                    total_input += usage.get("input_tokens", 0)
                    total_output += usage.get("output_tokens", 0)
                    total_cached += usage.get("cached_tokens", 0)

            except json.JSONDecodeError:
                # Not a JSON line, skip
                continue

        if total_input > 0 or total_output > 0:
            return TokenUsage(
                input_tokens=total_input,
                output_tokens=total_output,
                total_tokens=total_input + total_output,
                cache_read_tokens=total_cached,
                cache_write_tokens=0,
            )
        return None

    def _parse_model_name(self, output: str) -> Optional[str]:
        """Parse JSON output to extract the model name."""
        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
                model = event.get("model")
                if model:
                    return model
            except json.JSONDecodeError:
                continue
        return None

    def solve_task(self) -> SolverResult:
        """Synchronous wrapper for async solve_task_async."""
        return asyncio.run(self.solve_task_async())


def main():
    """Main function for testing the solver."""
    solver = GeminiSolver(debug=True)
    result = solver.solve_task()
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Message: {result.message}")
    print(f"Duration: {result.duration_seconds:.2f}s")
    if result.token_usage:
        print(f"Tokens: {result.token_usage.total_tokens}")
        print(f"Cost: ${result.cost_usd:.4f}")


if __name__ == "__main__":
    main()
