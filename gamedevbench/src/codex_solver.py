#!/usr/bin/env python3
"""
OpenAI Codex solver for gamedev benchmark tasks.
Uses Codex CLI for OpenAI-compatible models, and Gemini CLI (Vertex path)
for Gemini models when OpenAI-compatible endpoint is not configured.
"""

import json
import time
import os
import subprocess
from pathlib import Path
from typing import Optional

from gamedevbench.src.base_solver import BaseSolver
from gamedevbench.src.utils.data_types import SolverResult, TokenUsage


class CodexSolver(BaseSolver):
    """Solver that uses OpenAI Codex CLI to complete game development tasks."""

    # Solver capabilities (required by BaseSolver)
    SUPPORTS_MCP = True
    SUPPORTS_SYSTEM_PROMPT = False  # Codex embeds context in main prompt

    def __init__(
        self,
        timeout_seconds: int = 600,
        debug: bool = False,
        use_mcp: bool = False,
        model: Optional[str] = None,
        approval_policy: str = "never",      # untrusted | on-failure | on-request | never
        sandbox: str = "workspace-write",    # read-only | workspace-write | danger-full-access
        use_runtime_video: bool = False,
        api_base: Optional[str] = None,
    ):
        # Call parent constructor (handles MCP validation)
        super().__init__(timeout_seconds, debug, use_mcp, use_runtime_video)

        # Codex-specific parameters
        self.model = model
        self.approval_policy = approval_policy
        self.sandbox = sandbox
        self.api_base = (
            api_base
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("GEMINI_API_BASE")
        )
        self.gemini_cli_bin = os.environ.get("GEMINI_CLI_BIN", "gemini")
        # User-local default for Vertex service account (can override via env).
        self.vertex_credentials_default = os.environ.get(
            "GEMINI_VERTEX_CREDENTIALS",
            "/home/seele003/TTS/gamedevbench-bp/seeles-test-service-account.json",
        )

        # Only configure MCP if enabled
        if use_mcp:
            self._ensure_mcp_config()

    def _ensure_mcp_config(self):
        """Ensure ~/.codex/config.toml contains godot-screenshot MCP server config."""
        config_dir = Path.home() / ".codex"
        config_file = config_dir / "config.toml"

        mcp_config = '''
[mcp_servers.godot-screenshot]
command = "uv"
args = ["run", "gamedevbench-mcp"]
'''

        config_dir.mkdir(parents=True, exist_ok=True)

        if config_file.exists():
            content = config_file.read_text()
            if "godot-screenshot" not in content:
                # Append MCP config
                with open(config_file, 'a') as f:
                    f.write("\n" + mcp_config)
                if self.debug:
                    print(f"Added godot-screenshot MCP config to {config_file}")
        else:
            # Create new config file
            config_file.write_text(mcp_config.strip())
            if self.debug:
                print(f"Created Codex config at {config_file}")

    @staticmethod
    def is_rate_limit_error(error_message: str) -> bool:
        """Check if the error message indicates API rate limit."""
        error_lower = error_message.lower()
        rate_limit_keywords = [
            "rate limit", "rate_limit", "ratelimit",
            "quota exceeded", "429", "too many requests",
        ]
        return any(keyword in error_lower for keyword in rate_limit_keywords)

    @staticmethod
    def _is_gemini_model(model: Optional[str]) -> bool:
        """Check whether model name points to Gemini family."""
        if not model:
            return False
        model_lower = model.lower()
        return (
            model_lower.startswith("gemini")
            or model_lower.startswith("gemini/")
            or model_lower.startswith("google/")
        )

    def _build_subprocess_env(self) -> dict:
        """Build environment for Codex CLI with Gemini/OpenAI compatibility mapping."""
        env = os.environ.copy()

        # Allow explicit constructor override to set OpenAI-compatible endpoint.
        if self.api_base and not env.get("OPENAI_BASE_URL"):
            env["OPENAI_BASE_URL"] = self.api_base

        # Gemini-compatible backends are often OpenAI-compatible APIs with custom env names.
        if self._is_gemini_model(self.model):
            if not env.get("OPENAI_API_KEY"):
                gemini_key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
                if gemini_key:
                    env["OPENAI_API_KEY"] = gemini_key

            if not env.get("OPENAI_BASE_URL"):
                gemini_base = env.get("GEMINI_API_BASE") or env.get("GOOGLE_API_BASE")
                if gemini_base:
                    env["OPENAI_BASE_URL"] = gemini_base

        return env

    def _build_gemini_vertex_env(self) -> dict:
        """Build environment for Gemini CLI with Vertex defaults."""
        env = os.environ.copy()

        # Prefer explicitly exported credentials; otherwise use user-local default.
        if not env.get("GOOGLE_APPLICATION_CREDENTIALS") and self.vertex_credentials_default:
            if os.path.exists(self.vertex_credentials_default):
                env["GOOGLE_APPLICATION_CREDENTIALS"] = self.vertex_credentials_default

        # Force Vertex mode and avoid OAuth interactive fallback.
        env.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

        # Fill project id from service account json when missing.
        if not env.get("GOOGLE_CLOUD_PROJECT"):
            cred_path = env.get("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path and os.path.exists(cred_path):
                try:
                    with open(cred_path, "r", encoding="utf-8") as f:
                        cred_data = json.load(f)
                    project_id = cred_data.get("project_id")
                    if project_id:
                        env["GOOGLE_CLOUD_PROJECT"] = project_id
                except Exception:
                    pass

        # Required by user's Vertex workflow; keep global as default.
        env.setdefault("GOOGLE_CLOUD_LOCATION", "global")
        env.setdefault("VERTEXAI_LOCATION", "global")
        return env

    def _should_route_gemini_to_vertex_cli(self, env: dict) -> bool:
        """Route Gemini model to Gemini CLI when Vertex credentials are available."""
        if not self._is_gemini_model(self.model):
            return False

        # If OpenAI-compatible endpoint is explicitly set, keep using Codex path.
        if env.get("OPENAI_BASE_URL"):
            return False

        vertex_env = self._build_gemini_vertex_env()
        return bool(vertex_env.get("GOOGLE_APPLICATION_CREDENTIALS"))

    def _solve_with_gemini_cli(self, prompt: str, start_time: float) -> SolverResult:
        """Solve task via Gemini CLI (Vertex path) while staying in codex solver framework."""
        env = self._build_gemini_vertex_env()
        credentials = env.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not credentials:
            return SolverResult(
                success=False,
                message=(
                    "Gemini model selected but no credentials found. "
                    "Set GOOGLE_APPLICATION_CREDENTIALS or GEMINI_VERTEX_CREDENTIALS."
                ),
                duration_seconds=0.0,
            )

        cmd = [
            self.gemini_cli_bin,
            "--yolo",
            "--output-format",
            "stream-json",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.extend(["-p", prompt])

        if self.debug:
            print("\nRouting gemini model via Gemini CLI (Vertex)")
            print(f"GOOGLE_APPLICATION_CREDENTIALS: {credentials}")
            print(f"GOOGLE_CLOUD_LOCATION: {env.get('GOOGLE_CLOUD_LOCATION')}")
            print(f"VERTEXAI_LOCATION: {env.get('VERTEXAI_LOCATION')}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=os.getcwd(),
                env=env,
            )
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return SolverResult(
                success=False,
                message=f"Gemini CLI execution timed out after {self.timeout_seconds}s",
                duration_seconds=duration,
            )
        except FileNotFoundError:
            return SolverResult(
                success=False,
                message=(
                    f"Gemini CLI not found: {self.gemini_cli_bin}. "
                    "Install/configure Gemini CLI or set GEMINI_CLI_BIN."
                ),
                duration_seconds=0.0,
            )

        duration = time.time() - start_time
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        auth_prompt_detected = (
            "Please visit the following URL to authorize the application" in stdout
            or "Enter the authorization code:" in stdout
            or "authorization code" in stdout.lower()
        )
        if auth_prompt_detected:
            return SolverResult(
                success=False,
                message=(
                    "Gemini CLI entered interactive OAuth flow instead of Vertex service-account mode. "
                    "Ensure GOOGLE_GENAI_USE_VERTEXAI=true and GOOGLE_CLOUD_PROJECT are set correctly "
                    "with a valid GOOGLE_APPLICATION_CREDENTIALS."
                ),
                duration_seconds=duration,
                stdout=stdout,
                stderr=stderr,
                model=self.model or "gemini",
            )

        token_usage = self._parse_gemini_token_usage(stdout)
        final_response = self._parse_gemini_final_response(stdout) or "No response detected."
        model_used = self.model or "gemini"

        cost_usd = 0.0
        if token_usage:
            cost_usd = token_usage.calculate_cost(model_used)

        message = final_response if result.returncode == 0 else (
            f"Gemini CLI command failed (exit code {result.returncode})"
            + (f"\nSTDERR: {stderr.strip()}" if stderr.strip() else "")
            + (f"\nFinal response: {final_response}" if final_response else "")
        )

        return SolverResult(
            success=result.returncode == 0,
            message=message,
            duration_seconds=duration,
            stdout=stdout,
            stderr=stderr,
            token_usage=token_usage,
            model=model_used,
            cost_usd=cost_usd,
        )

    def solve_task(self) -> SolverResult:
        """Solve the task using Codex CLI."""
        config = self.load_config()
        if not config:
            return SolverResult(
                success=False,
                message="Could not load task configuration",
                duration_seconds=0.0,
            )

        start_time = time.time()
        prompt = self.get_task_prompt(config)

        if self.debug:
            print("=" * 60)
            print("SENDING PROMPT TO CODEX CLI:")
            print("=" * 60)
            print(prompt)
            print("=" * 60)

        try:
            env = self._build_subprocess_env()

            # Gemini path:
            # 1) If OPENAI_BASE_URL exists, keep Codex CLI (OpenAI-compatible endpoint).
            # 2) Else if Vertex credentials exist, route to Gemini CLI.
            if self._should_route_gemini_to_vertex_cli(env):
                return self._solve_with_gemini_cli(prompt, start_time)

            # Gemini selected without OpenAI-compatible route or Vertex credentials: fail fast.
            if self._is_gemini_model(self.model) and not env.get("OPENAI_BASE_URL"):
                return SolverResult(
                    success=False,
                    message=(
                        "Gemini model selected but no route found. "
                        "Use OPENAI_BASE_URL+OPENAI_API_KEY for OpenAI-compatible Gemini endpoint, "
                        "or set GOOGLE_APPLICATION_CREDENTIALS (Vertex path)."
                    ),
                    duration_seconds=0.0,
                )

            # Build codex exec command
            cmd = ["codex"]
            if self.model:
                cmd.extend(["--model", self.model])
            if self.approval_policy:
                cmd.extend(["--ask-for-approval", self.approval_policy])
            cmd.extend(
                [
                    "exec",
                    "--skip-git-repo-check",
                    "--json",
                    "-s",
                    self.sandbox,
                    "-C",
                    str(os.getcwd()),
                    prompt,
                ]
            )

            if self.debug:
                cmd_str = " ".join([c if " " not in c else f'"{c}"' for c in cmd[:-1]])
                print(f"Running: {cmd_str} \"...\"")
                print(f"OPENAI_BASE_URL set: {'yes' if env.get('OPENAI_BASE_URL') else 'no'}")
                print(f"OPENAI_API_KEY set: {'yes' if env.get('OPENAI_API_KEY') else 'no'}")
                print("\nCODEX TRAJECTORY:")
                print("=" * 60)

            # Run Codex
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=os.getcwd(),
                env=env,
            )

            duration = time.time() - start_time
            stdout = result.stdout
            stderr = result.stderr

            if self.debug:
                # Parse and print key events
                self._print_trajectory(stdout)
                print(f"\n\nDuration: {duration:.2f} seconds")
                print(f"Exit code: {result.returncode}")
                if stderr:
                    print(f"Stderr: {stderr[:500]}")
                print("=" * 60)

            # Parse final response and token usage
            final_response = self._parse_final_response(stdout)
            token_usage = self._parse_token_usage(stdout)
            model_used = self.model

            # Calculate cost
            cost_usd = 0.0
            if token_usage:
                cost_usd = token_usage.calculate_cost(model_used)

            if self.debug and token_usage:
                print(f"Tokens: input={token_usage.input_tokens}, output={token_usage.output_tokens}, total={token_usage.total_tokens}")
                print(f"Cost: ${cost_usd:.4f}")

            # Construct message: include stderr if command failed
            if result.returncode != 0:
                error_msg = f"Codex command failed (exit code {result.returncode})"
                if stderr and stderr.strip():
                    error_msg += f"\nSTDERR: {stderr.strip()}"
                if final_response:
                    error_msg += f"\nFinal response: {final_response}"
                message = error_msg
            else:
                message = final_response or "No response detected."

            return SolverResult(
                success=result.returncode == 0,
                message=message,
                duration_seconds=duration,
                stdout=stdout,
                stderr=stderr,
                token_usage=token_usage,
                model=model_used,
                cost_usd=cost_usd,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return SolverResult(
                success=False,
                message=f"Codex execution timed out after {self.timeout_seconds}s",
                duration_seconds=duration,
            )
        except FileNotFoundError:
            return SolverResult(
                success=False,
                message="Codex CLI not found. Install with: npm i -g @openai/codex",
                duration_seconds=0.0,
            )
        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e)
            is_rate_limited = self.is_rate_limit_error(error_msg)

            if self.debug:
                print(f"\nERROR INVOKING CODEX: {error_msg}")
                if is_rate_limited:
                    print("⚠️  DETECTED RATE LIMIT/QUOTA ERROR")
                print("=" * 60)

            return SolverResult(
                success=False,
                message=f"Error invoking Codex: {error_msg}",
                duration_seconds=duration,
                is_rate_limited=is_rate_limited,
            )

    def _print_trajectory(self, output: str):
        """Print key events from Codex execution trajectory."""
        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                if event_type == "turn.started":
                    print(f"\n[Turn Started]")
                elif event_type == "item.tool_call":
                    tool_name = event.get("name", "unknown")
                    args = event.get("arguments", {})
                    print(f"\n[Tool Call] {tool_name}({json.dumps(args)[:100]})")
                elif event_type == "item.tool_result":
                    print(f"[Tool Result] received")
                elif event_type == "item.message":
                    content = event.get("content", "")
                    if content:
                        preview = content[:200] + "..." if len(content) > 200 else content
                        print(f"[Message] {preview}")
                elif event_type == "turn.completed":
                    print(f"\n[Turn Completed]")
                elif event_type == "item.file_edit":
                    file_path = event.get("path", "unknown")
                    print(f"[File Edit] {file_path}")
                elif event_type == "item.shell_command":
                    cmd = event.get("command", "")
                    print(f"[Shell] {cmd[:100]}")

            except json.JSONDecodeError:
                # Non-JSON line, possibly error message
                if line.strip() and self.debug:
                    print(f"[Raw] {line[:100]}")

    def _parse_final_response(self, output: str) -> Optional[str]:
        """Parse JSON Lines output to get final response."""
        final_response = None
        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "turn.completed":
                    final_response = event.get("finalResponse", "")
                elif event.get("type") == "item.message":
                    # Save last message as fallback
                    content = event.get("content", "")
                    if content:
                        final_response = content
            except json.JSONDecodeError:
                continue
        return final_response

    def _parse_token_usage(self, output: str) -> Optional[TokenUsage]:
        """Parse JSON Lines output to get token usage."""
        total_input = 0
        total_output = 0
        total_cached = 0

        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                # Codex JSON output may have token_count events or usage in turn.completed
                if event_type == "token_count":
                    # Handle token_count event type
                    total_input += event.get("input_tokens", 0)
                    total_output += event.get("output_tokens", 0)
                    total_cached += event.get("cached_tokens", 0)
                elif event_type == "turn.completed":
                    # Check for usage info in turn.completed
                    usage = event.get("usage", {})
                    if usage:
                        total_input += usage.get("input_tokens", 0)
                        total_output += usage.get("output_tokens", 0)
                        total_cached += usage.get("cached_tokens", 0)
                elif event_type == "response.completed":
                    # Alternative: response.completed may have usage
                    usage = event.get("usage", {})
                    if usage:
                        total_input += usage.get("input_tokens", 0)
                        total_output += usage.get("output_tokens", 0)
                        total_cached += usage.get("cache_read_input_tokens", 0)

                # Also check payload.type for nested events
                payload = event.get("payload", {})
                if isinstance(payload, dict):
                    payload_type = payload.get("type", "")
                    if payload_type == "token_count":
                        total_input += payload.get("input_tokens", 0)
                        total_output += payload.get("output_tokens", 0)
                        total_cached += payload.get("cached_tokens", 0)

            except json.JSONDecodeError:
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

    def _parse_gemini_token_usage(self, output: str) -> Optional[TokenUsage]:
        """Parse Gemini stream-json output for token usage."""
        total_input = 0
        total_output = 0
        total_cached = 0

        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "usage":
                total_input += event.get("input_tokens", 0)
                total_output += event.get("output_tokens", 0)
                total_cached += event.get("cached_tokens", 0)

            usage = event.get("usage", {})
            if isinstance(usage, dict) and usage:
                total_input += usage.get("input_tokens", 0)
                total_output += usage.get("output_tokens", 0)
                total_cached += usage.get("cached_tokens", 0)

        if total_input > 0 or total_output > 0:
            return TokenUsage(
                input_tokens=total_input,
                output_tokens=total_output,
                total_tokens=total_input + total_output,
                cache_read_tokens=total_cached,
                cache_write_tokens=0,
            )
        return None

    def _parse_gemini_final_response(self, output: str) -> Optional[str]:
        """Parse Gemini stream-json output for final text."""
        final_response = None
        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            if event_type in ("assistant", "message", "content"):
                text = event.get("text") or event.get("content")
                if isinstance(text, str) and text.strip():
                    final_response = text

            if event_type in ("final", "done", "response") and isinstance(event.get("text"), str):
                final_response = event.get("text")

        return final_response


def main():
    """Main function for testing the solver."""
    solver = CodexSolver(debug=True)
    result = solver.solve_task()
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Message: {result.message[:500] if result.message else 'None'}")
    print(f"Duration: {result.duration_seconds:.2f}s")


if __name__ == "__main__":
    main()
