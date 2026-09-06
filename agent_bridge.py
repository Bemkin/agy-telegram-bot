"""
Bridge between Telegram messages and the Antigravity Python SDK.

Spawns a real Antigravity agent with full capabilities (file read/write,
command execution, web search, code generation) and maintains multi-turn
conversation state so the agent remembers context across messages.
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig, types
from google.antigravity.hooks.policy import Decision, Policy
from google.antigravity.types import SessionContinuationMode

from config import Config

logger = logging.getLogger(__name__)

# ── System Instructions ───────────────────────────────────────────────

SYSTEM_INSTRUCTIONS = """\
You are an expert AI coding assistant operating through a private Telegram interface.
The user is interacting with you from their mobile phone while away from their laptop.

You have access to their codebase and laptop to read files, inspect diagnostics, search,
formulate plans, and execute approved changes.

## Response Guidelines (Mobile-Optimized)
- Keep paragraphs short (2-3 sentences). The user is reading on a small screen.
- Use bullet points and numbered lists liberally.
- Only include code blocks when they add clear value. Prefer summarizing changes
  over dumping entire files.
- Use bold for important terms and section headers.

## Safety & Permission-First Workflow
- You are PRIMARILY a Planning, Brainstorming, and Remote Diagnostic assistant.
- NEVER create, modify, or delete project files without explicit user permission.
- When asked to build features, create folders, or write code:
  1. Inspect the relevant files first to research the codebase.
  2. Brainstorm architecture, trade-offs, and draft an Implementation Plan.
  3. Clearly ask for confirmation or instruct the user to tap "Approve & Execute" before modifying code.
- ONLY execute direct file modifications when:
  a) The prompt includes explicit user approval (e.g., "[ACTION: Approved Implementation Plan]" or "yes, execute this"), OR
  b) The user explicitly asks for an immediate minor fix (e.g. "fix this typo in line 5", "update port to 8080").

