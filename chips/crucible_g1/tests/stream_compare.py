"""Transport-independent comparison of accepted public output transfers.

A bridge adapter can call compare_transfers(commands, transfers), supplying
observed (m_data, m_last) pairs only at accepted output transfers. This is a
Python adapter boundary, NOT a board transport ABI or proof of physical origin.
compare_runs(commands, runs) checks every supplied capture in order, requiring
at least three exact deterministic runs without skipping an intervening failure.
Neither API executes a transport or authenticates capture provenance.
compare_captures(commands, captures) additionally compares accepted input words
for every run. Each capture is (input_words, output_transfers), in execution
order; these iterables contain observations, not the adapter's intended sends.
This is an in-process comparison boundary, not a graphics transport ABI. It
does not establish cycle ordering, reset or stall behavior from word-only data.
compare_event_runs additionally checks cycle-stamped accepted transfers in both
directions, including the single-command-in-flight boundary. It still cannot
check unaccepted cycles, reset or stalls, or authenticate physical provenance.
compare_pin_runs accepts contiguous pre-edge public-pin samples for reset-free
runs. It checks idle outputs, stalled payloads and busy input-ready behavior as
well as accepted transfers. Output valid before full command acceptance is
rejected even when the consumer stalls. Reset and asynchronous timing still need separate
observations; no comparison API implements or authenticates physical transport.
The shared runtime must retain physical execution identity, source bindings,
timing coverage and three consecutive board runs independently. Cycle-level
reset, stall and input-handshake checks remain in the L1 public-pin testbench.
Completed-command ledgers bind input words and compared output transfers.
Their SHA256 encoding is little-endian uint32 input words, and little-endian
uint32 output words followed by a one-byte last bit; it is not a transport ABI.
"""

import hashlib

from reference import Command, IDENTITY, Q, model


class TransferMismatch(ValueError):
    pass


class TransferChecker:
    """Consume ordered words without accepting missing or extra completions."""

    def __init__(self, commands, results):
        if not commands or len(commands) != len(results):
            raise TransferMismatch("Expected a nonempty command/result sequence")
        self.expected = [result.words() for result in results]
        self.tags = [command.tag for command in commands]
        self.input_hashes = [
            hashlib.sha256(b"".join(word.to_bytes(4, "little")
                                   for word in command.words())).hexdigest()
            for command in commands
        ]
        self.command = 0
        self.offset = 0
        self.words = 0
        self.pixels = 0
        self.output_hash = hashlib.sha256()
        self.completed = []

    def accept(self, word, last):
        if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
            raise TransferMismatch("Output word must be a known unsigned 32-bit integer")
        if type(last) not in (int, bool) or last not in (0, 1):
            raise TransferMismatch("m_last must be a known single bit")
        if self.command == len(self.expected):
            raise TransferMismatch("Extra transfer after final completion")
        expected = self.expected[self.command]
        final = self.offset == len(expected) - 1
        if word != expected[self.offset] or bool(last) != final:
            raise TransferMismatch(
                f"command={self.command} tag={self.tags[self.command]} "
                f"offset={self.offset}: expected=({expected[self.offset]:08x},"
                f"{int(final)}) observed=({word:08x},{int(last)})")
        self.words += 1
        self.output_hash.update(word.to_bytes(4, "little") + bytes([last]))
        self.offset += 1
        if final:
            pixels = len(expected) // 6 - 1
            self.pixels += pixels
            self.completed.append({
                "command_index": self.command, "tag": self.tags[self.command],
                "input_words_sha256": self.input_hashes[self.command],
                "compared_transfers_sha256": self.output_hash.hexdigest(),
                "exact_words": len(expected), "pixel_records": pixels,
                "status": expected[-4], "nondegenerate_fans": expected[-2],
            })
            self.command += 1
            self.offset = 0
            self.output_hash = hashlib.sha256()

    def finish(self):
        if self.command != len(self.expected) or self.offset:
            raise TransferMismatch(
                f"Missing output: command={self.command} offset={self.offset}")
        return {
            "commands": self.command, "exact_words": self.words,
            "pixel_records": self.pixels, "all_words_ordered_exact": True,
            "completed_commands": [dict(row) for row in self.completed],
        }


