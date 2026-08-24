---
name: independent-review
description: "Run one or more supervised, read-only requirements and code reviews with fresh reviewer subagents against staged changes, a commit or range, one task or epic, or a roadmap-independent investigation. Use when the user explicitly invokes /skill:independent-review and asks for an independent verdict without remediation."
disable-model-invocation: true
---

# Independent Review

Coordinate one or more fresh read-only reviewer subagents in the current worktree, preserve the current checkout, and independently verify the returned findings before recommending any response. The current execution backend is Kimi Code's native `Agent` mechanism; target selection and review semantics are backend-independent. This is a standalone review workflow, not the Mulgae phase owned by `/skill:task-review`.

## Load the Contract

1. Read [review-contract.md](../../references/review-contract.md) completely. It owns target selection, dirty-state handling, consent, static-review limits, and the result envelope.
2. Resolve this skill directory. The upstream `scripts/inspect_review_target.py` has no Kimi Code counterpart, so classify the target manually from repository evidence rather than invoking it.

## Establish the Request

1. Resolve one current Git root and classify the request as `staged`, `commit`, `range`, `task`, `epic`, or `special request`.
2. For a task or epic, inspect its roadmap and linked authority first. Select a Git target automatically only when the authority identifies one unambiguous staged candidate, commit, or range; otherwise ask the user to choose among the concrete candidates.
3. For a special request, establish the exact question, then always ask the user to confirm staged, `HEAD`, one commit, or one explicit two-dot or three-dot range.
4. Inspect HEAD, branch, upstream, staged, unstaged, untracked, ignored, and conflicted state. Resolve any staged-target dirty decision exactly as the shared contract requires. Never review dirty working-tree content as a target.
5. Bind the resolved target, authority paths, and exact included and excluded state to each reviewer specification.

Explicit invocation with an exact target and reviewer subagent authorizes the source transmission needed for this review. Do not ask for duplicate approval unless the target, included paths, reviewer model, or execution scope changes. The workflow authorizes no source edits, tests, builds, generators, formatters, linters, provider reviews, commits, pushes, publication, or remediation. The only permitted mutation is exact-path staging that the user separately approved under the dirty decision.

## Dispatch Fresh Reviewers

Dispatch at least one reviewer subagent through the host's `Agent` tool, and dispatch several when the target spans distinct review dimensions. Use the read-only `explore` subagent type for every reviewer. Give each reviewer a distinct lens — requirements conformance, implementation correctness, test and coverage adequacy — so that additional reviewers buy coverage rather than repetition. Launch them in a single message with `run_in_background` so they run concurrently, and record which lens each one received. Honor an explicitly requested reviewer model or effort only when the subagent mechanism exposes that selection; when it does not, record the unhonored request and report it with the result.

Do not reuse an existing terminal and do not create another Git worktree.

Build each specification from source evidence, including the absolute repository, target identifier, authority paths, exact review snapshot or range, relevant staged and unstaged state, and the fact that tests already passed. Include the same-user visibility disclosure when dirty content is excluded. Include instructions to use index blobs for staged targets and resolved commit blobs for commit, range, or `HEAD` targets rather than later working-tree copies. Include the static-only restrictions and `runtime unverified` requirement from the shared contract, plus the required finding fields and exact `APPROVE` condition. Do not include the coordinator's suspected findings or intended fixes.

Require each reviewer to:

- read applicable instructions, requirements, contracts, code, and relevant existing tests;
- remain strictly read-only and run no tests, generators, formatters, linters, or provider reviews;
- report only verified, actionable findings and omit style preferences, speculation, and praise;
- separate production defects from required test, specification, or current-documentation gaps;
- give each finding a severity, exact `path:line`, triggering scenario, violated requirement, impact, and smallest remediation;
- return exactly `APPROVE` when no actionable finding remains;
- leave the detailed review in its final response and report no modified files.

A reviewer subagent shares the coordinator's model, so what this buys is a fresh context that has not seen the coordinator's reasoning, not an independent model. Claim that guarantee and no more. Distinct lenses across several reviewers are what widen coverage.

## Fail Closed on Dispatch

1. Stop with the exact gap when the subagent mechanism is unavailable, when a dispatch fails, or when a reviewer returns no usable output.
2. Never substitute the coordinator's own review, a chat delegation, an ad hoc terminal, or a raw agent CLI for a dispatched reviewer. The coordinator has already reasoned about this target and cannot review it independently.
3. An operational failure is not an `APPROVE` result.

## Supervise and Settle

Before dispatch, disclose and record one cumulative liveness budget, using 30 minutes unless the user explicitly selected another duration. Wait on the background reviewers with `WaitFor` in rolling intervals, keeping each wait short enough to provide a user update at least once per minute and charging every wait against the same remaining budget.

Treat a wait timeout inside that budget as a liveness checkpoint, not a failure. Answer reviewer questions only from established repository facts; ask the user when an answer requires product intent or wider authority.

When the cumulative budget expires before every reviewer has reported, inspect each outstanding task's state once through `TaskList` and `TaskOutput`, stop waiting, leave any running reviewer intact, and report the review as operationally incomplete with the exact task IDs and their statuses. Further waiting or cancellation requires an explicit user request; never stop, retry, or replace a running reviewer automatically.

Process every returned review in full. The host delivers a finished task's result exactly once, so settlement is processing that result once and recording the verdict; there is no acknowledgement protocol to drain and no settled worker to release. Never stop a running reviewer after a wait timeout, and never dispatch a duplicate reviewer for the same lens while its first dispatch is still running. Keep technical review evidence and dispatch status as separate statuses, so a reviewer that never reported is never read as a clean verdict.

## Adjudicate the Result

Verify every reviewer finding against the current authority, code, callers, persistence boundaries, and existing tests without changing files or running checks. Classify each item as:

- **Valid**: confirmed and actionable; propose the smallest implementation and regression-coverage response.
- **Invalid**: contradicted by exact evidence; explain the contradiction briefly.
- **Needs confirmation**: plausible but dependent on missing authority or runtime evidence; state the precise evidence needed.

When several reviewers ran, merge overlapping findings once and keep disagreements visible. A finding one reviewer raised and another contradicted is a needs-confirmation item with both positions stated, never an averaged verdict.

Do not implement a proposed response. If every reviewer returned `APPROVE`, first confirm that each examined the intended snapshot and authority, then report that no actionable feedback was found. If output is missing, scope is wrong, or dispatch failed, report the operational gap without a clean verdict.

Return the complete shared result envelope, the target and snapshot, how many reviewers ran and with which lens, each reviewer's verdict, adjudicated findings, recommended responses, and a separate dispatch status for every reviewer.
