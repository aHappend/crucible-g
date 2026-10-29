#!/usr/bin/env python3
"""Discover native CLI syntax, not timing or hardware acceptance.

Run from the product root with ``python3 tests/native_contract.py`` after
independent admission as an additional check. Each run preserves fresh files
and emits their exact bytes in a stdout capsule. The latter lets the shared
runtime diagnose output-retention discrepancies without reconstructing an
earlier execution. Historical missing evidence remains missing.
Each new receipt also retains the native CLI version before its command help;
help syntax alone does not identify the tool that produced it.

The independently reviewed repair for native-invocation-contract-discovery-0291
preserves its inline Python command. The shared runtime must add ``uuid`` to
that command's imports, replace its allocation expression with
``root / 'evidence/native-contract-discovery-0291' / ('run-' + uuid.uuid4().hex)``,
retain exclusive mkdir and the remaining command, and select outputs
``evidence/native-contract-discovery-0291/run-*/``. It must also restore
native-prerequisites-discovery-0331 with the admitted command
``python3 tests/native_prerequisites.py --fit-dir
.vulcan/engineering/run-0001/quartus_sta_work --revision top`` and outputs
``evidence/native-prerequisites/run-*/``. Confirm both effective contracts before
execution; another passing diagnostic or unchanged L1 run cannot repair them.
The paired diagnostic accepts both effective check lists explicitly and rejects
one-sided repairs or divergent lists. It never loads runtime metadata itself.
When supplied the original check list, it also verifies preservation of every
other mandatory check and all discovery fields outside the admitted repair.
Matching repaired fields alone does not establish that checks were preserved.
Preservation includes the original check order; supplemental checks cannot
precede or interleave earlier mandatory checks, even when their relative order
is unchanged.
The original check list supplies the authoritative inline body automatically;
a conflicting separately supplied original body is an invalid diagnostic input.
An absent effective list is reported as unavailable evidence, never inferred
from the other list or treated as an empty, confirmed runtime contract.
Every effective check needs a unique, nonempty string identifier, including
appended checks; ambiguous identifiers cannot confirm an executable contract.
For a bounded, nonexecuting confirmation, supply an explicitly exported JSON
object with original_checks, config_checks and execution_checks using
``python3 tests/native_contract.py --check-contracts <export.json>``.
This mode prints the paired diagnostic and exits nonzero for an unapplied
repair. It does not open runtime metadata, allocate evidence or invoke tools;
the caller must retain its input, stdout, stderr and execution receipt.
The diagnostic hashes the exact exported bytes it inspected, so its result
cannot be mistaken for confirmation of a different or subsequently edited
export. This binding does not establish that an export is current runtime state.
Duplicate JSON keys are rejected at every nesting level: a shadowed check
field cannot serve as unambiguous evidence of an effective contract.
Original and effective lists also reject malformed check objects and ambiguous
identifiers before comparing preservation; invalid exports are diagnostic errors.
The single-list API rejects malformed containers and entries explicitly too,
without leaking attribute errors from check selection.
Malformed original inline Python is rejected before inspecting either effective
list, even when discovery is missing. It cannot certify body preservation or
escape the diagnostic CLI as an unhandled parser exception.
Compilation also rejects scope-invalid statements such as module-level return;
an AST alone does not establish that an inline command can execute.

The optional ``--invocation-discovery`` mode only allocates fresh children of
the historical directory. It is not the admitted inline-command repair and
must not replace that check or be appended as a substitute. The default
retention-capsule command and output namespace are unchanged. This entry point
does not modify execution contracts, overwrite historical evidence or certify
native gates.

The independent coverage-marker guard and its synthetic regression are also
used by portable L1. They do not execute STA, repair the native parser, or prove
that a native coverage query succeeded.
"""

