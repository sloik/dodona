"""Writes the kit data whose expected values need hashing or keyed checksums.

Stage-0 helper (decision 0023). The expected values in these files come from
the reference encoder in tools/canonical.py and Python's own hashing, never
from a kernel. Run it after changing what it describes; the repository checks
confirm the files on disk are what this script produces.

    python tools/gen_kit_vectors.py          # write the files
    python tools/gen_kit_vectors.py --check  # fail if they differ from what is on disk
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT: dict[str, str] = {}


def put(path: str, value) -> None:
    OUT[path] = json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def ident(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------- core keys
def core_keys() -> None:
    base = {"obligation": ident("ob/check-sort"), "kind": "check",
            "inputs": {"specified_by": [ident("spec a")], "targets": [ident("code a")],
                       "closure": canonical.sort_set([ident("code a"), ident("lib b"), ident("spec a")]),
                       "tools": [{"name": "checker", "digest": ident("checker 1")}],
                       "config": ident("bounds 3"), "expect": "holds"},
            "provider": {"name": "example.checker", "version": "1.0.0", "protocol": "0.2"}}
    accept = [("a plain check", base)]
    for name, change in [("the same with a different tool", lambda p: p["inputs"]["tools"].__setitem__(0, {"name": "checker", "digest": ident("checker 2")})),
                         ("the same expecting a violation", lambda p: p["inputs"].__setitem__("expect", "violated")),
                         ("the same from a newer provider", lambda p: p["provider"].__setitem__("version", "1.0.1")),
                         ("a conformance check with a mapping", lambda p: (p.__setitem__("kind", "conformance"), p["inputs"].__setitem__("mapping", [ident("map m")])))]:
        variant = copy.deepcopy(base)
        change(variant)
        accept.append((name, variant))
    unsorted = copy.deepcopy(base)
    unsorted["inputs"]["closure"] = list(reversed(unsorted["inputs"]["closure"]))
    repeated = copy.deepcopy(base)
    repeated["inputs"]["closure"] = base["inputs"]["closure"] + base["inputs"]["closure"][:1]
    with_platform = copy.deepcopy(base)
    with_platform["inputs"]["platform"] = {"os": "linux", "arch": "x86_64"}
    put("conformance/vectors/core-key.json", {
        "about": "The core key of an evidence record: the identity of exactly this object under the canonical encoding (protocol/evidence-record.schema.json, core_key_preimage). `accept` gives objects with their key. `reject` gives objects a kernel must refuse to key, with the reason: the arrays specified_by, targets, closure, declared and mapping are sets and must arrive sorted with no repeats, and the platform is not part of the core key.",
        "accept": [{"name": n, "preimage": p, "core_key": canonical.identity(p)} for n, p in accept],
        "reject": [{"name": "a set that is not sorted", "preimage": unsorted, "reason": "unsorted-set"},
                   {"name": "a set with a repeated member", "preimage": repeated, "reason": "unsorted-set"},
                   {"name": "a platform inside the core key", "preimage": with_platform, "reason": "platform-in-core-key"}]})


# ------------------------------------------------------------------- acts
KEY_GOOD = "6b65792d666f722d7468652d6b69742d6f6e6c792d6e6f742d612d736563726574"
KEY_OTHER = "616e6f746865722d6b65792d7468652d706f6c6963792d646f65732d6e6f74"
POLICY = {"attestors": {"harness-1": KEY_GOOD},
          "makes": [["vendor-a/family-x", "vendor-a/family-x-small"], ["vendor-b/family-y"]]}
FIELDS = ["actor", "worker", "brief", "given", "fresh_context", "transcript", "known_bad"]


def act(**changes) -> dict:
    wrong, right = ident("a wrong answer"), ident("a right answer")
    record = {"ticket": "t-1", "kind": "match-check", "target": ident("the link judged"),
              "lineage": {"intent": "0001", "criterion": "c1", "kind": "match-check"},
              "result": "agreed",
              "actor": {"id": "checker-7", "session": "s-900", "started_by": "harness-1",
                        "make": {"vendor": "vendor-b", "family": "family-y"}},
              "worker": {"id": "worker-1", "session": "s-100", "make": {"vendor": "vendor-a", "family": "family-x"}},
              "brief": {"issued_by": "kernel", "content": ident("the brief")},
              "given": [{"role": "brief", "content": ident("the brief")}, {"role": "criteria", "content": ident("criteria")},
                        {"role": "known-right", "content": right}, {"role": "known-wrong", "content": wrong},
                        {"role": "work", "content": ident("the work")}],
              "fresh_context": True, "transcript": ident("transcript"),
              "known_bad": {"wrong": wrong, "right": right, "supplied_by": "owner", "criterion": "c1",
                            "rejected_wrong": True, "accepted_right": True}}
    for key, value in changes.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    return record


def attest(record: dict, key_hex: str = KEY_GOOD, key_id: str = "harness-1", covers=None) -> dict:
    covers = canonical.sort_set(covers if covers is not None else [f for f in FIELDS if f in record])
    message = canonical.encode({"covers": covers, "fields": {f: record[f] for f in covers}})
    mac = hmac.new(bytes.fromhex(key_hex), message.encode("utf-8"), hashlib.sha256).hexdigest()
    out = dict(record)
    out["attestation"] = {"harness": "harness-1", "key": key_id, "covers": covers, "mac": mac}
    return out


def acts() -> None:
    def scenario(name, why, covers, steps):
        put(f"conformance/kernel/acts/{name}.json", {
            "kind": "acts", "name": name, "claim": "C36", "covers": covers, "why": why, "policy": POLICY,
            "steps": [{"do": {"grade": record}, "expect": expect} for record, expect in steps]})

    def want(level, claims, source):
        return {"level": level, "claims": claims, "source": source}

    full = act()
    scenario("attested_facts_earn_their_level", "With every fact vouched for by a harness the policy names, the act earns the level its facts support.", [],
             [(attest(full), want("cross-make", "cross-make", "attested")),
              (attest(act(known_bad=None, given=[g for g in full["given"] if not g["role"].startswith("known")])),
               want("apart", "apart", "attested")),
              (attest(act(actor=dict(full["actor"], make={"vendor": "vendor-a", "family": "family-x-small"}))),
               want("tested", "tested", "attested")),
              (attest(act(actor=dict(full["actor"], make={"vendor": "vendor-z", "family": "unknown"}))),
               want("tested", "tested", "attested"))])
    scenario("a_claim_alone_earns_helper", "The same facts with nobody vouching for them are a claim. The claim is shown and the grade is helper.", [],
             [(full, want("helper", "cross-make", "declared")),
              (act(known_bad=None, given=[g for g in full["given"] if not g["role"].startswith("known")]),
               want("helper", "apart", "declared"))])
    tampered = attest(act(fresh_context=False))
    tampered["fresh_context"] = True
    scenario("a_bad_signature_is_no_signature", "A signature made with a key the policy does not list, under a key name it does not know, or over something that was changed afterwards, vouches for nothing.", [],
             [(attest(full, key_hex=KEY_OTHER), want("helper", "cross-make", "declared")),
              (attest(full, key_id="harness-9"), want("helper", "cross-make", "declared")),
              (tampered, want("helper", "cross-make", "declared")),
              (dict(attest(full), attestation=dict(attest(full)["attestation"], mac="00" * 32)), want("helper", "cross-make", "declared"))])
    scenario("only_covered_facts_are_vouched_for", "A harness vouches only for the fields it signed. A level needs every fact below it vouched for, so one uncovered fact holds the grade down.", [],
             [(attest(full, covers=[f for f in FIELDS if f != "fresh_context"]), want("helper", "cross-make", "declared")),
              (attest(full, covers=[f for f in FIELDS if f != "known_bad"]), want("apart", "cross-make", "attested")),
              (attest(full, covers=["actor", "worker"]), want("helper", "cross-make", "declared"))])
    scenario("the_worker_is_never_separate", "An act by the worker, or by something the worker started, briefed or fed, is self or helper whoever signs it.", [],
             [(attest(act(actor=dict(full["actor"], id="worker-1"))), want("self", "self", "declared")),
              (attest(act(actor=dict(full["actor"], session="s-100"))), want("self", "self", "declared")),
              (attest(act(actor=dict(full["actor"], started_by="worker-1"))), want("helper", "helper", "declared")),
              (attest(act(actor={k: v for k, v in full["actor"].items() if k != "started_by"})), want("helper", "helper", "declared")),
              (attest(act(brief=dict(full["brief"], issued_by="worker"))), want("helper", "helper", "declared")),
              (attest(act(given=full["given"] + [{"role": "other", "content": ident("worker notes")}])), want("helper", "helper", "declared")),
              (attest(act(fresh_context=False)), want("helper", "helper", "declared")),
              (attest(act(transcript=None)), want("helper", "helper", "declared"))])
    scenario("tested_needs_a_real_test", "The known-wrong and known-right cases must come from the owner or the kernel, must be among what the checker was given, and the checker must tell them apart.", [],
             [(attest(act(known_bad=dict(full["known_bad"], supplied_by="worker"))), want("apart", "apart", "attested")),
              (attest(act(known_bad=dict(full["known_bad"], rejected_wrong=False))), want("apart", "apart", "attested")),
              (attest(act(known_bad=dict(full["known_bad"], accepted_right=False))), want("apart", "apart", "attested")),
              (attest(act(known_bad=dict(full["known_bad"], wrong=ident("something else")))), want("apart", "apart", "attested"))])


# ---------------------------------------------------------------- ledger
def line(entry: dict) -> str:
    payload = canonical.encode(entry)
    raw = payload.encode("utf-8")
    return f"dodona1 {len(raw)} {hashlib.sha256(raw).hexdigest()} {payload}\n"


def ledger() -> None:
    bodies = [("evidence", {"obligation": "ob-1", "verdict": "passed", "note": "zażółć"}),
              ("act", {"kind": "confirm-baseline", "ticket": "t-1"}),
              ("evidence", {"obligation": "ob-2", "verdict": "failed", "n": 3})]
    entries, previous, text = [], None, ""
    for kind, body in bodies:
        entry = {"previous": previous, "kind": kind, "body": body}
        previous = canonical.identity(entry)
        entries.append({"entry": entry, "identity": previous, "line": line(entry)})
        text += line(entry)
    put("conformance/ledger/cases.json", {
        "about": "A ledger of three entries, as the exact bytes a kernel must write (protocol/ledger.md), with each entry's identity. tools/run_ledger_cases.py appends these entries through the kernel and requires the file to be these bytes; then it damages the file in each of the ways listed and requires the reader to say what protocol/ledger.md says. The bytes were produced by the reference encoder, not by a kernel.",
        "append": [{"kind": k, "body": b} for k, b in bodies],
        "entries": entries,
        "file": text,
        "damage": [
            {"name": "torn at every byte of the last entry", "how": "truncate-last-entry-at-every-byte", "expect": {"torn": True, "entries": 2}},
            {"name": "last entry removed cleanly", "how": "drop-last-line", "expect": {"torn": False, "entries": 2}},
            {"name": "a byte changed in the second entry", "how": "flip-byte-in-line-2", "expect": {"refused": "corrupt", "at": 2}},
            {"name": "a byte changed in the last entry, line feed kept", "how": "flip-byte-in-line-3", "expect": {"refused": "corrupt", "at": 3}},
            {"name": "the second entry removed", "how": "drop-line-2", "expect": {"refused": "corrupt", "at": 2}},
            {"name": "the first two entries swapped", "how": "swap-lines-1-2", "expect": {"refused": "corrupt", "at": 1}},
            {"name": "a line that is not an entry added", "how": "append-garbage-line", "expect": {"refused": "corrupt", "at": 4}},
            {"name": "a carriage return before a line feed", "how": "crlf-line-1", "expect": {"refused": "corrupt", "at": 1}},
            {"name": "a well-formed entry that names the wrong previous entry", "how": "append-entry-with-wrong-previous", "expect": {"refused": "corrupt", "at": 4}},
            {"name": "a well-formed entry whose payload is not in canonical form", "how": "append-entry-not-canonical", "expect": {"refused": "corrupt", "at": 4}},
            {"name": "a well-formed entry appended by hand", "how": "append-entry-by-hand", "expect": {"torn": False, "entries": 4},
             "note": "The file's own checks cannot tell who wrote an entry. Whether it counts is decided by its content."}]})


# ---------------------------------------------------------------- status
def preimage(code: str, tool: str = "checker 1") -> dict:
    return {"obligation": ident("ob/" + code.split()[0]), "kind": "check",
            "inputs": {"specified_by": [ident("spec")], "targets": [ident(code)], "closure": canonical.sort_set([ident(code), ident("spec")]),
                       "tools": [{"name": "checker", "digest": ident(tool)}], "config": ident("bounds"), "expect": "holds"},
            "provider": {"name": "example.checker", "version": "1.0.0", "protocol": "0.2"}}


def evidence(name: str, pre: dict, verdict: str = "passed", writer: str = "kernel-a", platform: str = "p1", key=None) -> dict:
    return {"append": {"kind": "evidence", "body": {"obligation": name, "preimage": pre, "core_key": key or canonical.identity(pre),
                                                    "platform": platform, "verdict": verdict, "writer": writer}}}


def baseline(intent: dict) -> str:
    return canonical.identity({"owner": intent["owner"], "children": canonical.sort_set(intent.get("children", [])),
                               "criteria": {c: {"gate": v["gate"], "checked_by": canonical.sort_set(v["checked_by"])}
                                            for c, v in intent["criteria"].items()}})


def link(intent_id: str, criterion: str, obligation: str) -> str:
    return canonical.identity({"intent": intent_id, "criterion": criterion, "obligation": obligation})


def confirm(intent_id: str, intent: dict, actor: str = None, **changes) -> dict:
    record = act(kind="confirm-baseline", target=baseline(intent),
                 lineage={"intent": intent_id, "kind": "confirm-baseline"},
                 actor={"id": actor or intent["owner"], "session": "s-owner", "started_by": "harness-1"},
                 worker={"id": intent["worker"], "session": "s-100"}, known_bad=None,
                 given=[{"role": "criteria", "content": ident("criteria")}], **changes)
    return record


def status() -> None:
    A, B = preimage("code a"), preimage("code b")
    A2 = preimage("code a2")
    intent = {"owner": "owner-1", "worker": "worker-1", "children": [],
              "criteria": {"c1": {"gate": "hard", "checked_by": ["ob-a"]}, "c2": {"gate": "deferred", "checked_by": ["ob-b"]}}}
    policy = {"min_hard_gates": 1, "required": ["i1"], "trusted_writers": [],
              "floors": {"confirm-baseline": "helper", "match-check": "self"},
              "attestors": POLICY["attestors"], "makes": POLICY["makes"]}

    def scenario(name, claim, why, steps, intents=None, pol=None, obligations=None):
        put(f"conformance/kernel/status/{name}.json", {
            "kind": "status", "name": name, "claim": claim, "covers": [], "why": why,
            "self": {"writer": "kernel-a", "platform": "p1"}, "policy": pol or policy,
            "obligations": obligations or {"ob-a": {"preimage": A}, "ob-b": {"preimage": B}},
            "intents": intents or {"i1": intent},
            "steps": [{"do": d, "expect": e} for d, e in steps]})

    U = {"status": "unknown", "reason": "never-run"}
    P, F = {"status": "passed"}, {"status": "failed"}
    act_c = {"append": {"kind": "act", "body": confirm("i1", intent)}}
    sep0 = {"weakest": "self", "act": "confirm-baseline", "apart_or_better": 0, "of": 3}
    sep1 = {"weakest": "self", "act": "match-check", "apart_or_better": 0, "of": 3}
    scenario("nothing_confirmed_is_a_draft", "C29", "Checks can pass and the intent is still a draft until its owner confirms it. Nothing is reported as passing.",
             [(evidence("ob-a", A), {"obligations": {"ob-a": P, "ob-b": U}, "intents": {"i1": {"status": "draft", "gates": {"hard": 1, "soft": 0, "deferred": 1, "deferred_open": 1}, "score": {"met": 1, "of": 2}, "separation": sep0}}, "project": {"status": "unknown"}, "rejected": 0}),
              (evidence("ob-b", B), {"intents": {"i1": {"status": "draft", "score": {"met": 2, "of": 2}}}, "project": {"status": "unknown"}})])
    scenario("confirmed_and_shown_is_delivered_then_fulfilled", "C32", "Confirmed by its owner, with the hard gate passing, the intent is delivered; when the deferred gate closes it is fulfilled. The count of separate acts is out of the acts there must be, and the missing ones count as self.",
             [(act_c, {"intents": {"i1": {"status": "open", "separation": sep1}}, "project": {"status": "unknown"}}),
              (evidence("ob-a", A), {"intents": {"i1": {"status": "delivered", "gates": {"deferred_open": 1}, "score": {"met": 1, "of": 2}}}, "project": {"status": "passed"}}),
              (evidence("ob-b", B), {"intents": {"i1": {"status": "fulfilled", "gates": {"deferred_open": 0}, "score": {"met": 2, "of": 2}}}, "project": {"status": "passed"}})])
    own = dict(intent, owner="worker-1")
    scenario("the_worker_cannot_confirm_its_own_intent", "C25", "Where the owner of the intent is also the worker, the confirmation is at self, below the floor, and the intent stays a draft.",
             [({"append": {"kind": "act", "body": confirm("i1", own)}}, {"intents": {"i1": {"status": "draft"}}}),
              (evidence("ob-a", A), {"intents": {"i1": {"status": "draft"}}, "project": {"status": "unknown"}})],
             intents={"i1": own})
    scenario("confirmation_is_of_one_exact_baseline", "C29", "A confirmation names what was confirmed. By someone who is not the owner, or of something else, or refused, it confirms nothing; and editing a gate afterwards makes the intent a draft again until the new baseline is confirmed.",
             [({"append": {"kind": "act", "body": confirm("i1", intent, actor="someone-else")}}, {"intents": {"i1": {"status": "draft"}}}),
              ({"append": {"kind": "act", "body": confirm("i1", dict(intent, owner="owner-1", children=["i9"]))}}, {"intents": {"i1": {"status": "draft"}}}),
              ({"append": {"kind": "act", "body": confirm("i1", intent, result="refused")}}, {"intents": {"i1": {"status": "draft"}}}),
              (act_c, {"intents": {"i1": {"status": "open"}}}),
              ({"set_gate": {"intent": "i1", "criterion": "c2", "to": "soft"}}, {"intents": {"i1": {"status": "draft", "gates": {"hard": 1, "soft": 1, "deferred": 0, "deferred_open": 0}}}}),
              ({"append": {"kind": "act", "body": confirm("i1", {**intent, "criteria": {**intent["criteria"], "c2": {"gate": "soft", "checked_by": ["ob-b"]}}})}}, {"intents": {"i1": {"status": "open"}}}),
              ({"set_gate": {"intent": "i1", "criterion": "c2", "to": "deferred"}}, {"intents": {"i1": {"status": "open"}}})])
    scenario("evidence_counts_only_for_the_inputs_it_states", "C18", "A record counts for the inputs it was made from, and only if its key really is the key of the inputs it states. A record with the wrong key is rejected and counted as rejected, whoever wrote it.",
             [(evidence("ob-a", A2), {"obligations": {"ob-a": U}, "rejected": 0}),
              (evidence("ob-a", A, key=canonical.identity(A2)), {"obligations": {"ob-a": U}, "rejected": 1}),
              (evidence("ob-a", A2, key=canonical.identity(A)), {"obligations": {"ob-a": U}, "rejected": 2}),
              (evidence("ob-a", A), {"obligations": {"ob-a": P}, "rejected": 2}),
              ({"change": {"obligation": "ob-a", "preimage": A2}}, {"obligations": {"ob-a": P}}),
              ({"change": {"obligation": "ob-a", "preimage": preimage("code a3")}}, {"obligations": {"ob-a": U}}),
              ({"change": {"obligation": "ob-a", "preimage": A}}, {"obligations": {"ob-a": P}})])
    scenario("records_from_elsewhere_do_not_count", "C18", "A record written by another kernel, or on another platform, is not this kernel's evidence. It is not rejected as damaged; it simply does not count.",
             [(evidence("ob-a", A, writer="kernel-b"), {"obligations": {"ob-a": U}, "rejected": 0}),
              (evidence("ob-a", A, platform="p2"), {"obligations": {"ob-a": U}, "rejected": 0}),
              (evidence("ob-a", A, verdict="failed"), {"obligations": {"ob-a": F}})])
    scenario("a_writer_policy_names_is_accepted", "C18", "Policy can name another writer whose records count.",
             [(evidence("ob-a", A, writer="kernel-b"), {"obligations": {"ob-a": P}}),
              (evidence("ob-a", A, writer="kernel-c"), {"obligations": {"ob-a": P}}),
              (evidence("ob-a", A, writer="kernel-c", verdict="failed"), {"obligations": {"ob-a": P}}),
              (evidence("ob-a", A, writer="kernel-b", verdict="failed"), {"obligations": {"ob-a": {"status": "conflict"}}})],
             pol=dict(policy, trusted_writers=["kernel-b"]))
    scenario("a_failing_hard_gate_fails_the_project", "C32", "A failure or a conflict behind a hard gate of a required intent makes the project failed, not merely unknown. A failure behind a deferred gate does not.",
             [(act_c, {"project": {"status": "unknown"}}),
              (evidence("ob-b", B, verdict="failed"), {"intents": {"i1": {"status": "open"}}, "project": {"status": "unknown"}}),
              (evidence("ob-a", A, verdict="failed"), {"intents": {"i1": {"status": "open"}}, "project": {"status": "failed"}}),
              (evidence("ob-a", A), {"obligations": {"ob-a": {"status": "conflict"}}, "intents": {"i1": {"status": "open"}}, "project": {"status": "failed"}})])
    scenario("nothing_required_is_never_a_pass", "C32", "A project whose policy requires nothing is reported as requiring nothing, whatever has been delivered.",
             [(act_c, {"project": {"status": "nothing-required"}}),
              (evidence("ob-a", A), {"intents": {"i1": {"status": "delivered"}}, "project": {"status": "nothing-required"}})],
             pol=dict(policy, required=[]))
    bare = {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {"c1": {"gate": "hard", "checked_by": []}}}
    soft = {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {"c1": {"gate": "soft", "checked_by": ["ob-a"]}}}
    late = {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {"c1": {"gate": "hard", "checked_by": ["ob-a"]}, "c2": {"gate": "deferred", "checked_by": []}}}
    scenario("nothing_checked_is_nothing_met", "C30", "A criterion that nothing checks is not met, and a deferred one is still open. Found by running status on a real project: every uncovered criterion was being counted as met.",
             [(evidence("ob-a", A), {"intents": {"i1": {"status": "draft", "gates": {"hard": 1, "soft": 0, "deferred": 1, "deferred_open": 1}, "score": {"met": 1, "of": 2}},
                                                 "i2": {"status": "draft", "score": {"met": 0, "of": 1}}}})],
             intents={"i1": late, "i2": bare}, pol=dict(policy, required=["i1", "i2"]))
    scenario("uncovered_and_unguarded", "C30", "A criterion with no check is uncovered. An intent with no hard gate is unguarded. Neither is ever delivered, confirmed or not.",
             [({"append": {"kind": "act", "body": confirm("i1", bare)}}, {"intents": {"i1": {"status": "uncovered"}, "i2": {"status": "draft"}}}),
              ({"append": {"kind": "act", "body": confirm("i2", soft)}}, {"intents": {"i2": {"status": "unguarded"}}}),
              (evidence("ob-a", A), {"intents": {"i1": {"status": "uncovered"}, "i2": {"status": "unguarded"}}, "project": {"status": "unknown"}})],
             intents={"i1": bare, "i2": soft}, pol=dict(policy, required=["i1", "i2"]))
    match = act(kind="match-check", target=link("i1", "c1", "ob-a"), lineage={"intent": "i1", "criterion": "c1", "kind": "match-check"},
                worker={"id": "worker-1", "session": "s-100", "make": {"vendor": "vendor-a", "family": "family-x"}})
    scenario("vouched_for_acts_are_counted_as_separate", "C36", "The count of separate acts rises only for acts a named harness vouches for. A claim alone is helper, and an act for some other link is not this link's act.",
             [(act_c, {"intents": {"i1": {"separation": sep1}}}),
              ({"append": {"kind": "act", "body": match}}, {"intents": {"i1": {"separation": {"weakest": "self", "act": "match-check", "apart_or_better": 0, "of": 3}}}}),
              ({"append": {"kind": "act", "body": attest(match)}}, {"intents": {"i1": {"separation": {"weakest": "self", "act": "match-check", "apart_or_better": 1, "of": 3}}}}),
              ({"append": {"kind": "act", "body": attest(dict(match, target=link("i1", "c2", "ob-b"), lineage={"intent": "i1", "criterion": "c2", "kind": "match-check"}))}},
               {"intents": {"i1": {"separation": {"weakest": "helper", "act": "confirm-baseline", "apart_or_better": 2, "of": 3}}}}),
              ({"append": {"kind": "act", "body": attest(dict(match, target=link("i1", "c9", "ob-z")))}}, {"intents": {"i1": {"separation": {"apart_or_better": 2, "of": 3}}}})])


def main() -> int:
    core_keys()
    acts()
    ledger()
    status()
    check = "--check" in sys.argv
    stale = []
    for path, text in OUT.items():
        target = ROOT / path
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(path)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    if check and stale:
        print("these files are not what tools/gen_kit_vectors.py produces:", ", ".join(stale))
        return 1
    print(f"{len(OUT)} files {'checked' if check else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
