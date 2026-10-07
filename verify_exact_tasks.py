"""
Verification script for the 6 exact requested tasks:
1. GENERAL: "What is polymorphism in Java? Explain with a simple example."
2. CONCEPTUAL: "What is the difference between TCP and UDP?"
3. PROGRAMMING: "Write a C++ program to reverse a singly linked list and explain it."
4. CALCULATION: "Calculate 125 multiplied by 36 and explain the result."
5. CURRENT: "What are the latest developments in AI agents?"
6. MULTI-STEP: "Calculate the compound interest on ₹10000 at 8% annually for 5 years and explain the steps."
"""

import asyncio
import json
import sys
import uuid

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from backend.agent.graph import create_agent_graph
from backend.agent.runtime import AgentRuntime, set_current_runtime
from backend.agent.state import create_initial_state


async def run_task(name: str, goal: str, expected_tool: str | None = None):
    print(f"\n========================================================")
    print(f"RUNNING TEST [{name}]")
    print(f"Goal: {goal}")
    print(f"Expected tool: {expected_tool or 'NONE (direct LLM reasoning)'}")
    print(f"========================================================")

    runtime = AgentRuntime(session_factory=None)
    set_current_runtime(runtime)

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    state = create_initial_state(task_id, run_id, user_id, goal)
    app = create_agent_graph()

    final_state = await app.ainvoke(state)

    status = final_state.get("status")
    iter_count = final_state.get("iteration_count")
    tool_calls = final_state.get("tool_calls", [])
    used_tools = [tc.get("tool") for tc in tool_calls]
    final_response = final_state.get("final_response", "")

    print(f"Status: {status}")
    print(f"Iterations: {iter_count}")
    print(f"Tools Used: {used_tools}")
    print(f"Plan: {final_state.get('plan')}")
    print(f"Observations: {final_state.get('observations')}")
    print(f"Evaluation: {final_state.get('evaluation')}")
    print(f"\nResponse Excerpt (first 300 chars):\n{final_response[:300]}...")

    # Assertions
    assert status == "succeeded", f"Task {name} did not succeed: {status}"
    assert iter_count <= 3, f"Task {name} looped too many times: {iter_count}"

    if expected_tool is None:
        assert len(used_tools) == 0, f"Task {name} should NOT use tools, but used {used_tools}"
    else:
        assert expected_tool in used_tools, f"Task {name} should use {expected_tool}, but got {used_tools}"

    print(f"\n>>> TEST [{name}] PASSED VERIFICATION!")
    return {
        "name": name,
        "goal": goal,
        "status": status,
        "iterations": iter_count,
        "tools_used": used_tools,
        "response_excerpt": final_response[:200] + "...",
    }


async def main():
    results = []

    # 1. GENERAL
    r1 = await run_task(
        "GENERAL",
        "What is polymorphism in Java? Explain with a simple example.",
        expected_tool=None,
    )
    results.append(r1)

    # 2. CONCEPTUAL
    r2 = await run_task(
        "CONCEPTUAL",
        "What is the difference between TCP and UDP?",
        expected_tool=None,
    )
    results.append(r2)

    # 3. PROGRAMMING
    r3 = await run_task(
        "PROGRAMMING",
        "Write a C++ program to reverse a singly linked list and explain it.",
        expected_tool=None,
    )
    results.append(r3)

    # 4. CALCULATION
    r4 = await run_task(
        "CALCULATION",
        "Calculate 125 multiplied by 36 and explain the result.",
        expected_tool="calculator",
    )
    results.append(r4)

    # 5. CURRENT
    r5 = await run_task(
        "CURRENT",
        "What are the latest developments in AI agents?",
        expected_tool="web_search",
    )
    results.append(r5)

    # 6. MULTI-STEP
    r6 = await run_task(
        "MULTI-STEP",
        "Calculate the compound interest on ₹10000 at 8% annually for 5 years and explain the steps.",
        expected_tool="calculator",
    )
    results.append(r6)

    # 7. ARBITRARY QUESTION (Dynamic physics reasoning)
    r7 = await run_task(
        "ARBITRARY",
        "Why does increasing temperature usually increase the resistance of a metal?",
        expected_tool=None,
    )
    results.append(r7)

    print("\n\n" + "=" * 60)
    print("ALL 7 TASKS VERIFIED SUCCESSFULLY!")
    print("=" * 60)
    for r in results:
        print(f"[{r['name']}] Tools: {r['tools_used']} | Iterations: {r['iterations']} | Status: {r['status']}")


if __name__ == "__main__":
    asyncio.run(main())