import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md", "tests/*.py")
TIMEOUT = 3600


def validate_check_list(checks, label, allow_unavailable=False):
    if checks is None and allow_unavailable:
        return
    if (not isinstance(checks, list)
            or not all(isinstance(check, dict) for check in checks)):
        raise ValueError(label + " must be a list of check objects")
    identifiers = set()
    for index, check in enumerate(checks):
        identifier = check.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(
                f"{label}[{index}] must have a nonempty string id")
        if identifier in identifiers:
            raise ValueError(label + " contains duplicate check id: " + identifier)
        identifiers.add(identifier)


def execution_contract_diagnostics(checks, original_discovery_source=None):
    """Inspect the admitted repair without executing or changing any command.

    Callers supply effective checks explicitly. Product verification does not
    read runtime metadata, and this result is not native acceptance evidence.
    Supply the original inline source to also check preservation of its body;
    only the admitted UUID import and output allocation may change.
    """
    if checks is not None and (
            not isinstance(checks, list)
            or not all(isinstance(check, dict) for check in checks)):
        raise ValueError("Effective checks must be a list of check objects")
    discovery_id = "native-invocation-contract-discovery-0291"
    prerequisite_id = "native-prerequisites-discovery-0331"
    original = None
    if original_discovery_source is not None:
        if not isinstance(original_discovery_source, str):
            raise ValueError("Original discovery source must be inline Python text")
        try:
            original = ast.parse(original_discovery_source)
            compile(original, "<original-discovery-command>", "exec")
        except SyntaxError as error:
            raise ValueError(
                f"Original discovery source has invalid Python at line "
                f"{error.lineno}: {error.msg}") from error
        imports = [node for node in original.body if isinstance(node, ast.Import)]
        original_allocations = [
            node for node in original.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "out"
                    for target in node.targets)]
        if not imports or len(original_allocations) != 1:
            raise ValueError("Original discovery source lacks its import or allocation")
    issues = []
    if checks is None:
        issues.append("Effective check list is unavailable; contract confirmation is incomplete")
        checks = []
    seen = set()
    for index, check in enumerate(checks):
        identifier = check.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            issues.append(f"Check at index {index} lacks a nonempty string identifier")
        elif identifier in seen:
            issues.append(f"Duplicate effective check identifier: {identifier}")
        else:
            seen.add(identifier)
    selected = {}
    for identifier in (discovery_id, prerequisite_id):
        matches = [check for check in checks if check.get("id") == identifier]
        if len(matches) != 1:
            issues.append(f"{identifier}: expected exactly one effective check; found {len(matches)}")
        else:
            selected[identifier] = matches[0]
    discovery = selected.get(discovery_id)
    if discovery is not None:
        if discovery.get("outputs") != ["evidence/native-contract-discovery-0291/run-*/"]:
            issues.append(discovery_id + ": fresh-run output selector is absent")
        argv = discovery.get("argv")
        if (not isinstance(argv, list) or len(argv) != 3
                or argv[:2] != ["python3", "-c"] or not isinstance(argv[2], str)):
            issues.append(discovery_id + ": expected the preserved inline Python command")
        else:
            try:
                tree = ast.parse(argv[2])
                compile(tree, "<effective-discovery-command>", "exec")
            except SyntaxError:
                issues.append(discovery_id + ": inline Python is not syntactically valid")
            else:
                uuid_imports = [
                    index for index, node in enumerate(tree.body)
                    if isinstance(node, ast.Import)
                    and any(alias.name == "uuid" and alias.asname is None
                            for alias in node.names)]
                expected = ast.dump(ast.parse(
                    "root / 'evidence/native-contract-discovery-0291' / "
                    "('run-' + uuid.uuid4().hex)", mode="eval").body)
                allocations = [
                    (index, node.value) for index, node in enumerate(tree.body)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "out"
                            for target in node.targets)]
                allocation_valid = (
                    len(allocations) == 1
                    and ast.dump(allocations[0][1]) == expected
                    and any(index < allocations[0][0] for index in uuid_imports))
                if not allocation_valid:
                    issues.append(discovery_id + ": admitted UUID child allocation is absent")
                mkdir = ast.dump(ast.parse(
                    "out.mkdir(parents=True, exist_ok=False)", mode="eval").body)
                mkdir_indices = [
                    index for index, node in enumerate(tree.body)
                    if isinstance(node, ast.Expr) and ast.dump(node.value) == mkdir]
                if (len(mkdir_indices) != 1 or not allocation_valid
                        or mkdir_indices[0] != allocations[0][0] + 1):
                    issues.append(discovery_id + ": exclusive output allocation is absent")
                if original_discovery_source is not None:
                    original_allocations[0].value = ast.parse(
                        "root / 'evidence/native-contract-discovery-0291' / "
                        "('run-' + uuid.uuid4().hex)", mode="eval").body
                    # The admitted uuid import has no mandated position.
                    for module in (tree, original):
                        for node in module.body:
                            if isinstance(node, ast.Import):
                                node.names = [
                                    alias for alias in node.names
                                    if not (alias.name == "uuid" and alias.asname is None)]
                        module.body = [
                            node for node in module.body
                            if not isinstance(node, ast.Import) or node.names]
                    if ast.dump(tree) != ast.dump(original):
                        issues.append(discovery_id + ": remaining inline command was changed")
    prerequisite = selected.get(prerequisite_id)
    if prerequisite is not None:
        if prerequisite.get("argv") != [
                "python3", "tests/native_prerequisites.py", "--fit-dir",
                ".vulcan/engineering/run-0001/quartus_sta_work", "--revision", "top"]:
            issues.append(prerequisite_id + ": admitted prerequisite argv is absent")
        if prerequisite.get("outputs") != ["evidence/native-prerequisites/run-*/"]:
            issues.append(prerequisite_id + ": prerequisite output selector is absent")
    return {
        "kind": "read_only_execution_contract_diagnostic",
        "acceptance_evidence": False, "commands_executed": False,
        "runtime_state_modified": False,
        "required_repair_fields_present": not issues, "issues": issues,
        "remaining_command_checked": original_discovery_source is not None,
        "scope": ("Repair fields and original inline-body preservation; not native acceptance"
                  if original_discovery_source is not None else
                  "Required repair fields only; not preservation of the remaining command or native acceptance"),
    }


