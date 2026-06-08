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


def deep_debug_map_prompt(*, logs: str, context: str, failing_command: str) -> str:
    return f"""Map this debugging evidence for Codex.

Context:
{context or "No extra context provided."}

Failing command:
{failing_command or "No failing command provided."}

Return concise bullets with:
- likely error clusters
- root-cause hypotheses with confidence
- missing evidence Codex should gather if needed
- files or commands that look relevant

Evidence:
{logs}"""


def deep_debug_final_prompt(
    *, summaries: str, context: str, safety_notes: list[str], mode: str
) -> str:
    return f"""Produce a {mode} debugging handoff for Codex.

Context:
{context or "No extra context provided."}

Safety notes:
{chr(10).join(safety_notes) if safety_notes else "None."}

Return machine-readable lines:
status: complete | needs_codex_input | blocked
summary: one concise diagnosis
finding: repeat for key findings
risk: repeat for risks or uncertainty
requested_evidence: repeat only if Codex must gather more input
next_codex_action: repeat for concrete next actions Codex should take

Summaries:
{summaries}"""


def deep_diff_map_prompt(*, diff: str, context: str) -> str:
    return f"""Review this diff chunk for Codex.

Context:
{context or "No extra context provided."}

Return concise bullets with:
- changed behavior
- risky areas
- missing tests
- questions or missing evidence

Diff chunk:
{diff}"""


def deep_diff_final_prompt(
    *, summaries: str, context: str, safety_notes: list[str], mode: str
) -> str:
    return f"""Produce a {mode} diff-review handoff for Codex.

Context:
{context or "No extra context provided."}

Safety notes:
{chr(10).join(safety_notes) if safety_notes else "None."}

Return machine-readable lines:
status: complete | needs_codex_input | blocked
summary: concise review summary
finding: repeat for important changes
risk: repeat for review risks
requested_evidence: repeat only if Codex must gather more input
next_codex_action: repeat for concrete next review actions

Chunk summaries:
{summaries}"""


def repo_map_prompt(*, question: str, file_tree: str, files: str, context: str) -> str:
    return f"""Map this repository evidence for Codex.

Question:
{question}

Context:
{context or "No extra context provided."}

File tree:
{file_tree or "No file tree provided."}

Return concise bullets with:
- ranked relevant files/components
- responsibilities
- missing files Codex should gather if needed

Files:
{files}"""


def repo_map_final_prompt(
    *, summaries: str, question: str, safety_notes: list[str]
) -> str:
    return f"""Produce a repository-map handoff for Codex.

Question:
{question}

Safety notes:
{chr(10).join(safety_notes) if safety_notes else "None."}

Return machine-readable lines:
status: complete | needs_codex_input | blocked
summary: concise architecture or file-map answer
finding: repeat for ranked relevant files/components
risk: repeat for missing context or uncertainty
requested_evidence: repeat only if Codex must gather more input
next_codex_action: repeat for concrete next Codex actions

Map summaries:
{summaries}"""