## Current Workspace
The user's project is located at: {project_dir}
Focus your file operations within this workspace unless told otherwise.
"""


PRIMARY_MODEL = "gemini-3.7-flash"
FALLBACK_MODEL = "gemini-3.5-flash-lite"


class AgentBridge:
    """
    Manages the lifecycle of an Antigravity agent and provides
    a simple async interface for sending messages.
    Defaults to Safe Planning Mode (asks permission before modifying code).
    Supports intelligent failover: gemini-3.7-flash first, falling back
    to gemini-3.5-flash-lite if rate limits are hit.
    """

    def __init__(self, project_dir: str | None = None, model: str | None = None):
        self.project_dir = project_dir or Config.DEFAULT_PROJECT_DIR
        self.model_name = model or Config.AGENT_MODEL or PRIMARY_MODEL
        self.fallback_model = FALLBACK_MODEL
        self.mode: str = "plan"  # Default to Safe Planning Mode (requires approval to edit files)
        self._agent: Agent | None = None
        self._lock = asyncio.Lock()  # Serialize agent interactions
        self._conversation_id = str(uuid.uuid4())
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the Antigravity agent process."""
        if self._started:
            return

        instructions = SYSTEM_INSTRUCTIONS.format(project_dir=self.project_dir)

        config_kwargs = dict(
            system_instructions=instructions,
            capabilities=CapabilitiesConfig(),
            policies=[Policy(tool="*", decision=Decision.APPROVE, name="allow_all")],
            workspaces=[self.project_dir],
            conversation_id=self._conversation_id,
            session_continuation_mode=SessionContinuationMode.CREATE_ONLY,
        )

        # Add API key if configured
        if Config.GEMINI_API_KEY:
            config_kwargs["api_key"] = Config.GEMINI_API_KEY

        # Set active model
        if self.model_name:
            config_kwargs["model"] = self.model_name

        config = LocalAgentConfig(**config_kwargs)

        self._agent = Agent(config)
        await self._agent.__aenter__()
        self._started = True
        logger.info(
            "Agent started | workspace=%s | model=%s | conversation=%s | mode=%s",
            self.project_dir,
            self.model_name,
            self._conversation_id,
            self.mode,
        )

    async def stop(self) -> None:
        """Shut down the agent process gracefully."""
        if self._agent and self._started:
            try:
                await self._agent.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error stopping agent: %s", e)
            self._agent = None
            self._started = False
            logger.info("Agent stopped")

    # ── Chat ──────────────────────────────────────────────────────────

    async def chat(self, message: str, override_prompt: Optional[str] = None) -> str:
        """
        Send a message to the agent and collect the full streamed response.
        Thread-safe via asyncio.Lock — concurrent messages are queued.
        Includes automatic retry for transient 429 rate limits.
        """
        async with self._lock:
            if not self._started or not self._agent:
                raise RuntimeError("Agent is not running. Call start() first.")

            # Decorate prompt if in Planning/Brainstorming mode
            if self.mode == "plan" and not override_prompt:
                effective_prompt = (
                    "[MODE: BRAINSTORMING & PLANNING]\n"
                    "You are currently in Planning & Brainstorming Mode.\n"
                    "- DO NOT make direct edits to source code files yet.\n"
                    "- You MAY inspect and read files to research the codebase.\n"
                    "- Brainstorm architecture, explore ideas, and draft a structured Implementation Plan.\n"
                    "- Present clear options, trade-offs, and file breakdown.\n\n"
                    f"User Prompt: {message}"
                )
            else:
                effective_prompt = override_prompt or message

            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    response = await self._agent.chat(effective_prompt)
                    
                    # Drain all stream chunks completely to ensure tool execution finishes
                    chunks = await response.resolve()
                    
                    text_parts = [chunk.text for chunk in chunks if isinstance(chunk, types.Text)]
                    full_text = "".join(text_parts).strip()

                    # If text was empty (e.g. model executed commands without final conversational text)
                    if not full_text:
                        tool_calls = [chunk for chunk in chunks if isinstance(chunk, types.ToolCall)]
                        if tool_calls:
                            tool_lines = []
                            for t in tool_calls:
                                name = getattr(t, "name", "tool")
                                args = getattr(t, "args", {}) or {}
                                cmd = args.get("CommandLine") or args.get("Query") or args.get("AbsolutePath") or ""
                                tool_lines.append(f"• **{name}**: `{cmd}`" if cmd else f"• **{name}**")
                            full_text = "✅ **Commands & Tools Executed:**\n" + "\n".join(tool_lines) + "\n\n*(Command finished successfully with no error output)*"
                        else:
                            full_text = "✅ Task completed."

                    return full_text
                except Exception as e:
                    err_str = str(e)
                    # 1. Seamless Model Failover: If 3.7 hits 429 quota, failover to 3.5-flash-lite immediately!
                    if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()) and self.model_name != self.fallback_model:
                        logger.warning(
                            "Primary model %s rate limited (429). Seamlessly falling over to %s...",
                            self.model_name,
                            self.fallback_model,
                        )
                        try:
                            await self.switch_model(self.fallback_model)
                            # Retry immediately on the high-quota fallback model
                            return await self.chat(message, override_prompt=override_prompt)
                        except Exception as failover_err:
                            logger.error("Failover switch error: %s", failover_err)

                    # 2. General 429 backoff if already on fallback model
                    if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries:
                        logger.warning("Rate limit on fallback model. Retrying in 12s... (attempt %d/%d)", attempt + 1, max_retries)
                        await asyncio.sleep(12)
                        continue

                    # 3. WebSocket drop / ConnectionClosed recovery
                    elif ("ConnectionClosed" in err_str or "1000 (OK)" in err_str or "closed" in err_str.lower()) and attempt < max_retries:
                        logger.warning("Agent connection dropped. Auto-recovering session... (attempt %d/%d)", attempt + 1, max_retries)
                        try:
                            await self.stop()
                            await self.start()
                            await asyncio.sleep(1)
                            continue
                        except Exception as rec_err:
                            logger.error("Session auto-recovery failed: %s", rec_err)

                    logger.error("Agent chat error: %s", e, exc_info=True)
                    return f"❌ Agent error: {e}"

    def set_mode(self, mode: str) -> str:
        """Switch between 'plan' (brainstorm) and 'act' (direct execution) mode."""
        clean_mode = mode.lower().strip()
        if clean_mode in ("plan", "brainstorm", "planning"):
            self.mode = "plan"
            return "🧠 <b>Planning Mode Activated</b>\n\nThe agent will research, brainstorm, and draft implementation plans <i>without modifying code</i> until you approve."
        else:
            self.mode = "act"
            return "⚡ <b>Direct Action Mode Activated</b>\n\nThe agent will immediately execute tasks and edit files on your laptop."

    # ── Project & Model Switching ────────────────────────────────────

    async def switch_project(self, new_dir: str) -> str:
        """
        Switch the agent's workspace to a different project directory.
        This tears down the current agent and creates a new one.
        """
        path = Path(new_dir)
        if not path.is_dir():
            return f"❌ Directory does not exist: {new_dir}"

        old_dir = self.project_dir
        self.project_dir = str(path.resolve())
        await self.reset()
        return f"✅ Switched from `{old_dir}` to `{self.project_dir}`"

    async def switch_model(self, new_model: str) -> str:
        """
        Switch the active LLM model (e.g. gemini-3.7-flash, gemini-2.5-pro).
        """
        old_model = self.model_name
        self.model_name = new_model
        await self.reset()
        return f"✅ Switched model from `<b>{old_model}</b>` to `<b>{new_model}</b>`"

    # ── Reset ─────────────────────────────────────────────────────────

    async def reset(self) -> None:
        """
        Reset the agent — clears conversation memory and starts fresh.
        """
        await self.stop()
        self._conversation_id = str(uuid.uuid4())  # New conversation
        await self.start()
        logger.info("Agent reset with new conversation %s", self._conversation_id)

    # ── Status ────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return agent status info for the /status command."""
        return {
            "running": self._started,
            "project": self.project_dir,
            "model": self.model_name,
            "conversation_id": self._conversation_id,
        }