def effective_contract_diagnostics(config_checks, execution_checks,
                                   original_discovery_source=None,
                                   original_checks=None):
    """Inspect repair and optional baseline preservation without changing state."""
    for label, checks in (("config_checks", config_checks),
                          ("execution_checks", execution_checks)):
        if checks is not None and (
                not isinstance(checks, list)
                or not all(isinstance(check, dict) for check in checks)):
            raise ValueError(label + " must be a list of check objects")
    if original_checks is not None:
        validate_check_list(original_checks, "original_checks")
        discoveries = [
            check for check in original_checks
            if check.get("id") == "native-invocation-contract-discovery-0291"]
        if len(discoveries) != 1:
            raise ValueError("Original checks must contain exactly one discovery command")
        argv = discoveries[0].get("argv")
        if (not isinstance(argv, list) or len(argv) != 3
                or argv[:2] != ["python3", "-c"] or not isinstance(argv[2], str)):
            raise ValueError("Original discovery must contain its inline Python command")
        if (original_discovery_source is not None
                and original_discovery_source != argv[2]):
            raise ValueError("Original discovery source conflicts with original checks")
        original_discovery_source = argv[2]
    diagnostics = {
        "config": execution_contract_diagnostics(
            config_checks, original_discovery_source),
        "execution": execution_contract_diagnostics(
            execution_checks, original_discovery_source),
    }
    issues = [
        name + ": " + issue
        for name, result in diagnostics.items() for issue in result["issues"]]
    if config_checks != execution_checks:
        issues.append("Config and execution effective check lists differ")
    if original_checks is not None:
        discovery_id = "native-invocation-contract-discovery-0291"
        prerequisite_id = "native-prerequisites-discovery-0331"
        for name, checks in (("config", config_checks), ("execution", execution_checks)):
            if checks is None:
                continue
            original_ids = [check["id"] for check in original_checks]
            retained_order = [check.get("id") for check in checks
                              if check.get("id") in original_ids]
            if retained_order != original_ids:
                issues.append(f"{name}: original mandatory-check order was changed")
            if [check.get("id") for check in checks[:len(original_ids)]] != original_ids:
                issues.append(
                    f"{name}: supplemental checks must be appended after original mandatory checks")
            for original in original_checks:
                identifier = original["id"]
                matches = [check for check in checks if check.get("id") == identifier]
                if len(matches) != 1:
                    issues.append(
                        f"{name}: original check {identifier} is missing or duplicated")
                    continue
                current = matches[0]
                if identifier in (discovery_id, prerequisite_id):
                    original = {key: value for key, value in original.items()
                                if key not in ("argv", "outputs")}
                    current = {key: value for key, value in current.items()
                               if key not in ("argv", "outputs")}
                if current != original:
                    issues.append(f"{name}: original check {identifier} was changed")
    return {
        "kind": "read_only_paired_execution_contract_diagnostic",
        "acceptance_evidence": False, "commands_executed": False,
        "runtime_state_modified": False,
        "required_repair_fields_present": not issues,
        "remaining_command_checked": original_discovery_source is not None,
        "original_checks_preservation_checked": original_checks is not None,
        "contracts": diagnostics, "issues": issues,
    }