def compare_transfers(commands, transfers):
    """Compare command/transfer iterables; do not infer physical provenance."""
    commands = tuple(commands)
    checker = TransferChecker(commands, [model(command) for command in commands])
    for word, last in transfers:
        checker.accept(word, last)
    return checker.finish()


def compare_runs(commands, runs):
    """Compare consecutive captures; physical identity remains runtime-owned."""
    commands = tuple(commands)
    results = [model(command) for command in commands]
    compared = []
    baseline = None
    for index, transfers in enumerate(runs):
        checker = TransferChecker(commands, results)
        try:
            for word, last in transfers:
                checker.accept(word, last)
            result = checker.finish()
        except TransferMismatch as error:
            raise TransferMismatch(f"run={index}: {error}") from error
        if baseline is None:
            baseline = result
        elif result != baseline:
            raise TransferMismatch(f"run={index}: nondeterministic comparison ledger")
        compared.append({"run_index": index, "comparison": result})
    if len(compared) < 3:
        raise TransferMismatch(
            f"Need at least three consecutive exact runs; observed={len(compared)}")
    return {
        "consecutive_exact_runs": len(compared),
        "all_runs_ordered_exact": True,
        "run_to_run_deterministic": True,
        "capture_provenance_verified": False,
        "runs": compared,
    }


def compare_captures(commands, captures):
    """Bind both directions of consecutive captures to the frozen commands."""
    commands = tuple(commands)
    expected = [word for command in commands for word in command.words()]

    def checked_outputs():
        for index, (inputs, outputs) in enumerate(captures):
            count = 0
            for offset, word in enumerate(inputs):
                if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
                    raise TransferMismatch(
                        f"run={index} input_offset={offset}: "
                        "input word must be a known unsigned 32-bit integer")
                if offset >= len(expected):
                    raise TransferMismatch(
                        f"run={index} input_offset={offset}: extra input transfer")
                if word != expected[offset]:
                    raise TransferMismatch(
                        f"run={index} input_offset={offset}: "
                        f"expected={expected[offset]:08x} observed={word:08x}")
                count += 1
            if count != len(expected):
                raise TransferMismatch(
                    f"run={index}: missing input transfers; "
                    f"expected={len(expected)} observed={count}")
            yield outputs

    result = compare_runs(commands, checked_outputs())
    return {
        **result,
        "all_input_words_ordered_exact": True,
        "accepted_input_words_per_run": len(expected),
    }


def compare_event_runs(commands, runs):
    """Compare (cycle, direction, word, last) observations, not intended sends.

    Cycles are nonnegative pre-edge sample indices within one reset-free run.
    Direction is 'input' or 'output'; input events have last=None. The frozen
    single-command interface cannot accept input and output on the same edge.
    This Python boundary defines no board transport or capture-file format.
    """
    commands = tuple(commands)
    expected_inputs = [command.words() for command in commands]

    def checked_events(run_index, events):
        previous_cycle = -1
        completed = 0
        input_offset = 0
        for cycle, direction, word, last in events:
            context = f"run={run_index} cycle={cycle}"
            if type(cycle) is not int or cycle < 0 or cycle <= previous_cycle:
                raise TransferMismatch(
                    context + ": accepted-transfer cycles must strictly increase")
            previous_cycle = cycle
            if completed == len(commands):
                raise TransferMismatch(context + ": transfer after final completion")
            if direction == "input":
                if last is not None:
                    raise TransferMismatch(context + ": input event must have last=None")
                if input_offset == 31:
                    raise TransferMismatch(
                        context + ": next command input before prior completion")
                if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
                    raise TransferMismatch(context + ": unknown or invalid input word")
                expected = expected_inputs[completed][input_offset]
                if word != expected:
                    raise TransferMismatch(
                        context + f": input_offset={input_offset} "
                        f"expected={expected:08x} observed={word:08x}")
                input_offset += 1
            elif direction == "output":
                if input_offset != 31:
                    raise TransferMismatch(
                        context + ": output before complete command acceptance")
                # The numerical checker validates the completion marker before
                # this generator advances to the next command.
                yield word, last
                if last:
                    completed += 1
                    input_offset = 0
            else:
                raise TransferMismatch(context + ": unknown transfer direction")
        if completed != len(commands) or input_offset:
            raise TransferMismatch(
                f"run={run_index}: incomplete accepted-transfer event stream")

    result = compare_runs(
        commands, (checked_events(index, events) for index, events in enumerate(runs)))
    return {
        **result,
        "all_input_words_ordered_exact": True,
        "accepted_input_words_per_run": 31 * len(commands),
        "single_command_in_flight_checked": True,
        "accepted_transfer_cycles_checked": True,
        "reset_and_stall_cycles_checked": False,
    }


