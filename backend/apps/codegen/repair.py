"""Reusable generate → verify → repair loop for code-generating agents.

Any agent that emits source files can route them through `verify_and_repair`
instead of a one-shot write: it compiles the code, and (optionally) runs the
project's real test suite, feeding each genuine failure back to the model and
regenerating — up to a shared repair budget — before anything is declared done.
Only code that actually compiles (and passes tests, when run) is reported clean;
exhausted repairs are reported honestly, never hidden.

The loop is agent-agnostic: the caller supplies how to turn a model response into
files (`build_files`) and how to ask for another completion (`complete`); the
JSON *shape* is the caller's own, so the default repair prompts just ask for "the
same shape you were asked for" (the model still has its system prompt in context).
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.ai_providers.base import Message
from apps.codegen.service import materialize, run_repo_tests, verify_python


@dataclass
class RepairOutcome:
    files: list[dict]
    final_text: str
    model: str
    total_tokens: int
    repair_rounds: int
    compiled: bool | None      # None = no code to compile
    compile_log: str
    tests_passed: bool | None  # None = no tests run / nothing runnable
    tests_ran: int
    test_log: str
    commit_sha: str | None


def default_compile_prompt(log: str) -> str:
    return (
        "The code you just returned does NOT compile/parse. Fix it.\n\n"
        f"Verifier output:\n{(log or '').strip()[-1500:] or '(no detail)'}\n\n"
        "Return the COMPLETE corrected JSON in the SAME shape you were asked for "
        "— every file needed to run, not a diff. No prose outside the JSON."
    )


def default_test_prompt(output: str) -> str:
    return (
        "The code compiles but its TESTS FAIL. Fix the implementation so the "
        f"tests pass.\n\nTest output:\n{(output or '').strip()[-1500:] or '(no detail)'}\n\n"
        "Fix the real defect (do not weaken or delete a test unless it is clearly "
        "wrong). Return the COMPLETE corrected JSON in the SAME shape you were "
        "asked for — every file needed to run, not a diff. No prose outside the JSON."
    )


def verify_and_repair(
    *,
    complete,               # callable(list[Message]) -> CompletionResponse
    project,
    initial_response,       # the first CompletionResponse (caller already made it)
    user_prompt: str,       # the original user turn, replayed into repair context
    build_files,            # callable(text: str) -> list[dict]
    materialize_message: str,
    compile_prompt=default_compile_prompt,
    test_prompt=default_test_prompt,
    max_repairs: int = 2,
    run_tests: bool = True,
) -> RepairOutcome:
    files = build_files(initial_response.text)
    final = initial_response
    total_tokens = initial_response.usage.total_tokens
    rounds = 0

    def _repair(instruction: str):
        return complete([
            Message("user", user_prompt),
            Message("assistant", final.text),
            Message("user", instruction),
        ])

    # Phase 1: compile (in-memory — cheap, before we materialize anything).
    compiled, compile_log = (verify_python(files) if files else (None, ""))
    while files and compiled is False and rounds < max_repairs:
        rounds += 1
        fix = _repair(compile_prompt(compile_log))
        total_tokens += fix.usage.total_tokens
        repaired = build_files(fix.text)
        if not repaired:
            break  # nothing usable came back; keep the prior attempt
        files, final = repaired, fix
        compiled, compile_log = verify_python(files)

    commit_sha = None
    if files:
        _, commit_sha = materialize(project, files, message=materialize_message)

    # Phase 2: real tests (only if it compiles and the caller wants them).
    tests_passed, test_log, tests_ran = None, "", 0
    if files and compiled and run_tests:
        result = run_repo_tests(project)
        tests_passed = result.get("passed")
        tests_ran = result.get("ran", 0)
        test_log = (result.get("output") or result.get("note") or "").strip()
        while tests_passed is False and rounds < max_repairs:
            rounds += 1
            fix = _repair(test_prompt(test_log))
            total_tokens += fix.usage.total_tokens
            repaired = build_files(fix.text)
            if not repaired:
                break
            files, final = repaired, fix
            compiled, compile_log = verify_python(files)
            _, commit_sha = materialize(project, files, message=materialize_message)
            if not compiled:
                break  # the fix broke compilation; reported honestly by the caller
            result = run_repo_tests(project)
            tests_passed = result.get("passed")
            tests_ran = result.get("ran", 0)
            test_log = (result.get("output") or result.get("note") or "").strip()

    return RepairOutcome(
        files=files,
        final_text=final.text,
        model=final.model,
        total_tokens=total_tokens,
        repair_rounds=rounds,
        compiled=compiled,
        compile_log=compile_log,
        tests_passed=tests_passed,
        tests_ran=tests_ran,
        test_log=test_log,
        commit_sha=commit_sha,
    )