def execution_contract_self_test():
    export_json_self_test()
    discovery = {
        "id": "native-invocation-contract-discovery-0291",
        "argv": ["python3", "-c",
                 "import uuid\n"
                 "out = root / 'evidence/native-contract-discovery-0291' / "
                 "('run-' + uuid.uuid4().hex)\n"
                 "out.mkdir(parents=True, exist_ok=False)\n"],
        "outputs": ["evidence/native-contract-discovery-0291/run-*/"],
    }
    prerequisite = {
        "id": "native-prerequisites-discovery-0331",
        "argv": ["python3", "tests/native_prerequisites.py", "--fit-dir",
                 ".vulcan/engineering/run-0001/quartus_sta_work", "--revision", "top"],
        "outputs": ["evidence/native-prerequisites/run-*/"],
    }
    if not execution_contract_diagnostics([discovery, prerequisite])[
            "required_repair_fields_present"]:
        raise AssertionError("Synthetic repaired-contract control was rejected")
    variants = {
        "missing_prerequisite": [discovery],
        "duplicate_discovery": [discovery, discovery, prerequisite],
        "occupied_allocation": [
            {**discovery, "argv": ["python3", "-c",
                                  "out = root / 'evidence/native-contract-discovery-0291'\n"
                                  "out.mkdir(parents=True, exist_ok=False)\n"]}, prerequisite],
        "old_selector": [{**discovery, "outputs": ["evidence/native-contract-discovery-0291/"]},
                         prerequisite],
        "nonexclusive": [
            {**discovery, "argv": [*discovery["argv"][:2],
                                  discovery["argv"][2].replace("exist_ok=False", "exist_ok=True")]},
            prerequisite],
        "syntax_failure": [{**discovery, "argv": ["python3", "-c", "("]}, prerequisite],
        "module_return": [
            {**discovery, "argv": ["python3", "-c", discovery["argv"][2] + "return\n"]},
            prerequisite],
        "module_continue": [
            {**discovery, "argv": ["python3", "-c", discovery["argv"][2] + "continue\n"]},
            prerequisite],
        "substitute": [{**discovery, "argv": ["python3", "tests/native_contract.py"]}, prerequisite],
        "wrong_prerequisite": [discovery, {**prerequisite, "argv": ["python3", "--version"]}],
        "missing_prerequisite_outputs": [discovery, {**prerequisite, "outputs": []}],
    }
    script = discovery["argv"][2]
    allocation, mkdir = script.splitlines()[1:]
    for name, source in {
        "dead_allocation": "import uuid\nif False:\n    " + allocation
                           + "\n" + mkdir + "\n",
        "dead_mkdir": "import uuid\n" + allocation + "\nif False:\n    " + mkdir + "\n",
        "premature_mkdir": "import uuid\n" + mkdir + "\n" + allocation + "\n",
        "late_uuid_import": allocation + "\n" + mkdir + "\nimport uuid\n",
    }.items():
        variants[name] = [
            {**discovery, "argv": ["python3", "-c", source]}, prerequisite]
    rejected = {}
    for name, checks in variants.items():
        result = execution_contract_diagnostics(checks)
        if result["required_repair_fields_present"]:
            raise AssertionError("Fail-open synthetic execution contract: " + name)
        rejected[name] = result["issues"]
    original = (
        "import time\n"
        "out = root / 'evidence/native-contract-discovery-0291'\n"
        "out.mkdir(parents=True, exist_ok=False)\n"
        "receipt = {'start': time.time(), 'timeout_s': 3600}\n")
    repaired = original.replace("import time\n", "import time, uuid\n").replace(
        "out = root / 'evidence/native-contract-discovery-0291'\n",
        allocation + "\n")
    control = {**discovery, "argv": ["python3", "-c", repaired]}
    if not execution_contract_diagnostics(
            [control, prerequisite], original)["required_repair_fields_present"]:
        raise AssertionError("Preserved inline-body control was rejected")
    for source in (
        repaired.replace("import time, uuid", "import uuid, time"),
        repaired.replace("import time, uuid", "import uuid\nimport time"),
    ):
        if not execution_contract_diagnostics(
                [{**control, "argv": ["python3", "-c", source]}, prerequisite],
                original)["required_repair_fields_present"]:
            raise AssertionError("Equivalent admitted UUID import was rejected")
    for name, source in {
        "removed_receipt": repaired.rsplit("receipt =", 1)[0],
        "changed_timeout": repaired.replace("3600", "1"),
        "extra_statement": repaired + "raise SystemExit(0)\n",
    }.items():
        result = execution_contract_diagnostics(
            [{**control, "argv": ["python3", "-c", source]}, prerequisite], original)
        if result["required_repair_fields_present"]:
            raise AssertionError("Fail-open inline-body preservation: " + name)
        rejected[name] = result["issues"]
    effective = [control, prerequisite]
    paired_control = effective_contract_diagnostics(effective, effective, original)
    if not paired_control["required_repair_fields_present"]:
        raise AssertionError("Paired effective-contract control was rejected")
    unrepaired = [
        {**control, "argv": ["python3", "-c", original],
         "outputs": ["evidence/native-contract-discovery-0291/"]}]
    paired_rejections = {}
    for name, (config_checks, execution_checks) in {
        "both_unrepaired": (unrepaired, unrepaired),
        "config_only_repaired": (effective, unrepaired),
        "execution_only_repaired": (unrepaired, effective),
        "missing_from_both": ([], []),
        "config_list_unavailable": (None, effective),
        "execution_list_unavailable": (effective, None),
        "both_lists_unavailable": (None, None),
        "divergent_effective_lists": (
            effective, [*effective, {"id": "unexpected-check", "argv": ["python3"]}]),
    }.items():
        result = effective_contract_diagnostics(
            config_checks, execution_checks, original)
        if result["required_repair_fields_present"]:
            raise AssertionError("Fail-open paired execution contracts: " + name)
        paired_rejections[name] = result["issues"]
    portable = {
        "id": "portable-l1", "argv": ["python3", "tests/verify.py"],
        "inputs": ["rtl/*.sv", "tests/*.py"], "outputs": [],
        "requires": ["python3", "iverilog", "vvp", "yosys"],
        "timeout_s": 86400,
    }
    baseline = [portable, *unrepaired]
    preserved = [portable, *effective]
    preservation_control = effective_contract_diagnostics(
        preserved, preserved, original, baseline)
    if not preservation_control["required_repair_fields_present"]:
        raise AssertionError("Original mandatory-check preservation control was rejected")
    supplemented = [*preserved, {"id": "supplement", "argv": ["python3", "--version"]}]
    appended_control = effective_contract_diagnostics(
        supplemented, supplemented, original_checks=baseline)
    if not appended_control["required_repair_fields_present"]:
        raise AssertionError("Append-only supplemental-check control was rejected")
    inferred_control = effective_contract_diagnostics(
        preserved, preserved, original_checks=baseline)
    if (not inferred_control["required_repair_fields_present"]
            or not inferred_control["remaining_command_checked"]):
        raise AssertionError("Original inline-body inference control was rejected")
    preservation_rejections = {}
    for name, checks in {
        "duplicate_supplement": [*supplemented, supplemented[-1]],
        "unnamed_supplement": [*preserved, {"argv": ["python3", "--version"]}],
        "blank_supplement_id": [*preserved, {"id": " ", "argv": ["python3"]}],
        "nonstring_supplement_id": [*preserved, {"id": 12, "argv": ["python3"]}],
        "removed_portable_l1": effective,
        "reordered_original_checks": [control, portable, prerequisite],
        "prepended_prerequisite": [prerequisite, portable, control],
        "interleaved_prerequisite": [portable, prerequisite, control],
        "prepended_supplement": [
            {"id": "supplement", "argv": ["python3", "--version"]}, *preserved],
        "interleaved_supplement": [
            portable, {"id": "supplement", "argv": ["python3", "--version"]},
            control, prerequisite],
        "duplicate_portable_l1": [portable, *preserved],
        "replaced_portable_argv": [
            {**portable, "argv": ["python3", "--version"]}, *effective],
        "removed_portable_inputs": [{**portable, "inputs": []}, *effective],
        "removed_portable_dependency": [
            {**portable, "requires": ["python3"]}, *effective],
        "shortened_portable_timeout": [
            {**portable, "timeout_s": 1}, *effective],
        "altered_discovery_inputs": [
            portable, {**control, "inputs": []}, prerequisite],
        "altered_inline_body_without_explicit_source": [
            portable, {**control, "argv": [
                "python3", "-c", repaired.replace("3600", "1")]}, prerequisite],
    }.items():
        result = effective_contract_diagnostics(
            checks, checks, original_checks=baseline)
        if result["required_repair_fields_present"]:
            raise AssertionError("Fail-open mandatory-check preservation: " + name)
        preservation_rejections[name] = result["issues"]
    baseline_rejections = {}
    for name, config_checks, execution_checks in (
        ("config_list_unavailable", None, preserved),
        ("execution_list_unavailable", preserved, None),
        ("both_lists_unavailable", None, None),
    ):
        result = effective_contract_diagnostics(
            config_checks, execution_checks, original_checks=baseline)
        if (result["required_repair_fields_present"]
                or not any("unavailable" in issue for issue in result["issues"])):
            raise AssertionError("Unavailable effective contract was inferred: " + name)
        preservation_rejections[name] = result["issues"]
    for name, source, checks in (
        ("conflicting_original_source", repaired, baseline),
        ("missing_original_discovery", None, [portable]),
        ("duplicate_original_discovery", None, [*baseline, unrepaired[0]]),
        ("noninline_original_discovery", None, [
            portable, {**unrepaired[0], "argv": ["python3", "--version"]}]),
    ):
        try:
            effective_contract_diagnostics(preserved, preserved, source, checks)
        except ValueError as error:
            baseline_rejections[name] = str(error)
        else:
            raise AssertionError("Invalid original-check baseline accepted: " + name)
    for name, source in (
        ("invalid_original_python", "("),
        ("missing_original_import", "out = root / 'evidence'\n"),
        ("missing_original_allocation", "import time\n"),
        ("nontext_original_python", 42),
        ("module_return_original_python", original + "return\n"),
        ("module_continue_original_python", original + "continue\n"),
    ):
        for suffix, checks in (("present", effective), ("absent", [])):
            try:
                execution_contract_diagnostics(checks, source)
            except ValueError as error:
                baseline_rejections[name + "_" + suffix] = str(error)
            else:
                raise AssertionError("Invalid original inline source accepted: " + name)
    for name, checks in (
        ("single_list_mapping", {}),
        ("single_list_text", "unavailable"),
        ("single_list_nonobject", [None]),
        ("single_list_mixed_entries", [control, 42, prerequisite]),
    ):
        try:
            execution_contract_diagnostics(checks, original)
        except ValueError as error:
            baseline_rejections[name] = str(error)
        else:
            raise AssertionError("Malformed single-list contract accepted: " + name)
    for name, field, value in (
        ("original_not_list", "original_checks", {}),
        ("original_nonobject", "original_checks", [None]),
        ("original_missing_id", "original_checks", [*baseline, {}]),
        ("original_blank_id", "original_checks", [*baseline, {"id": " "}]),
        ("original_duplicate_id", "original_checks", [*baseline, portable]),
        ("config_not_list", "config_checks", {}),
        ("config_nonobject", "config_checks", [None]),
        ("execution_not_list", "execution_checks", "unavailable"),
        ("execution_nonobject", "execution_checks", [None]),
    ):
        arguments = {
            "config_checks": preserved, "execution_checks": preserved,
            "original_checks": baseline,
        }
        arguments[field] = value
        try:
            effective_contract_diagnostics(**arguments)
        except ValueError as error:
            baseline_rejections[name] = str(error)
        else:
            raise AssertionError("Malformed contract input accepted: " + name)
    return {"kind": "synthetic_execution_contract_sensitivity",
            "acceptance_evidence": False, "commands_executed": False,
            "accepted_control": True, "preserved_body_control": True,
            "rejections": rejected, "paired_control": paired_control,
            "paired_rejections": paired_rejections,
            "preservation_control": preservation_control,
            "appended_supplement_control": appended_control,
            "inferred_body_control": inferred_control,
            "preservation_rejections": preservation_rejections,
            "baseline_rejections": baseline_rejections}


