# Orca Review Supervision

This reference describes the Orca execution backend used by the upstream Aquarium plugin. Kimi Code does not use Orca. On this host, `/skill:independent-review` dispatches one or more read-only `explore` subagents through the native `Agent` tool, waits on them with `WaitFor`, and settles their results through `TaskList` and `TaskOutput`.

For review semantics — target selection, dirty-state handling, consent, static-review limits, and the result envelope — see [review-contract.md](review-contract.md).