def compare_pin_runs(commands, runs):
    """Compare contiguous reset-free pre-edge samples, never inferred pins.

    Each sample is (cycle, s_valid, s_ready, s_data, m_valid, m_ready,
    m_data, m_last). Begin after reset release, before the first input
    transfer. All control/output pins must be known, including idle cycles.
    Input data is checked when valid. No samples may be dropped to hide stalls.
    """
    statistics = []

    def checked_samples(run_index, samples):
        previous_cycle = None
        previous_input = None
        previous_output = None
        input_count = 0
        counts = {"samples": 0, "input_stall_edges": 0,
                  "output_stall_edges": 0, "idle_output_edges": 0}
        for sample in samples:
            if not isinstance(sample, (tuple, list)) or len(sample) != 8:
                raise TransferMismatch(
                    f"run={run_index}: expected eight public-pin sample fields")
            cycle, sv, sr, sd, mv, mr, md, ml = sample
            context = f"run={run_index} cycle={cycle}"
            if (type(cycle) is not int or cycle < 0
                    or (previous_cycle is not None and cycle != previous_cycle + 1)):
                raise TransferMismatch(context + ": pin sample cycles must be contiguous")
            previous_cycle = cycle
            for name, value in (("s_valid", sv), ("s_ready", sr),
                                ("m_valid", mv), ("m_ready", mr), ("m_last", ml)):
                if type(value) not in (int, bool) or value not in (0, 1):
                    raise TransferMismatch(context + ": unknown or invalid " + name)
            payloads = [("m_data", md)]
            if sv:
                payloads.append(("s_data", sd))
            for name, value in payloads:
                if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
                    raise TransferMismatch(context + ": unknown or invalid " + name)
            if not mv and (md != 0 or ml):
                raise TransferMismatch(context + ": inactive output is not zero")
            if previous_input is not None and (not sv or sd != previous_input):
                raise TransferMismatch(context + ": sender changed a stalled input")
            if previous_output is not None and (mv, md, ml) != previous_output:
                raise TransferMismatch(context + ": DUT changed a stalled output")
            if input_count == 31 and sr:
                raise TransferMismatch(context + ": s_ready asserted while command is busy")
            if mv and input_count != 31:
                raise TransferMismatch(
                    context + ": output valid before complete command acceptance")
            previous_input = sd if sv and not sr else None
            previous_output = (mv, md, ml) if mv and not mr else None
            counts["samples"] += 1
            counts["input_stall_edges"] += int(bool(sv and not sr))
            counts["output_stall_edges"] += int(bool(mv and not mr))
            counts["idle_output_edges"] += int(not mv)
            if sv and sr:
                input_count += 1
                yield cycle, "input", sd, None
            if mv and mr:
                yield cycle, "output", md, ml
                if ml:
                    input_count = 0
        if previous_input is not None or previous_output is not None:
            raise TransferMismatch(
                f"run={run_index}: capture ended with an unresolved stalled word")
        statistics.append({"run_index": run_index, **counts})

    result = compare_event_runs(
        commands, (checked_samples(index, samples)
                   for index, samples in enumerate(runs)))
    return {
        **result,
        "contiguous_public_pin_samples_checked": True,
        "idle_output_and_stall_stability_checked": True,
        "busy_input_ready_checked": True,
        "premature_output_valid_checked": True,
        "reset_cycles_checked": False,
        "pin_observations": statistics,
    }