def unconstrained_setup_count(text):
    """Parse one explicit native marker; absent/ambiguous evidence is not zero.

    A parsed zero alone is not timing acceptance: the producer must separately
    establish a successful coverage query and complete synchronous-path scope.
    """
    marker = "UNCONSTRAINED_SETUP_PATHS"
    lines = [line.strip() for line in text.splitlines() if marker in line]
    if len(lines) != 1:
        raise ValueError("Expected exactly one unconstrained setup-path marker")
    match = re.fullmatch(marker + r":([0-9]+)", lines[0])
    if match is None:
        raise ValueError("Malformed unconstrained setup-path count")
    return int(match.group(1))


def require_zero_unconstrained_setup(text):
    count = unconstrained_setup_count(text)
    if count != 0:
        raise ValueError(f"Unconstrained setup paths remain: {count}")
    return count


def coverage_marker_self_test():
    """Synthetic evidence-validation sensitivity, never a native-gate result."""
    valid = {
        "explicit_zero": "UNCONSTRAINED_SETUP_PATHS:0\n",
        "surrounding_output": "Info: TimeQuest\nUNCONSTRAINED_SETUP_PATHS:0\nInfo: done\n",
    }
    rejected = {
        "missing": "",
        "slack_only": "Setup WNS = 0.280 ns\nHold WNS = 0.039 ns\n",
        "malformed": "UNCONSTRAINED_SETUP_PATHS:not-a-count\n",
        "empty_count": "UNCONSTRAINED_SETUP_PATHS:\n",
        "negative": "UNCONSTRAINED_SETUP_PATHS:-1\n",
        "fractional": "UNCONSTRAINED_SETUP_PATHS:0.0\n",
        "unknown": "UNCONSTRAINED_SETUP_PATHS:x\n",
        "non_ascii_digit": "UNCONSTRAINED_SETUP_PATHS:\u0660\n",
        "trailing_text": "UNCONSTRAINED_SETUP_PATHS:0 query failed\n",
        "prefixed_text": "ERROR: UNCONSTRAINED_SETUP_PATHS:0\n",
        "duplicate_zero": "UNCONSTRAINED_SETUP_PATHS:0\n" * 2,
        "conflicting_counts": "UNCONSTRAINED_SETUP_PATHS:0\nUNCONSTRAINED_SETUP_PATHS:1\n",
        "malformed_then_zero": "UNCONSTRAINED_SETUP_PATHS:bad\nUNCONSTRAINED_SETUP_PATHS:0\n",
        "nonzero": "UNCONSTRAINED_SETUP_PATHS:1\n",
        "nonzero_many": "UNCONSTRAINED_SETUP_PATHS:20\n",
    }
    accepted = {name: require_zero_unconstrained_setup(text)
                for name, text in valid.items()}
    if accepted != dict.fromkeys(valid, 0):
        raise AssertionError("Explicit-zero coverage-marker control failed")
    for count in (1, 20):
        if unconstrained_setup_count(f"UNCONSTRAINED_SETUP_PATHS:{count}\n") != count:
            raise AssertionError("Nonzero coverage count was lost")
    reasons = {}
    for name, text in rejected.items():
        try:
            require_zero_unconstrained_setup(text)
        except ValueError as error:
            reasons[name] = str(error)
        else:
            raise AssertionError("Fail-open coverage-marker fixture: " + name)
    return {
        "kind": "synthetic_coverage_marker_sensitivity",
        "acceptance_evidence": False, "native_gate_executed": False,
        "runtime_parser_repaired": False,
        "scope": "Marker syntax and zero-count rejection only; not query-success or timing proof",
        "accepted_controls": accepted, "rejections": reasons,
        "fixtures": {"accepted": valid, "rejected": rejected},
    }


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    if json.loads(path.read_text()) != value:
        raise RuntimeError("Receipt read-back mismatch")


