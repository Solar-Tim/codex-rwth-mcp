from __future__ import annotations


SYSTEM_PROMPT = """You are a preprocessing assistant for GPT-5 Codex.
Compress high-volume evidence into concise, actionable engineering context.
Do not suggest code edits unless directly supported by the evidence.
Prefer short bullets, concrete file names, exact error messages, and confidence levels.
Do not include hidden chain-of-thought; return only the useful handoff summary."""


def logs_prompt(*, logs: str, context: str = "") -> str:
    return f"""Analyze these logs for Codex.

Context:
{context or "No extra context provided."}

Return:
- Top error clusters with representative messages
- Likely root causes and confidence
- Timeline or frequency signals if visible
- Suggested next files, commands, or checks
- Noise to ignore

Logs:
{logs}"""


def repo_prompt(*, files: str, question: str = "") -> str:
    return f"""Analyze this repository excerpt for Codex.

Question:
{question or "Explain the architecture, code flow, and most relevant components."}

Return:
- Architecture summary
- Main execution/data flow
- Relevant files/components and why
- Coupling, risk, or missing-context notes
- Compact handoff summary

Repository excerpt:
{files}"""


def screenshot_prompt(*, question: str = "") -> str:
    return f"""Analyze this screenshot for Codex.

Question:
{question or "Identify actionable debugging insights from the UI, error, terminal, or dashboard."}

Return:
- What is visible
- Error states, suspicious UI details, or diagnostic signals
- Likely causes and confidence
- Concrete next checks"""


def diff_prompt(*, diff: str, context: str = "") -> str:
    return f"""Analyze this git diff or pull request for Codex.

Context:
{context or "No extra context provided."}

Return:
- Change summary
- Affected areas and behavioral impact
- Risk assessment
- Missing tests or review focus
- Compact handoff summary

Diff:
{diff}"""
