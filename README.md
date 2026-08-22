# Aquarium for Kimi

Aquarium development skills packaged as a Kimi Code plugin. This repository is a **generated artifact**: the source of truth is the Codex plugin at [irootkernel/aquarium](https://github.com/irootkernel/aquarium), pinned here as a submodule and transformed by `scripts/sync.py`.

By [Root Kernel](https://home.rootkernel.xyz) · Support: [cs@rootkernel.xyz](mailto:cs@rootkernel.xyz)

## Install

```
/plugins install https://github.com/irootkernel/aquarium-for-kimi
```

Inside a session, run `/plugins install https://github.com/irootkernel/aquarium-for-kimi`, then `/reload` or start a new session so the skill snapshot reloads. For a local checkout, `/plugins install /path/to/aquarium-for-kimi` works the same way.

The generated plugin is committed, so installation never depends on the submodule being fetched.

## Skills

| Skill | Purpose | Invocation |
|---|---|---|
| `new-project` | Shape a greenfield project into an approved PRD and initial roadmap with Ouroboros, without implementing it. | `/skill:new-project` |
| `new-feature` | Shape one feature epic and its Design Gate impact for an existing project. | `/skill:new-feature` |
| `refactor` | Shape one refactor epic with compatibility, migration, rollback, and gate impact. | `/skill:refactor` |
| `war-room` | Diagnose one difficult bug and propose a task, epic, or incomplete investigation without a fix. | `/skill:war-room` |
| `design-qa` | Create, change, reactivate, or retire durable local Design Gates behind an approved exact diff. | `/skill:design-qa` |
| `epic-handler` | Orchestrate an epic through sequential task goals and a convergent epic-wide audit. | `/skill:epic-handler` with a roadmap path and one epic ID |
| `epic-validator` | Cold-validate a completed epic and converge confirmed gaps through remediation goals. | `/skill:epic-validator` with a roadmap path and one epic ID |
| `task-handler` | Strengthen the procedure around one task goal through focused phase skills and verified transitions. | `/skill:task-handler` with a roadmap path and one task ID |
| `task-commit` | Reconcile roadmap task lifecycle state and create one authorized commit that preserves unrelated work. | Automatic for commit requests, or `/skill:task-commit` |
| `release-qa` | Exercise the current release candidate through read-only user scenarios covering every change since the previous stable release. | `/skill:release-qa` with an intended or confirmed version |
| `dev-setup` | Diagnose and configure selected development tools, and propose reference-based instruction-file guidance behind separate approvals. | `/skill:dev-setup` |
| `dev-setup-bundle` | Apply development-tool setup to explicit Git repositories from one external YAML manifest. | `/skill:dev-setup-bundle` with a manifest path |
| `independent-review` | Run a supervised read-only requirements and code review with fresh reviewer subagents, then adjudicate their findings. | `/skill:independent-review` with one epic or task |

The five design skills drive Ouroboros as a bounded leaf capability and need it installed and pinned to `>=0.51.1,<0.52.0`; `/skill:dev-setup` diagnoses and configures it behind separate approvals. They shape documents only and never implement.

`task-handler` loads seven phase skills in order — `task-plan`, `task-implement`, `task-verify`, `task-refine`, `task-document`, `task-review`, `task-close`. Invoke one directly only to resume that exact phase with its required task context.

### Roadmap commit guard

The plugin manifest declares a `PreToolUse` hook that inspects `Bash` commands and denies a direct `git commit` in a repository whose tracked roadmap carries task lifecycle state, routing it through `task-commit` instead. The hook is local, reads only the proposed command and the working directory, and fails open when it cannot parse its input. Kimi Code merges an enabled plugin's hooks with your own while the plugin is enabled; review the declaration under `.kimi-plugin/plugin.json` after installing.

### Invocation gating

Every skill except `task-commit` carries `disable-model-invocation: true`, so the model cannot start it on its own; you invoke it with `/skill:<name>`. Several of these skills stage, commit, or mutate roadmap state, and the upstream workflow requires explicit invocation. The flag is derived from each upstream skill's `agents/openai.yaml` at sync time, so it can never disagree with the Codex policy. Kimi Code accepts the kebab-case key as an alias of `disableModelInvocation`.

This is also why the plugin is a separate artifact rather than a second manifest in the upstream repository: Codex's plugin validator rejects `disable-model-invocation` outright, while Kimi Code needs it for the same guarantee.

## How generation works

```
upstream/                        git submodule, pinned to one upstream commit
  plugins/aquarium/              the Codex plugin — never edited here
overrides/
  manifest.json                  path → SHA-256 of the upstream file each override was derived from
  codex-exemptions.json          path → SHA-256 of an upstream file whose remaining "Codex" mentions were reviewed
  skills/...                     full-file replacements for host-specific divergence
scripts/sync.py                  the transformation
plugins/aquarium/                generated output, committed
  hooks/                         the roadmap commit guard script
  sync-manifest.json             upstream commit and per-file hashes
.kimi-plugin/
  plugin.json                    generated root manifest — skills pointer and the converted hook declaration
```

`sync.py` copies the upstream plugin, applies literal substitutions, applies overrides, then derives invocation gating from the upstream sidecars and drops them. It refuses to run against an empty submodule, refuses to run when upstream grows a directory the transformation does not handle, and fails if host-specific text survives.

Four files diverge semantically and are kept as overrides rather than substitutions:

| Override | Why |
|---|---|
| `skills/independent-review/SKILL.md` | Replaces Orca orchestration with fresh read-only review subagents dispatched through the host's own subagent mechanism. Because a subagent shares the coordinator's model, the skill claims a fresh context rather than an independent model, and buys coverage by giving several reviewers distinct lenses. |
| `skills/dev-setup/SKILL.md` | Resolves the instruction-file target to `AGENTS.md`, which Kimi Code reads natively. The two-stage approval gate is unchanged. |
| `skills/dev-setup/references/agents-guidance.md` | The whole file is instruction-file editing guidance, which is exactly what differs per host. |
| `skills/dev-setup/references/tool-catalog.md` | Registers Mulgae, Gaori, and Ouroboros MCP servers in the user-level `mcp.json` (`$KIMI_CODE_HOME/mcp.json`, shared across projects) with millisecond `startupTimeoutMs`/`toolTimeoutMs` fields, and verifies them by reading the effective configuration plus `kimi doctor`, because Kimi Code has no `mcp get` CLI probe. |

Everything else is a literal substitution: the `$aquarium:` sigil becomes `/skill:`, the `$use-*` skill sigils become `/skill:use-*`, the Ouroboros sigils `$interview`, `$pm`, `$seed`, and `$qa` become `/skill:*` because Ouroboros installs user-scoped skills that Kimi Code reads natively from `~/.agents/skills`, the separately installed `$deslop` becomes `/skill:deslop`, `request_user_input` becomes `AskUserQuestion`, `Codex goal` becomes `Kimi Code goal`, and the inspection script resolves skills from the Kimi Code roots — `KIMI_CODE_HOME`, `~/.kimi-code/skills`, and the shared `~/.agents/skills` — and diagnoses Ouroboros against this host instead of Codex.

The hook declaration moves from the Codex/Claude `hooks/hooks.json` shape into the manifest's flat `hooks` array, because Kimi Code does not auto-load a hooks file. Its command resolves `${KIMI_PLUGIN_ROOT}` instead of Codex's `${PLUGIN_ROOT}` and gains a `plugins/aquarium` prefix, because the installed plugin root is this repository while the script lives in the generated tree. That substitution is load-bearing: `PLUGIN_ROOT` is unset under Kimi Code, so the unsubstituted command expands to `/hooks/task_commit_gate.py`, `python3` exits 2, and `PreToolUse` reads exit 2 as a denial — blocking every `Bash` call. A forbidden needle and a required-text assertion both guard it.

Upstream diagnoses Ouroboros by asking Codex — `ooo codex doctor` for its integration artifacts and `codex mcp get ouroboros --json` for its registration. Kimi Code has neither command. The generated inspector instead reads the registration from the host's `mcp.json` files — `$KIMI_CODE_HOME/mcp.json` user-level, then the project-level `.kimi-code/mcp.json` override — and takes that entry as the host-integration signal, because on this host the integration is exactly that entry plus the user-scoped Ouroboros skills. Runtime health comes from `ooo mcp doctor --json` with the `mcp_import` check exempted: the MCP 2 server registered in `mcp.json` launches as a separate process while the CLI environment keeps MCP 1.x, so that check fails on a correctly configured machine. The Mulgae and Gaori MCP probes move to the same mcp.json reading. All three register one user-level entry shared across projects — flag-less `mcp` arguments and no pinned `cwd`, so the launched server resolves each session's own repository — and the generated inspector verifies the merged user entry directly: enabled, stdio transport, the selected binary, the millisecond timeout floors, and no shadowing project-level entry. A legacy project-scoped registration reports as missing with a reason naming that state.

Skill discovery narrows for the same reason. Upstream resolves user-scoped skills from the Codex and shared cross-agent roots; the generated inspector resolves the Kimi Code roots alone, because one host's artifact should diagnose one host. The shared `~/.agents/skills` root needs no substitution: Kimi Code reads it natively, so Ouroboros, Deslop, and Lora skills installed there are genuinely reachable.

An unmapped sigil is the quiet failure: it is valid Markdown naming a command the reader's host does not have, so neither a forbidden needle nor a required-text assertion notices it, and one needle per known sigil only ever catches the sigils that already exist. Generation therefore rejects any remaining lowercase `$name` in generated Markdown, which is what caught the five Ouroboros and Deslop sigils upstream introduced in v0.1.9. Uppercase spellings are environment variables the generated tree still needs and do not match.

The `Codex` name is otherwise forbidden in generated text. `tool-catalog.md` is exempt because it names the Codex CLI as a Mulgae provider and a required CLI version, which stays true here. The exemption records the upstream digest it was judged against, so the sync stops when that file changes.

## Upgrade

```bash
git -C upstream fetch --tags origin
git -C upstream checkout <new-tag>
python3 scripts/sync.py
ruby tests/validate.rb
git add -A && git commit
```

Each override records the SHA-256 of the upstream file it came from. When upstream changes one of those files the sync stops and names it, because merging a stale override would ship guidance that no longer matches its source. Re-derive the override against the new upstream content and update `overrides/manifest.json`.

## Validate

```bash
python3 scripts/sync.py --check
ruby tests/validate.rb
git diff --check
```

`--check` regenerates into a temporary directory and fails if the committed output drifted. The Ruby validation covers only what this repository is responsible for — invocation gating against the upstream sidecars, host-neutral generated text, the commit hook's Kimi Code contract, byte-identical Podway procedures, manifest agreement, and the generated tree's coverage of upstream. Upstream owns the prose contract and validates it in its own CI.

## Documentation style

Do not hard-wrap prose. Keep each prose paragraph on one source line; use line breaks only for structural Markdown, code, tables, lists, or other syntax where the break is meaningful.

## License

MIT, inherited from upstream. This repository vendors no third-party skill source: Deslop and Lora are installed from their own upstream repositories by `/skill:dev-setup`, each keeping its original licence.