def capture(root, output, name, argv, receipt):
    row = {
        "name": name, "argv": argv, "cwd": ".", "start": time.time(),
        "timeout_s": TIMEOUT, "exit_code": None, "timed_out": False,
        "stdout": (output / (name + ".stdout")).relative_to(root).as_posix(),
        "stderr": (output / (name + ".stderr")).relative_to(root).as_posix(),
    }
    receipt["commands"].append(row)
    save(output / "receipt.json", receipt)
    try:
        with (root / row["stdout"]).open("xb") as stdout, (
                root / row["stderr"]).open("xb") as stderr:
            result = subprocess.run(argv, cwd=root, stdout=stdout, stderr=stderr,
                                    timeout=TIMEOUT, check=False)
            row["exit_code"] = result.returncode
    except subprocess.TimeoutExpired:
        row["timed_out"] = True
        raise
    finally:
        row["end"] = time.time()
        save(output / "receipt.json", receipt)
    if row["exit_code"] != 0:
        raise RuntimeError(name + " command failed; inspect retained raw streams")
    if not any((root / row[stream]).stat().st_size
               for stream in ("stdout", "stderr")):
        raise RuntimeError(name + " returned empty command output")


def capture_version(root, output, receipt):
    """Bind this invocation's help output to its actual native CLI version."""
    capture(root, output, "vulcan-version", ["vulcan", "--version"], receipt)
    row = receipt["commands"][-1]
    receipt["tool_versions"] = {
        "python3": {"version": sys.version},
        "vulcan": {key: row[key] for key in ("argv", "stdout", "stderr", "exit_code")},
    }
    save(output / "receipt.json", receipt)