def bridge_commands():
    """Small deterministic bridge workload, independent of transport details."""
    def v(x, y):
        return (x, y, Q // 2, Q)

    triangles = [
        (v(-Q, -Q), v(Q, -Q), v(-Q, Q)),
        (v(-Q // 2, -Q // 2), v(Q, -Q // 2), v(0, Q)),
        (v(-2 * Q, -Q // 2), v(Q // 2, -Q // 2), v(0, Q)),
        (v(0, 0),) * 3,
        (v(-Q, -Q), v(Q, -Q), v(-Q, Q)),
        (v(-3 * Q, 0), v(-2 * Q, -Q), v(-2 * Q, Q)),
    ]
    commands = [
        Command(index + 1, 8, 8, int(index == 4), IDENTITY, triangle)
        for index, triangle in enumerate(triangles)
    ]
    perspective = (
        Q // 2, Q // 4, 0, Q // 8,
        0, 3 * Q // 4, 0, -Q // 8,
        0, 0, Q, 0,
        Q // 4, 0, 0, Q,
    )
    commands.extend((
        Command(7, 8, 8, 0, perspective, triangles[0]),
        Command(8, 8, 8, 0, IDENTITY, (v(Q, Q), v(-Q, Q), v(Q, -Q))),
    ))
    return commands


def self_test():
    """Synthetic checker sensitivity only; never credited as board execution."""
    commands = bridge_commands()
    results = [model(command) for command in commands]
    if not ({command.mode for command in commands} == {0, 1}
            and len(results[2].fans) > 1
            and results[3].records[-1][2] == 3
            and results[5].records[-1][2] == 2
            and results[0].pixels & results[1].pixels
            and results[6].transformed != results[0].transformed
            and len({vertex[3] for vertex in results[6].transformed}) > 1
            and results[6].fractional > 0
            and not results[0].pixels & results[7].pixels
            and len(results[0].pixels | results[7].pixels) == 64):
        raise TransferMismatch("Bridge workload lost required reference categories")
    transfers = [
        (word, int(index == len(result.words()) - 1))
        for result in results for index, word in enumerate(result.words())
    ]
    baseline = compare_transfers(commands, transfers)
    if (baseline != compare_transfers(commands, iter(transfers))
            or baseline != compare_transfers(iter(commands), iter(transfers))
            or sum(row["exact_words"] for row in baseline["completed_commands"])
            != baseline["exact_words"]
            or sum(row["pixel_records"] for row in baseline["completed_commands"])
            != baseline["pixel_records"]):
        raise TransferMismatch("Completed-transfer ledger is inconsistent or nondeterministic")
    variants = {}
    altered = transfers.copy()
    altered[3] = (altered[3][0] ^ 1, altered[3][1])
    variants["barycentric_word"] = altered
    altered = transfers.copy()
    altered[1] = (altered[1][0] ^ 1, altered[1][1])
    variants["tag"] = altered
    altered = transfers.copy()
    altered[5] = (altered[5][0], 1)
    variants["early_last"] = altered
    altered = transfers.copy()
    altered[-1] = (altered[-1][0], 0)
    variants["missing_last"] = altered
    variants["missing_completion"] = transfers[:-6]
    variants["duplicate_output"] = transfers + transfers[-6:]
    variants["record_order"] = transfers[6:12] + transfers[:6] + transfers[12:]
    altered = transfers.copy()
    altered[0] = ("xxxxxxxx", 0)
    variants["unknown_word"] = altered
    altered = transfers.copy()
    altered[0] = (altered[0][0], "x")
    variants["unknown_last"] = altered
    rejections = {}
    for name, empty in (("empty_commands", []),
                        ("empty_command_iterator", iter(()))):
        try:
            compare_transfers(empty, ())
        except TransferMismatch as error:
            rejections[name] = str(error)
        else:
            raise TransferMismatch("Insensitive empty-command fixture: " + name)
    for name, captured in variants.items():
        try:
            compare_transfers(commands, captured)
        except TransferMismatch as error:
            rejections[name] = str(error)
        else:
            raise TransferMismatch("Insensitive checker fixture: " + name)
    consecutive = compare_runs(commands, (iter(transfers) for _ in range(3)))
    if (consecutive["consecutive_exact_runs"] != 3
            or any(row["run_index"] != index or row["comparison"] != baseline
                   for index, row in enumerate(consecutive["runs"]))
            or consecutive["capture_provenance_verified"]):
        raise TransferMismatch("Consecutive-run ledger is inconsistent")
    run_variants = {
        "no_runs": [],
        "two_runs": [transfers, transfers],
        "failed_middle_run": [transfers, variants["barycentric_word"], transfers],
        "missing_middle_completion": [
            transfers, variants["missing_completion"], transfers],
        "extra_middle_output": [
            transfers, variants["duplicate_output"], transfers],
        "failed_run_after_three_passes": [
            transfers, transfers, transfers, variants["tag"]],
    }
    run_rejections = {}
    for name, captures in run_variants.items():
        try:
            compare_runs(commands, iter(captures))
        except TransferMismatch as error:
            run_rejections[name] = str(error)
        else:
            raise TransferMismatch("Insensitive consecutive-run fixture: " + name)
    inputs = [word for command in commands for word in command.words()]
    captured = compare_captures(
        iter(commands), ((iter(inputs), iter(transfers)) for _ in range(3)))
    if (captured["accepted_input_words_per_run"] != 31 * len(commands)
            or not captured["all_input_words_ordered_exact"]
            or {key: captured[key] for key in consecutive} != consecutive):
        raise TransferMismatch("Bidirectional capture ledger is inconsistent")
    altered_inputs = inputs.copy()
    altered_inputs[3] ^= 1
    unknown_inputs = inputs.copy()
    unknown_inputs[0] = "xxxxxxxx"
    boolean_inputs = inputs.copy()
    boolean_inputs[0] = True
    input_variants = {
        "changed_matrix_input": altered_inputs,
        "missing_final_input": inputs[:-1],
        "extra_input": inputs + [0],
        "reordered_commands": inputs[31:62] + inputs[:31] + inputs[62:],
        "unknown_input": unknown_inputs,
        "boolean_input": boolean_inputs,
    }
    capture_rejections = {}
    for name, observed_inputs in input_variants.items():
        try:
            compare_captures(commands, [
                (inputs, transfers), (observed_inputs, transfers),
                (inputs, transfers),
            ])
        except TransferMismatch as error:
            if "run=1" not in str(error):
                raise TransferMismatch("Capture rejection lost its run index") from error
            capture_rejections[name] = str(error)
        else:
            raise TransferMismatch("Insensitive input-capture fixture: " + name)
    try:
        compare_captures(commands, [
            (inputs, transfers), (inputs, variants["barycentric_word"]),
            (inputs, transfers),
        ])
    except TransferMismatch as error:
        capture_rejections["correct_inputs_corrupted_output"] = str(error)
    else:
        raise TransferMismatch("Input checking masked corrupted output")
    events = []
    cycle = 0
    for command, result in zip(commands, results):
        for word in command.words():
            events.append((cycle, "input", word, None))
            cycle += 2
        words = result.words()
        for index, word in enumerate(words):
            events.append((cycle, "output", word, int(index == len(words) - 1)))
            cycle += 3
    ordered = compare_event_runs(commands, (iter(events) for _ in range(3)))
    if ({key: ordered[key] for key in consecutive} != consecutive
            or not ordered["single_command_in_flight_checked"]
            or not ordered["accepted_transfer_cycles_checked"]
            or ordered["reset_and_stall_cycles_checked"]
            or ordered["capture_provenance_verified"]):
        raise TransferMismatch("Ordered-event comparison lost its scope or ledger")
    reordered = events.copy()
    # Keep every input/output word individually correct while moving the next
    # command's input before the preceding completion.
    next_input = next(index for index, event in enumerate(events)
                      if index > 31 and event[1] == "input")
    event = reordered.pop(next_input)
    reordered.insert(31, event)
    reordered = [(index, *event[1:]) for index, event in enumerate(reordered)]
    same_cycle = events.copy()
    same_cycle[1] = (same_cycle[0][0], *same_cycle[1][1:])
    early_output = [events[31], *events[:31], *events[32:]]
    early_output = [(index, *event[1:]) for index, event in enumerate(early_output)]
    changed_input = events.copy()
    changed_input[3] = (*changed_input[3][:2], changed_input[3][2] ^ 1, None)
    bad_direction = events.copy()
    bad_direction[0] = (0, "send", events[0][2], None)
    event_variants = {
        "next_input_before_completion": reordered,
        "same_cycle_transfers": same_cycle,
        "output_before_input": early_output,
        "changed_input": changed_input,
        "unknown_direction": bad_direction,
        "missing_final_completion": events[:-1],
        "extra_transfer": events + [(cycle, "output", 0, 0)],
    }
    event_rejections = {}
    for name, observed in event_variants.items():
        try:
            compare_event_runs(commands, [events, observed, events])
        except TransferMismatch as error:
            if "run=1" not in str(error):
                raise TransferMismatch("Event rejection lost its run index") from error
            event_rejections[name] = str(error)
        else:
            raise TransferMismatch("Insensitive ordered-event fixture: " + name)
    samples = []
    for command, result in zip(commands, results):
        for word in command.words():
            samples.append((len(samples), 1, 0, word, 0, 1, 0, 0))
            samples.append((len(samples), 1, 0, word, 0, 1, 0, 0))
            samples.append((len(samples), 1, 1, word, 0, 1, 0, 0))
        samples.append((len(samples), 0, 0, None, 0, 1, 0, 0))
        words = result.words()
        for index, word in enumerate(words):
            last = int(index == len(words) - 1)
            samples.append((len(samples), 0, 0, None, 1, 0, word, last))
            samples.append((len(samples), 0, 0, None, 1, 0, word, last))
            samples.append((len(samples), 0, 0, None, 1, 1, word, last))
    pins = compare_pin_runs(commands, (iter(samples) for _ in range(3)))
    if ({key: pins[key] for key in consecutive} != consecutive
            or pins["reset_cycles_checked"]
            or not all(row["output_stall_edges"] == 2 * len(transfers)
                       and row["input_stall_edges"] == 62 * len(commands)
                       for row in pins["pin_observations"])):
        raise TransferMismatch("Public-pin comparison lost its scope or observations")

    def changed_sample(index, field, value):
        altered = list(samples)
        row = list(altered[index])
        row[field] = value
        altered[index] = tuple(row)
        return altered

    busy_edge = 93
    first_stall = 95

    def premature_output(start):
        altered = list(samples)
        for index in range(start, busy_edge + 1):
            cycle, sv, sr, sd, _, _, _, _ = altered[index]
            altered[index] = (cycle, sv, sr, sd, 1, 0, transfers[0][0], 0)
        return altered

    pin_variants = {
        "unaccepted_output_during_input": premature_output(0),
        "unaccepted_output_on_final_input_edge": premature_output(92),
        "idle_nonzero_data": changed_sample(busy_edge, 6, 1),
        "idle_asserted_last": changed_sample(busy_edge, 7, 1),
        "unknown_idle_output": changed_sample(busy_edge, 6, "xxxxxxxx"),
        "unknown_control": changed_sample(busy_edge, 4, "x"),
        "busy_ready_without_transfer": changed_sample(busy_edge, 2, 1),
        "changed_unaccepted_input": changed_sample(1, 3, 0),
        "dropped_stalled_input_valid": changed_sample(1, 1, 0),
        "changed_unaccepted_output": changed_sample(first_stall, 6, 1),
        "dropped_stalled_valid": changed_sample(first_stall, 4, 0),
        "changed_stalled_last": changed_sample(first_stall, 7, 1),
        "dropped_sample": samples[:first_stall] + samples[first_stall + 1:],
        "duplicate_sample": samples[:first_stall] + samples[first_stall - 1:],
    }
    # These corruptions preserve every accepted output word, unlike a numerical
    # mutation. Only observation of unaccepted cycles can reject them.
    pin_rejections = {}
    for name, observed in pin_variants.items():
        try:
            compare_pin_runs(commands, [samples, observed, samples])
        except TransferMismatch as error:
            if "run=1" not in str(error):
                raise TransferMismatch("Pin rejection lost its run index") from error
            pin_rejections[name] = str(error)
        else:
            raise TransferMismatch("Insensitive public-pin fixture: " + name)
    return {
        "kind": "synthetic_transfer_checker_sensitivity",
        "physical_board_runs": 0, "baseline": baseline,
        "rejections": rejections,
        "synthetic_consecutive_runs": consecutive,
        "consecutive_run_rejections": run_rejections,
        "synthetic_bidirectional_runs": captured,
        "bidirectional_capture_rejections": capture_rejections,
        "synthetic_ordered_event_runs": ordered,
        "ordered_event_rejections": event_rejections,
        "synthetic_public_pin_runs": pins,
        "public_pin_rejections": pin_rejections,
    }
