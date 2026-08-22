#!/usr/bin/env python3
"""Generate the Kimi Code plugin from the pinned upstream Codex plugin.

The upstream repository at `upstream/` is the single source of truth. This
script performs a deterministic transformation into `plugins/aquarium/` plus
the root `.kimi-plugin/plugin.json`, both committed so the plugin installs
even when the submodule is absent.

Run `sync.py` to regenerate, or `sync.py --check` to fail on drift.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
UPSTREAM = REPOSITORY / "upstream"
UPSTREAM_PLUGIN = UPSTREAM / "plugins" / "aquarium"
OUTPUT = REPOSITORY / "plugins" / "aquarium"
ROOT_MANIFEST = REPOSITORY / ".kimi-plugin"
OVERRIDES = REPOSITORY / "overrides"
OVERRIDE_MANIFEST = OVERRIDES / "manifest.json"
CODEX_EXEMPTIONS = OVERRIDES / "codex-exemptions.json"
SYNC_MANIFEST = "sync-manifest.json"

COPIED_DIRECTORIES = ("skills", "references", "assets", "hooks")
TEXT_SUFFIXES = (".md",)
SCRIPT_SUFFIXES = (".py",)
DATA_SUFFIXES = (".json",)
# Everything copied that host-specific text could hide in. `.yaml` is scanned but
# never rewritten: the Podway procedure IDs are load-bearing identifiers, and the
# integration contract requires the installed copies to match these bytes.
SCANNED_SUFFIXES = TEXT_SUFFIXES + SCRIPT_SUFFIXES + DATA_SUFFIXES + (".yaml",)

# Ordered literal substitutions applied to copied Markdown. Order matters: a
# later rule must never rewrite text that an earlier rule already produced.
#
# Kimi Code invokes skills as `/skill:<name>` with bare names — plugin skills
# carry no namespace — so every Codex sigil maps onto that form. Ouroboros and
# Deslop install user-scoped under the Kimi Code skill roots, where
# `~/.agents/skills` is read natively, so their invocations stay bare too.
#
# `AGENTS.md` is deliberately absent: it is Kimi Code's native instruction
# file, and upstream wording about it stays correct here. `~/.agents/skills`
# is absent for the same reason.
SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("$aquarium:", "/skill:"),
    # `$use-podway`, `$use-sanho`, `$use-mulgae`, `$use-gaori`. A prefix rule
    # covers the family and any later sibling; `/skill:use-` cannot re-match it.
    ("$use-", "/skill:use-"),
    ("$lore-commits", "/skill:lore-commits"),
    ("$lore-query", "/skill:lore-query"),
    ("$orca-cli", "/skill:orca-cli"),
    ("$interview", "/skill:interview"),
    ("$deslop", "/skill:deslop"),
    ("$seed", "/skill:seed"),
    ("$pm", "/skill:pm"),
    ("$qa", "/skill:qa"),
    ("`request_user_input`", "`AskUserQuestion`"),
    # Kimi Code has a goal mode, so the Codex goal translates directly.
    ("Codex goal", "Kimi Code goal"),
    ("a fresh Codex reviewer", "a fresh independent reviewer"),
    ("one fresh Codex reviewer", "one fresh independent reviewer"),
    ("supervised Codex reviewer", "supervised independent reviewer"),
    ("a fresh Codex in the current", "a fresh independent reviewer in the current"),
    ("fresh Codex audit", "fresh from-scratch audit"),
    ("direct Codex audit", "direct from-scratch audit"),
    (" for Codex.", " for Kimi Code."),
    # Ouroboros registers its skills with the host agent, so the component whose
    # health `dev-setup` establishes is the Kimi Code one here. The bundle
    # skill names the same component in a list of Ouroboros setup mutations.
    ("Codex skill health", "Kimi Code skill health"),
    (
        "Ouroboros package, Codex, and runtime components",
        "Ouroboros package, host integration, and runtime components",
    ),
    # Lora installs per host, so the catalog's scope wording moves. The
    # instruction-file text it could collide with is handled by overrides.
    ("Configure it for Codex user-global scope.", "Configure it for the Kimi Code user-global scope."),
    ("the Codex user-global skill directory", "the Kimi Code user-global skill directory"),
    # Singular form covers the plural; upstream has both "another Codex skill
    # root" and "Codex skill roots".
    ("Codex skill root", "Kimi Code skill root"),
    ("a new Codex user-scoped", "a new user-scoped"),
    (
        "restart Codex so a new session loads the skill snapshot",
        "restart Kimi Code so a new session loads the skill snapshot",
    ),
    (
        "restart Codex if the skill does not appear in the active session",
        "restart Kimi Code if the skill does not appear in the active session",
    ),
    ("will not load until Codex restarts", "will not load until Kimi Code restarts"),
)

# Substitutions for bundled scripts, kept separate from Markdown because they
# rewrite executable behavior rather than prose. Multi-line blocks use raw
# triple-single-quoted literals so backslashes and quotes match the upstream
# bytes exactly. Skill discovery narrows to the Kimi Code roots: this artifact
# diagnoses one host, and a copy sitting in another host's root is neither
# reachable here nor a duplicate of anything. `~/.agents/skills` is a Kimi
# Code root natively, so it stays.
SCRIPT_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    (
        r'''    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home).expanduser().joinpath("skills"))
    candidates.extend(
        [Path.home().joinpath(".codex/skills"), Path.home().joinpath(".agents/skills")]
    )
''',
        r'''    # Only Kimi Code skill roots count here. A skill installed in
    # another host's root is not reachable from this one, and counting it
    # would report a cross-host copy as a duplicate installation and
    # degrade a diagnosis that is about this host.
    kimi_home = os.environ.get("KIMI_CODE_HOME")
    if kimi_home:
        candidates.append(Path(kimi_home).expanduser().joinpath("skills"))
    candidates.extend(
        [Path.home().joinpath(".kimi-code/skills"), Path.home().joinpath(".agents/skills")]
    )
''',
    ),
    # Upstream classifies the Ouroboros registration from a `codex mcp get`
    # JSON probe. Kimi Code has no `mcp` CLI subcommand, so the whole
    # classifier is replaced with one that reads the host's mcp.json files:
    # `$KIMI_CODE_HOME/mcp.json` (user level) and `.kimi-code/mcp.json`
    # (project level, which overrides the user entry on a name collision).
    (
        r'''def classify_ouroboros_registration(
    raw_probe: dict[str, Any],
) -> dict[str, Any]:
    probe = {
        key: raw_probe[key] for key in ("attempted", "ok", "exit_code", "timed_out")
    }
    if raw_probe["timed_out"]:
        probe["reason"] = "registration_probe_timed_out"
        return {"status": "degraded", "probe": probe}
    if raw_probe.get("error_code"):
        probe["error_code"] = raw_probe["error_code"]
        probe["reason"] = "registration_probe_failed"
        return {"status": "degraded", "probe": probe}

    stderr = raw_probe.get("stderr", "").strip()
    if not raw_probe["ok"]:
        not_found = re.fullmatch(
            r"(?:Error:\s*)?No MCP server named ['\"]?ouroboros['\"]? found\.?",
            stderr,
        )
        probe["reason"] = (
            "registration_not_found" if not_found else "registration_probe_failed"
        )
        return {
            "status": "missing" if not_found else "degraded",
            "probe": probe,
        }

    parsed = parse_json_probe(raw_probe)
    if parsed.get("error_code") == "invalid_json":
        probe["error_code"] = "invalid_json"
        probe["reason"] = "registration_invalid_json"
        return {"status": "degraded", "probe": probe}
    result = parsed.get("result")
    if not isinstance(result, dict):
        probe["reason"] = "registration_result_invalid"
        return {"status": "degraded", "probe": probe}
    if result.get("enabled") is True:
        return {"status": "configured", "probe": probe}
    if result.get("enabled") is False:
        probe["reason"] = "registration_disabled"
    elif "enabled" not in result:
        probe["reason"] = "registration_enabled_missing"
    else:
        probe["reason"] = "registration_enabled_invalid"
    return {"status": "degraded", "probe": probe}
''',
        r'''def ouroboros_mcp_registration(repository: Path) -> dict[str, Any]:
    # Kimi Code has no `mcp get` CLI probe; registrations live in
    # `$KIMI_CODE_HOME/mcp.json` (user level) and `.kimi-code/mcp.json`
    # (project level, which overrides the user entry on a name collision).
    # The entry resolving at all is the registration signal; a disabled entry
    # degrades rather than disappears.
    probe: dict[str, Any] = {
        "attempted": True,
        "ok": True,
        "exit_code": 0,
        "timed_out": False,
    }
    kimi_home = os.environ.get("KIMI_CODE_HOME")
    config_home = Path(kimi_home).expanduser() if kimi_home else Path.home().joinpath(".kimi-code")
    sources = [config_home.joinpath("mcp.json"), repository.joinpath(".kimi-code/mcp.json")]
    entry: Any = None
    found = False
    for source in sources:
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, json.JSONDecodeError):
            probe["reason"] = "registration_invalid_json"
            return {"status": "degraded", "probe": probe}
        servers = document.get("mcpServers") if isinstance(document, dict) else None
        if isinstance(servers, dict) and "ouroboros" in servers:
            entry = servers["ouroboros"]
            found = True
    if not found:
        probe["reason"] = "registration_not_found"
        return {"status": "missing", "probe": probe}
    if isinstance(entry, dict) and entry.get("enabled") is False:
        probe["reason"] = "registration_disabled"
        return {"status": "degraded", "probe": probe}
    return {"status": "configured", "probe": probe}
''',
    ),
    # The Codex probe of the Ouroboros MCP registration moves to the mcp.json
    # reader above. On this host the integration consists of that entry plus
    # the user-scoped Ouroboros skills under the Kimi Code skill roots, so the
    # registration doubles as the host-integration signal.
    (
        r'''    codex = shutil.which("codex")
    if codex:
        registration_raw = run_command(
            [
                str(Path(codex).resolve()),
                "mcp",
                "get",
                "ouroboros",
                "--json",
            ],
            repository,
            timeout_seconds,
        )
        tool["mcp_registration"] = classify_ouroboros_registration(
            registration_raw
        )
    else:
        tool["mcp_registration"] = {
            "status": "unverifiable",
            "probe": skipped_probe("codex_executable_missing"),
        }
''',
        r'''    tool["mcp_registration"] = ouroboros_mcp_registration(repository)
    host_integration = {
        "status": tool["mcp_registration"]["status"],
        "probe": tool["mcp_registration"]["probe"],
    }
''',
    ),
    # `ooo codex doctor` has no Kimi Code counterpart, so the integration
    # component is taken from the mcp.json registration above.
    (
        r'''    codex_doctor = run_command(
        [tool["executable"], "codex", "doctor"], repository, timeout_seconds
    )
    tool["codex_integration"] = {
        "status": "configured" if codex_doctor["ok"] else "degraded",
        "probe": {
            key: codex_doctor[key]
            for key in ("attempted", "ok", "exit_code", "timed_out")
        },
    }
''',
        r'''    # `ooo codex doctor` verifies another host's routing artifacts and has
    # no Kimi Code counterpart. The mcp.json registration resolved above is
    # the host-integration signal here, so it is recorded rather than reprobed.
    tool["host_integration"] = host_integration
''',
    ),
    # The reported component is the host's own integration here, not Codex's.
    (
        r'''        tool["codex_integration"] = {
            "status": "missing",
            "probe": skipped_probe("executable_missing"),
        }
''',
        r'''        tool["host_integration"] = {
            "status": "missing",
            "probe": skipped_probe("executable_missing"),
        }
''',
    ),
    # ...and the readiness rollup reads the renamed component.
    (
        r'''        and tool["codex_integration"]["status"] == "configured"
''',
        r'''        and tool["host_integration"]["status"] == "configured"
''',
    ),
    # Upstream reads this component from the doctor's exit code. The MCP 2
    # server registered in mcp.json launches as a separate process while the
    # CLI environment keeps MCP 1.x, so the doctor's `mcp_import` check — and
    # the exit code with it — fails on a correctly configured machine. The
    # remaining checks carry runtime health here; the server's own health is
    # the registration component.
    (
        r'''    tool["mcp_runtime"] = {
        "status": "configured" if mcp_doctor["ok"] else "degraded",
        "probe": normalized_probe(mcp_doctor),
    }
''',
        r'''    doctor_checks = mcp_doctor.get("result")
    runtime_probe = normalized_probe(mcp_doctor)
    if isinstance(doctor_checks, list):
        failed = sorted(
            str(check.get("name"))
            for check in doctor_checks
            if isinstance(check, dict)
            and check.get("status") == "fail"
            and check.get("name") != "mcp_import"
        )
        if failed:
            runtime_probe["reason"] = "doctor_checks_failed"
        tool["mcp_runtime"] = {
            "status": "degraded" if failed else "configured",
            "failed_checks": failed,
            "probe": runtime_probe,
        }
    else:
        tool["mcp_runtime"] = {
            "status": "degraded",
            "probe": runtime_probe,
        }
''',
    ),
    # `hooks/task_commit_gate.py` names the remediation skill in the text the
    # user sees when a commit is denied. Markdown rules do not reach `.py`.
    ("$aquarium:", "/skill:"),
)

# Text that must exist after transformation, relative to the staged repository
# fragment. A script substitution that quietly stops matching would otherwise
# ship a script searching only Codex paths, and the Markdown forbidden-check
# cannot see it. The Ouroboros blocks are multi-line matches, so a reformat
# upstream would stop them matching and silently restore the Codex-only
# inspection.
REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    ("plugins/aquarium/skills/dev-setup/scripts/inspect_tools.py", "KIMI_CODE_HOME"),
    ("plugins/aquarium/skills/dev-setup/scripts/inspect_tools.py", '".kimi-code/skills"'),
    ("plugins/aquarium/skills/dev-setup/scripts/inspect_tools.py", "ouroboros_mcp_registration"),
    ("plugins/aquarium/skills/dev-setup/scripts/inspect_tools.py", '"host_integration"'),
    ("plugins/aquarium/skills/dev-setup/scripts/inspect_tools.py", "doctor_checks_failed"),
    ("plugins/aquarium/hooks/task_commit_gate.py", "/skill:task-commit"),
    (".kimi-plugin/plugin.json", "${KIMI_PLUGIN_ROOT}/plugins/aquarium/hooks/task_commit_gate.py"),
)

# Strings that must not survive into the generated tree, scanned across the
# whole staged repository fragment. Each entry pairs a needle with the remedy,
# so a failure names its own fix.
FORBIDDEN: tuple[tuple[str, str], ...] = (
    ("$aquarium:", "add a substitution rule"),
    ("$use-", "add a substitution rule"),
    ("$lore-", "add a substitution rule"),
    ("$orca-cli", "add a substitution rule"),
    ("request_user_input", "add a substitution rule or an override"),
    ("--agent codex", "add an override"),
    (".codex/skills", "Kimi Code loads ~/.kimi-code/skills and ~/.agents/skills; add a substitution rule"),
    ("${PLUGIN_ROOT}", "Kimi Code provides ${KIMI_PLUGIN_ROOT}; fix the hook conversion"),
    ("Codex", "add a substitution rule, an override, or a reviewed exemption"),
)

# Every lowercase `$name` in upstream Markdown is a Codex skill invocation.
# `FORBIDDEN` names one needle per sigil family that already exists, so a family
# upstream introduces later passes both the substitution table and the forbidden
# scan and ships Codex invocation syntax to a Kimi Code user in silence.
# Uppercase spellings are environment variables the generated tree still needs
# (`${KIMI_PLUGIN_ROOT}`, `$KIMI_CODE_HOME`) and deliberately do not match.
SIGIL = re.compile(r"\$[a-z][a-z0-9:_-]*")


class SyncError(RuntimeError):
    """A condition that must stop generation rather than produce partial output."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_commit() -> str:
    result = subprocess.run(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SyncError(
            "cannot resolve the upstream commit; run `git submodule update --init`"
        )
    return result.stdout.strip()


def require_upstream() -> None:
    """Refuse to generate from a missing or partially initialized submodule.

    Plugin installation treats a failed submodule clone as non-fatal, so an
    empty `upstream/` is a realistic state. Generating from it would silently
    delete the committed plugin.
    """
    marker = UPSTREAM_PLUGIN / ".codex-plugin" / "plugin.json"
    if not marker.is_file():
        raise SyncError(
            f"upstream plugin not found at {marker}; "
            "run `git submodule update --init --recursive` before syncing"
        )
    for name in ("skills", "hooks"):
        if not (UPSTREAM_PLUGIN / name).is_dir():
            raise SyncError(f"upstream is missing `{name}/`; refusing to generate")
    check_upstream_directories()


def check_upstream_directories() -> None:
    """Refuse to generate when upstream grows a directory nobody decided about.

    `COPIED_DIRECTORIES` is an allowlist with no counterpart check, so a new
    directory upstream would otherwise be dropped in silence. Whether it
    belongs in a Kimi artifact is a decision, and skipping it is not a safe
    default.
    """
    known = set(COPIED_DIRECTORIES) | {".codex-plugin"}
    unknown = sorted(
        path.name
        for path in UPSTREAM_PLUGIN.iterdir()
        if path.is_dir() and path.name not in known
    )
    if unknown:
        raise SyncError(
            "upstream has directories this transformation does not handle: "
            + ", ".join(unknown)
            + "; add them to COPIED_DIRECTORIES or exclude them deliberately"
        )


def apply_substitutions(text: str) -> str:
    for old, new in SUBSTITUTIONS:
        text = text.replace(old, new)
    return text


def read_sidecar_policy(skill: Path) -> bool:
    """Return `allow_implicit_invocation` for one upstream skill.

    The Codex sidecar is the single source of truth for invocation policy, so
    the Kimi frontmatter flag cannot drift from it. A missing or malformed
    sidecar is an error: guessing a default would risk letting a mutating
    skill fire without the user asking for it.
    """
    sidecar = skill / "agents" / "openai.yaml"
    if not sidecar.is_file():
        raise SyncError(
            f"skill `{skill.name}` has no agents/openai.yaml; "
            "invocation policy cannot be derived and will not be guessed"
        )
    match = re.search(
        r"^\s*allow_implicit_invocation:\s*(true|false)\s*$",
        sidecar.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        raise SyncError(
            f"skill `{skill.name}` sidecar has no boolean allow_implicit_invocation"
        )
    return match.group(1) == "true"


def gate_frontmatter(text: str, skill_name: str, allow_implicit: bool) -> str:
    """Insert `disable-model-invocation: true` when implicit invocation is off.

    Kimi Code accepts the kebab-case key as an alias of `disableModelInvocation`,
    so the policy moves into the frontmatter without renaming it. Codex's own
    plugin validator rejects this key, which is precisely why the generated
    tree is a separate artifact.
    """
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise SyncError(f"skill `{skill_name}` has no frontmatter block")
    if allow_implicit:
        return text
    body = match.group(1)
    if "disable-model-invocation" in body:
        raise SyncError(f"skill `{skill_name}` already declares disable-model-invocation")
    return text.replace(
        match.group(0),
        f"---\n{body}\ndisable-model-invocation: true\n---\n",
        1,
    )


def copy_tree(destination: Path) -> None:
    for name in COPIED_DIRECTORIES:
        source = UPSTREAM_PLUGIN / name
        if source.is_dir():
            shutil.copytree(source, destination / name)


def transform_skills(destination: Path) -> None:
    skills = destination / "skills"
    for skill in sorted(p for p in skills.iterdir() if p.is_dir()):
        allow_implicit = read_sidecar_policy(UPSTREAM_PLUGIN / "skills" / skill.name)
        skill_md = skill / "SKILL.md"
        if not skill_md.is_file():
            raise SyncError(f"skill `{skill.name}` has no SKILL.md")
        skill_md.write_text(
            gate_frontmatter(skill_md.read_text(encoding="utf-8"), skill.name, allow_implicit),
            encoding="utf-8",
        )
        # The Codex sidecar has no meaning for Kimi Code and its `$` prompts
        # would contradict the generated text, so it is dropped.
        shutil.rmtree(skill / "agents", ignore_errors=True)


def transform_text(destination: Path) -> None:
    for path in sorted(destination.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in TEXT_SUFFIXES:
            rules = SUBSTITUTIONS
        elif path.suffix in SCRIPT_SUFFIXES:
            rules = SCRIPT_SUBSTITUTIONS
        else:
            continue
        original = path.read_text(encoding="utf-8")
        replaced = original
        for old, new in rules:
            replaced = replaced.replace(old, new)
        if replaced != original:
            path.write_text(replaced, encoding="utf-8")


def convert_hooks(destination: Path) -> list[dict[str, Any]]:
    """Translate the upstream hook declaration into Kimi manifest entries.

    Kimi Code does not auto-load `hooks/hooks.json`; plugin hooks are declared
    in the manifest as flat `{event, matcher, command, timeout}` entries whose
    commands run with the plugin root as working directory and
    `KIMI_PLUGIN_ROOT` in the environment. The plugin root here is the
    installed repository, so the script path gains a `plugins/aquarium`
    prefix. The declaration file is dropped from the generated tree; the gate
    script itself stays.
    """
    source_path = destination / "hooks" / "hooks.json"
    if not source_path.is_file():
        raise SyncError(
            "upstream hooks/hooks.json was not copied; cannot derive the manifest hooks"
        )
    source = json.loads(source_path.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = []
    for event, matchers in source.get("hooks", {}).items():
        if not isinstance(matchers, list):
            raise SyncError(f"unexpected hooks.json shape for event `{event}`")
        for matcher_entry in matchers:
            for hook in matcher_entry.get("hooks", []):
                if hook.get("type") != "command":
                    raise SyncError(
                        f"unsupported hook type `{hook.get('type')}` for event `{event}`"
                    )
                entry: dict[str, Any] = {
                    "event": event,
                    "matcher": matcher_entry.get("matcher"),
                    "command": hook["command"].replace(
                        "${PLUGIN_ROOT}", "${KIMI_PLUGIN_ROOT}/plugins/aquarium"
                    ),
                }
                if "timeout" in hook:
                    entry["timeout"] = hook["timeout"]
                entries.append(entry)
    source_path.unlink()
    return entries


def check_required(staged_root: Path) -> None:
    missing: list[str] = []
    for relative, needle in REQUIRED_TEXT:
        path = staged_root / relative
        if not path.is_file():
            missing.append(f"  {relative}: file not generated")
        elif needle not in path.read_text(encoding="utf-8"):
            missing.append(f"  {relative}: missing `{needle}` — a substitution stopped matching")
    if missing:
        raise SyncError("required text is absent from the generated tree:\n" + "\n".join(missing))


def upstream_manifest() -> dict[str, Any]:
    return json.loads(
        (UPSTREAM_PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )


def load_override_manifest() -> dict[str, str]:
    if not OVERRIDE_MANIFEST.is_file():
        return {}
    return json.loads(OVERRIDE_MANIFEST.read_text(encoding="utf-8"))


def check_codex_exemptions() -> set[str]:
    """Return the paths whose remaining `Codex` mentions were reviewed and kept.

    Some upstream text names the Codex CLI as a third-party tool rather than as
    the host running the skill — a Mulgae provider, a required CLI version. That
    text is correct in a Kimi artifact and cannot be renamed without making it
    false, but it still trips the `Codex` needle after an override is applied,
    because overrides do not exempt their own content.

    An exemption records that a human read every remaining mention in one file
    and confirmed each is third-party. That judgement holds only for the bytes it
    was made against, so an upstream edit stops the run instead of widening the
    exemption in silence.
    """
    if not CODEX_EXEMPTIONS.is_file():
        return set()
    recorded_all: dict[str, str] = json.loads(CODEX_EXEMPTIONS.read_text(encoding="utf-8"))
    for relative, recorded in sorted(recorded_all.items()):
        source = UPSTREAM_PLUGIN / relative
        if not source.is_file():
            raise SyncError(
                f"`Codex` exemption targets `{relative}`, which no longer exists "
                "upstream; remove the exemption or retarget it"
            )
        current = digest(source)
        if current != recorded:
            raise SyncError(
                f"`Codex` exemption stale: `{relative}` changed upstream\n"
                f"  recorded {recorded}\n"
                f"  current  {current}\n"
                "re-read every remaining `Codex` mention, confirm each still names "
                "the third-party CLI, then update overrides/codex-exemptions.json"
            )
    return set(recorded_all)


def apply_overrides(destination: Path) -> list[str]:
    """Replace files whose Kimi form diverges semantically from upstream.

    Every override records the SHA-256 of the upstream file it was derived
    from. When upstream changes that file the override is stale, and merging
    it silently would ship guidance that no longer matches the source. That is
    the one failure mode that quietly breaks a fork, so it stops the run.
    """
    manifest = load_override_manifest()
    applied: list[str] = []
    for relative, recorded in sorted(manifest.items()):
        source = UPSTREAM_PLUGIN / relative
        override = OVERRIDES / relative
        if not override.is_file():
            raise SyncError(f"override file missing: {override}")
        if not source.is_file():
            raise SyncError(
                f"override targets `{relative}`, which no longer exists upstream; "
                "remove the override or retarget it"
            )
        current = digest(source)
        if current != recorded:
            raise SyncError(
                f"override stale: `{relative}` changed upstream\n"
                f"  recorded {recorded}\n"
                f"  current  {current}\n"
                "re-derive the override from the new upstream content, then update "
                "overrides/manifest.json"
            )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(override, target)
        applied.append(relative)
    return applied


def write_plugin_manifest(staged_root: Path, hooks: list[dict[str, Any]]) -> None:
    """Derive the Kimi manifest from the Codex one so versions cannot diverge.

    The manifest lives at the repository root because `/plugins install`
    treats the installed directory as the plugin root. The generated tree
    stays under `plugins/aquarium/`, and the manifest points into it. Only
    documented Kimi fields are emitted; Codex-only interface keys
    (`defaultPrompt`, `category`, `capabilities`, icon fields) are dropped
    rather than reported as diagnostics.
    """
    codex = upstream_manifest()
    interface = codex.get("interface", {})
    author = codex.get("author")
    manifest: dict[str, Any] = {
        "name": codex["name"],
        "version": codex["version"],
        "description": apply_substitutions(codex["description"]),
        "author": author.get("name") if isinstance(author, dict) else author,
        "homepage": codex["homepage"],
        "license": codex["license"],
        "keywords": codex["keywords"],
        "skills": "./plugins/aquarium/skills/",
        "interface": {
            key: interface[key]
            for key in (
                "displayName",
                "shortDescription",
                "longDescription",
                "developerName",
                "websiteURL",
            )
            if interface.get(key) is not None
        },
        "hooks": hooks,
    }
    directory = staged_root / ".kimi-plugin"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def check_forbidden(staged_root: Path, codex_exemptions: set[str]) -> None:
    """Scan every generated text file for host-specific text.

    Scripts and YAML are included, as is the root manifest. Only the `Codex`
    needle is skipped, and only for reviewed exemptions; every other needle
    applies to every file.
    """
    failures: list[str] = []
    for path in sorted(staged_root.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        relative = path.relative_to(staged_root)
        text = path.read_text(encoding="utf-8")
        for needle, remedy in FORBIDDEN:
            if needle == "Codex" and str(relative).startswith("plugins/aquarium/") and str(
                relative
            ).removeprefix("plugins/aquarium/") in codex_exemptions:
                continue
            if needle in text:
                failures.append(f"  {relative}: contains `{needle}` — {remedy}")
    if failures:
        raise SyncError("host-specific text survived transformation:\n" + "\n".join(failures))


def check_sigils(staged_root: Path) -> None:
    """Fail on any Codex skill sigil that no substitution rule rewrote.

    This closes the class rather than the known instances: an unmapped sigil is
    a silent failure, because it is valid Markdown that simply names a command
    the reader's host does not have.
    """
    failures: list[str] = []
    for path in sorted(staged_root.rglob("*.md")):
        if not path.is_file():
            continue
        found = sorted(set(SIGIL.findall(path.read_text(encoding="utf-8"))))
        if found:
            failures.append(f"  {path.relative_to(staged_root)}: {', '.join(found)}")
    if failures:
        raise SyncError(
            "Codex skill sigils survived transformation:\n"
            + "\n".join(failures)
            + "\nadd a substitution rule naming each sigil's Kimi form"
        )


def write_sync_manifest(
    destination: Path, repository: str, commit: str, overrides: list[str]
) -> None:
    files = {
        str(path.relative_to(destination)): digest(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file() and path.name != SYNC_MANIFEST
    }
    payload = {
        "upstream": {
            "repository": repository,
            "commit": commit,
        },
        "overrides": overrides,
        "files": files,
    }
    (destination / SYNC_MANIFEST).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def generate(staged_root: Path) -> tuple[str, list[str]]:
    commit = upstream_commit()
    codex_exemptions = check_codex_exemptions()
    plugin = staged_root / "plugins" / "aquarium"
    plugin.mkdir(parents=True)
    copy_tree(plugin)
    transform_text(plugin)
    # Overrides replace whole files, so they run before gating. Otherwise an
    # override would overwrite the frontmatter key and quietly reintroduce the
    # policy drift the sidecar is meant to prevent.
    overrides = apply_overrides(plugin)
    transform_skills(plugin)
    hooks = convert_hooks(plugin)
    write_plugin_manifest(staged_root, hooks)
    check_forbidden(staged_root, codex_exemptions)
    check_sigils(staged_root)
    check_required(staged_root)
    write_sync_manifest(plugin, upstream_manifest()["repository"], commit, overrides)
    return commit, overrides


def differences(left: Path, right: Path, prefix: Path = Path()) -> list[str]:
    comparison = filecmp.dircmp(str(left), str(right))
    found = [f"only in committed output: {prefix / name}" for name in sorted(comparison.left_only)]
    found += [f"only in regenerated output: {prefix / name}" for name in sorted(comparison.right_only)]
    found += [f"differs: {prefix / name}" for name in sorted(comparison.diff_files)]
    for name in sorted(comparison.common_dirs):
        found += differences(left / name, right / name, prefix / name)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed output matches a fresh regeneration",
    )
    arguments = parser.parse_args()

    try:
        require_upstream()
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary) / "repository"
            staged.mkdir()
            commit, overrides = generate(staged)

            if arguments.check:
                if not OUTPUT.is_dir() or not ROOT_MANIFEST.is_dir():
                    print(
                        "error: plugins/aquarium/ and .kimi-plugin/ have not been generated",
                        file=sys.stderr,
                    )
                    return 1
                drift = differences(OUTPUT, staged / "plugins" / "aquarium", Path("plugins/aquarium"))
                drift += differences(ROOT_MANIFEST, staged / ".kimi-plugin", Path(".kimi-plugin"))
                if drift:
                    print("error: committed output is stale:", file=sys.stderr)
                    for entry in drift:
                        print(f"  {entry}", file=sys.stderr)
                    print("\nrun `python3 scripts/sync.py` and commit the result", file=sys.stderr)
                    return 1
                print(f"in sync with upstream {commit[:9]} ({len(overrides)} overrides)")
                return 0

            for target in (OUTPUT, ROOT_MANIFEST):
                if target.exists():
                    shutil.rmtree(target)
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged / "plugins" / "aquarium", OUTPUT)
            shutil.copytree(staged / ".kimi-plugin", ROOT_MANIFEST)
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    skills = sorted(p.name for p in (OUTPUT / "skills").iterdir() if p.is_dir())
    gated = sum(
        1
        for name in skills
        if "disable-model-invocation: true" in (OUTPUT / "skills" / name / "SKILL.md").read_text(
            encoding="utf-8"
        )
    )
    print(f"generated {len(skills)} skills from upstream {commit[:9]}")
    print(f"  {gated} gated against model invocation, {len(skills) - gated} model-invocable")
    print(f"  {len(overrides)} overrides applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