def emit_capsule(root, output, receipt):
    """Include actual retained bytes, never replacement historical evidence."""
    files = {}
    for row in receipt["commands"]:
        for stream in ("stdout", "stderr"):
            path = root / row[stream]
            if not path.is_file():
                raise RuntimeError("Missing new execution stream: " + row[stream])
            data = path.read_bytes()
            files[row[stream]] = {
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "base64": base64.b64encode(data).decode("ascii"),
            }
    receipt["retained_files"] = {
        name: {key: value for key, value in item.items() if key != "base64"}
        for name, item in files.items()
    }
    save(output / "receipt.json", receipt)
    data = (output / "receipt.json").read_bytes()
    files[(output / "receipt.json").relative_to(root).as_posix()] = {
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "base64": base64.b64encode(data).decode("ascii"),
    }
    print(json.dumps({
        "kind": "native-invocation-discovery-capsule", "schema": 1,
        "acceptance_evidence": False, "historical_evidence_reconstructed": False,
        "files": files,
    }, sort_keys=True), flush=True)


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Contract export contains duplicate JSON key: " + key)
        result[key] = value
    return result


def export_json_self_test():
    control = '{"config_checks":[{"id":"one","outputs":[]}],"execution_checks":[]}'
    if json.loads(control, object_pairs_hook=unique_json_object) != json.loads(control):
        raise AssertionError("Unambiguous contract JSON control was changed")
    for text in (
        '{"config_checks":[],"config_checks":null}',
        '{"config_checks":[{"id":"one","id":"two"}]}',
        '{"config_checks":[{"outputs":[],"outputs":["replacement"]}]}',
        '{"config_checks":[{"extra":{"timeout_s":3600,"timeout_s":1}}]}',
    ):
        try:
            json.loads(text, object_pairs_hook=unique_json_object)
        except ValueError as error:
            if "duplicate JSON key" not in str(error):
                raise
        else:
            raise AssertionError("Ambiguous contract JSON was accepted: " + text)


def check_contract_export(path):
    """Inspect an explicit export, never discover or modify runtime state."""
    source = path.read_bytes()
    data = json.loads(source, object_pairs_hook=unique_json_object)
    if not isinstance(data, dict):
        raise ValueError("Contract export must be a JSON object")
    for key in ("original_checks", "config_checks", "execution_checks"):
        if key not in data:
            raise ValueError("Contract export is missing " + key)
        validate_check_list(
            data[key], key, allow_unavailable=key != "original_checks")
    result = effective_contract_diagnostics(
        data["config_checks"], data["execution_checks"],
        original_checks=data["original_checks"])
    result["export_sha256"] = hashlib.sha256(source).hexdigest()
    result["export_bytes"] = len(source)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Retain native invocation help, not acceptance.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--invocation-discovery", action="store_true",
        help=("Use fresh children of the historical invocation-discovery directory; "
              "not a replacement for the admitted inline-command repair."))
    modes.add_argument(
        "--check-contracts", type=Path, metavar="EXPORT_JSON",
        help="Inspect explicitly supplied original and effective checks without executing tools.")
    arguments = list(sys.argv[1:] if argv is None else argv)
    options = parser.parse_args(arguments)
    if options.check_contracts is not None:
        try:
            result = check_contract_export(options.check_contracts)
        except (OSError, ValueError) as error:
            print(type(error).__name__ + ": " + str(error), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return int(not result["required_repair_fields_present"])
    namespace = ("native-contract-discovery-0291" if options.invocation_discovery
                 else "native-contract")
    output = ROOT / "evidence" / namespace / ("run-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "kind": "native-invocation-contract-discovery",
        "acceptance_evidence": False, "historical_evidence_reconstructed": False,
        "argv": ["python3", "tests/native_contract.py", *arguments], "cwd": ".",
        "start": time.time(), "end": None, "exit_code": None,
        "python_version": sys.version, "commands": [], "source_sha256": {},
        "status": "running",
    }
    save(output / "receipt.json", receipt)
    try:
        for selector in SOURCES:
            paths = sorted(ROOT.glob(selector))
            if not paths:
                raise RuntimeError("Source selector has no inputs: " + selector)
            for path in paths:
                receipt["source_sha256"][path.relative_to(ROOT).as_posix()] = (
                    hashlib.sha256(path.read_bytes()).hexdigest())
        save(output / "receipt.json", receipt)
        if shutil.which("vulcan") is None:
            raise RuntimeError("Missing prerequisite executable: vulcan")
        capture_version(ROOT, output, receipt)
        for name in ("quartus-sta", "board-hil"):
            capture(ROOT, output, name,
                    ["vulcan", "hardware", "fpga", name, "--help"], receipt)
        receipt["status"] = "invocation_help_retained_not_native_acceptance"
        receipt["exit_code"] = 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        receipt["status"] = "failed"
        receipt["exit_code"] = 1
        receipt["error"] = type(error).__name__ + ": " + str(error)
        print(receipt["error"], file=sys.stderr, flush=True)
    finally:
        receipt["end"] = time.time()
        save(output / "receipt.json", receipt)
        emit_capsule(ROOT, output, receipt)
        print((output / "receipt.json").relative_to(ROOT).as_posix(), flush=True)
    return receipt["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
