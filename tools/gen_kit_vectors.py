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
import attest as signer  # noqa: E402
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
    # More refusals. Every set is checked, a pair is enough to be out of order, and a repeat anywhere is refused.
    more = []
    for name in ("specified_by", "targets", "closure", "declared", "mapping"):
        pair = canonical.sort_set([ident("code a"), ident("lib b")])
        descending = copy.deepcopy(base)
        descending["inputs"][name] = list(reversed(pair))
        more.append({"name": f"{name}: two members in descending order", "preimage": descending, "reason": "unsorted-set"})
        twice = copy.deepcopy(base)
        twice["inputs"][name] = [pair[0], pair[0]]
        more.append({"name": f"{name}: a member given twice", "preimage": twice, "reason": "unsorted-set"})
    null_platform = copy.deepcopy(base)
    null_platform["inputs"]["platform"] = None
    top_platform = dict(copy.deepcopy(base), platform={"os": "linux", "arch": "x86_64"})
    top_null = dict(copy.deepcopy(base), platform=None)
    more += [{"name": "a null platform inside the inputs is still a platform", "preimage": null_platform, "reason": "platform-in-core-key"},
             {"name": "a platform at the top level", "preimage": top_platform, "reason": "platform-in-core-key"},
             {"name": "a null platform at the top level", "preimage": top_null, "reason": "platform-in-core-key"},
             {"name": "a field at the top level that the definition does not have", "preimage": dict(copy.deepcopy(base), extra=1), "reason": "unknown-field"}]
    both_sorted = copy.deepcopy(base)
    for name in ("specified_by", "targets", "declared", "mapping"):
        both_sorted["inputs"][name] = canonical.sort_set([ident("code a"), ident("lib b")])
    put("conformance/vectors/core-key-more.json", {
        "about": "More vectors for the core key, in the format of core-key.json (conformance/README.md, Core keys). Every set in a preimage is checked, not only closure; two members in descending order are unsorted; a repeat in any set is refused; and a platform is refused at the top level as well as inside the inputs, null included. Any field at the top level that the preimage definition does not have is refused with the same reason as a platform, `platform-in-core-key`: there is one reason for both. `accept` holds one preimage with two members in every set, so a kernel that refuses every set of more than one member does not pass.",
        "accept": [{"name": "two sorted members in every set", "preimage": both_sorted, "core_key": canonical.identity(both_sorted)}],
        "reject": more})


# ------------------------------------------------------------------- acts
KEY_GOOD = "6b65792d666f722d7468652d6b69742d6f6e6c792d6e6f742d612d736563726574"
KEY_OTHER = "616e6f746865722d6b65792d7468652d706f6c6963792d646f65732d6e6f74"
POLICY = {"attestors": {"harness-1": KEY_GOOD},
          "makes": [["vendor-a/family-x", "vendor-a/family-x-small"], ["vendor-b/family-y"]]}
FIELDS = ["actor", "worker", "brief", "given", "fresh_context", "transcript", "known_bad"]
# What a check value must also cover before any level above helper is granted: what was judged, and how.
BIND = ["kind", "target", "result", "lineage"]


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


def attest(record: dict, key_hex: str = KEY_GOOD, key_id: str = "harness-1", covers=None, bind: bool = True, key: bytes | None = None) -> dict:
    """Sign with the reference signer's check value. `covers` is the fields the facts read; the four
    fields that bind what was judged are added unless `bind` is false. `key` gives the key as bytes,
    for keys that are not hexadecimal."""
    names = list(covers) if covers is not None else [f for f in FIELDS if f in record]
    covers = canonical.sort_set(names + (BIND if bind else []))
    mac = signer.check_value(record, covers, bytes.fromhex(key_hex) if key is None else key)
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
              # A covered field the record does not have is left out of what is signed; the value still verifies.
              (attest(act(known_bad=None, given=[g for g in full["given"] if not g["role"].startswith("known")]), covers=FIELDS),
               want("apart", "apart", "attested")),
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

    # ---- added after the second review of the kit (docs/reviews/2026-11-18-newer-scenarios.md).
    # Every expected value below was worked out by hand from conformance/README.md; only the check values are computed.
    TOP, HELP = want("cross-make", "cross-make", "attested"), want("helper", "cross-make", "declared")
    LOW, SELF = want("helper", "helper", "declared"), want("self", "self", "declared")
    bound = attest(full)
    scenario("a_vouched_act_is_bound_to_what_it_judged", "A check value must cover what was judged: the kind, the target, the result and the lineage. Signed without them the act is helper. Signed with them it earns its level, and changing any of the four afterwards breaks the value. Otherwise a vouched refusal could be copied as an agreement, or onto another target.", [],
             [(attest(full, bind=False), HELP),
              (bound, TOP),
              (dict(bound, result="refused"), HELP),
              (dict(bound, target=ident("another link")), HELP),
              (dict(bound, lineage=dict(full["lineage"], criterion="c2")), HELP),
              (dict(bound, kind="confirm-baseline"), HELP)]
             + [(attest(full, covers=FIELDS + [b for b in BIND if b != left_out], bind=False), HELP) for left_out in BIND])
    scenario("every_field_a_fact_reads_must_be_covered", "A fact is vouched for only if every field it reads is covered. Leaving out any one of worker, actor, brief, given or transcript holds the grade at helper, whatever else is signed.", [],
             [(attest(full, covers=[f for f in FIELDS if f != left_out]), HELP) for left_out in ["worker", "actor", "brief", "given", "transcript"]])
    wrong, right = full["known_bad"]["wrong"], full["known_bad"]["right"]
    swapped = [dict(g, content=right) if g["role"] == "known-wrong" else dict(g, content=wrong) if g["role"] == "known-right" else g for g in full["given"]]
    scenario("each_fact_at_its_edges", "Each fact with values the other scenarios never try: a brief from the owner, a brief from `other`, nothing given, freshness not stated, known cases from the kernel, a known-right case missing, the two known cases swapped, a worker whose make policy does not list, and a worker whose make names no family.", [],
             [(attest(act(brief=dict(full["brief"], issued_by="owner"))), TOP),
              (attest(act(brief=dict(full["brief"], issued_by="other"))), LOW),
              (attest(act(given=[])), LOW),
              (attest(act(fresh_context=None), covers=FIELDS), LOW),
              (attest(act(known_bad=dict(full["known_bad"], supplied_by="kernel"))), TOP),
              (attest(act(given=[g for g in full["given"] if g["role"] != "known-right"])), want("apart", "apart", "attested")),
              (attest(act(given=swapped)), want("apart", "apart", "attested")),
              (attest(act(worker=dict(full["worker"], make={"vendor": "vendor-z", "family": "unknown"}))), want("tested", "tested", "attested")),
              (attest(act(worker=dict(full["worker"], make={"vendor": "vendor-a"}))), want("tested", "tested", "attested"))])
    key = bytes.fromhex(KEY_GOOD)
    names = canonical.sort_set(FIELDS + BIND)
    backwards, repeated = list(reversed(names)), names + names[-1:]

    def signed_as(covers, mac):
        return dict(full, attestation={"harness": "harness-1", "key": "harness-1", "covers": covers, "mac": mac})
    good_mac = signer.check_value(full, names, key)
    scenario("the_check_value_is_exact", "The check value is over covers exactly as the record lists it, and covers must already be sorted with no repeat: a list in another order vouches for nothing, whether the value was made over that order or over the sorted one. The value is lowercase and is compared in full.", [],
             [(signed_as(names, good_mac), TOP),
              (signed_as(backwards, signer.check_value(full, backwards, key)), HELP),
              (signed_as(backwards, good_mac), HELP),
              (signed_as(repeated, signer.check_value(full, repeated, key)), HELP),
              (signed_as(repeated, good_mac), HELP),
              (signed_as(names, good_mac.upper()), HELP),
              (signed_as(names, good_mac[:32] + "0" * 32), HELP)])

    def broken(change, **how):
        record = copy.deepcopy(full)
        change(record)
        return attest(record, covers=FIELDS, **how)

    def bad_attestation(change):
        record = copy.deepcopy(bound)
        change(record["attestation"])
        return record
    scenario("a_record_that_fails_its_schema_is_self", "A malformed act record is graded self, whatever it claims and whoever signed it. One step for each way of being malformed that conformance/README.md lists. Every record here is otherwise the fully vouched one, so a kernel that does not look grades it higher.", [],
             [(broken(lambda r: r.pop("worker")), SELF),
              (broken(lambda r: r.pop("actor")), SELF),
              (broken(lambda r: r.update(actor="checker-7")), SELF),
              (broken(lambda r: r.update(worker=["worker-1"])), SELF),
              (broken(lambda r: r["actor"].update(id=1)), SELF),
              (broken(lambda r: r["worker"].update(id=2)), SELF),
              (broken(lambda r: r["actor"].pop("session")), SELF),
              (broken(lambda r: r["worker"].pop("session")), SELF),
              (broken(lambda r: r.update(brief="kernel")), SELF),
              (broken(lambda r: r.update(given={"role": "work", "content": ident("the work")})), SELF),
              (broken(lambda r: r["given"][0].pop("content")), SELF),
              (broken(lambda r: r["given"][0].update(role=1)), SELF),
              (broken(lambda r: r.update(fresh_context="true")), SELF),
              (broken(lambda r: r.update(transcript=None)), SELF),
              (broken(lambda r: r.update(known_bad=[])), SELF),
              (broken(lambda r: r["known_bad"].pop("wrong")), SELF),
              (broken(lambda r: r["known_bad"].update(rejected_wrong="true")), SELF),
              (bad_attestation(lambda a: a.update(covers=",".join(a["covers"]))), SELF),
              (bad_attestation(lambda a: a.pop("mac")), SELF),
              (bad_attestation(lambda a: a.update(key=1)), SELF),
              (dict(full, attestation="harness-1"), SELF),
              (broken(lambda r: r.update(kind=7)), SELF),
              (broken(lambda r: r.update(target=None)), SELF),
              (broken(lambda r: r.update(result=True)), SELF),
              (broken(lambda r: r.update(lineage=["0001", "c1"])), SELF)])
    not_a_key = "An attestor key that is not a non-empty, even-length string of lowercase hexadecimal digits names no key, and nothing is vouched for under it. "
    for name, policy_key, signing_keys, about in [
            ("empty", "", [b""], "Here the key is the empty string, and the record is signed with the empty key."),
            ("not_hex", "zz", [b"", b"zz"], "Here the key is `zz`, and the record is signed with the empty key and with those two characters as bytes."),
            ("odd_length", "abc", [bytes.fromhex("ab"), bytes.fromhex("0abc"), b"abc"], "Here the key is `abc`, and the record is signed with each key a lenient reader might make of it."),
            ("uppercase", KEY_GOOD.upper(), [key], "Here the key is the fixture key written in uppercase, and the record is signed with the fixture key.")]:
        put(f"conformance/kernel/acts/a_key_that_is_not_a_key_vouches_for_nothing_{name}.json", {
            "kind": "acts", "name": f"a_key_that_is_not_a_key_vouches_for_nothing_{name}", "claim": "C36", "covers": [], "why": not_a_key + about,
            "policy": dict(POLICY, attestors={"harness-1": policy_key}),
            "steps": [{"do": {"grade": attest(full, key=k)}, "expect": HELP} for k in signing_keys]})


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

    # More damage, each case as a whole file. The first three lines are the good ledger above.
    last, before = entries[-1]["identity"], entries[-2]["identity"]
    extra = {"previous": last, "kind": "evidence", "body": {"obligation": "ob-9", "verdict": "passed"}}
    payload = canonical.encode(extra)
    size, checksum = len(payload.encode("utf-8")), hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def made(text_of_payload: str) -> str:
        """A well-formed line around any payload text: the right length and checksum for it."""
        raw = text_of_payload.encode("utf-8")
        return f"dodona1 {len(raw)} {hashlib.sha256(raw).hexdigest()} {text_of_payload}\n"
    lines = [e["line"] for e in entries]
    corrupt = lambda at: {"refused": "corrupt", "at": at}  # noqa: E731
    note = {"previous": last, "kind": "note", "body": {"obligation": "ob-9", "verdict": "passed"}}
    cases = [
        ("a byte changed in the body of the last entry, the chain untouched", lines[0] + lines[1] + lines[2].replace('"verdict":"failed"', '"verdict":"passed"'), corrupt(3),
         "The payload is still canonical and nothing follows it, so only the checksum can notice."),
        ("a length that is not the payload's", text + f"dodona1 {size + 1} {checksum} {payload}\n", corrupt(4), "The checksum is right. Only the length is wrong."),
        ("a length with a leading zero", text + f"dodona1 0{size} {checksum} {payload}\n", corrupt(4), None),
        ("a length with a plus sign", text + f"dodona1 +{size} {checksum} {payload}\n", corrupt(4), None),
        ("a checksum in uppercase", text + f"dodona1 {size} {checksum.upper()} {payload}\n", corrupt(4), None),
        ("two spaces between fields", text + f"dodona1  {size}  {checksum}  {payload}\n", corrupt(4), None),
        ("two spaces after the format marker only", text + f"dodona1  {size} {checksum} {payload}\n", corrupt(4), None),
        ("two spaces after the length only", text + f"dodona1 {size}  {checksum} {payload}\n", corrupt(4), None),
        ("two spaces after the checksum only", text + f"dodona1 {size} {checksum}  {payload}\n", corrupt(4), "A reader that takes everything after the third space as the payload sees a payload that starts with a space: the length and the checksum no longer fit it."),
        ("a tab in place of a space", text + f"dodona1\t{size} {checksum} {payload}\n", corrupt(4), None),
        ("a space after the payload", text + f"dodona1 {size} {checksum} {payload} \n", corrupt(4), None),
        ("a byte-order mark before the first entry", "\ufeff" + text, corrupt(1), None),
        ("a blank line between entries", lines[0] + "\n" + lines[1] + lines[2], corrupt(2), None),
        ("a blank line at the end", text + "\n", corrupt(4), None),
        ("a file that is one line feed", "\n", corrupt(1), "An empty file has no entries. This one has a line, and the line is empty."),
        ("the last entry written twice", text + lines[2], corrupt(4), "The repeated line names the entry before the last as its previous."),
        ("an entry whose previous is the entry before the last", text + line(dict(extra, previous=before)), corrupt(4), None),
        ("the first entry removed", lines[1] + lines[2], corrupt(1), "The first entry of a ledger has previous null."),
        ("a later entry whose previous is null", text + line(dict(extra, previous=None)), corrupt(4), None),
        ("an entry with a fourth field", text + made(canonical.encode(dict(extra, extra=1))), corrupt(4), None),
        ("an entry with no body", text + made(canonical.encode({"previous": last, "kind": "evidence"})), corrupt(4), None),
        ("a payload that is null", text + made("null"), corrupt(4), None),
        ("a payload that is a list", text + made(canonical.encode([last, "evidence", {}])), corrupt(4), None),
        ("an entry whose kind is not a string", text + made(canonical.encode(dict(extra, kind=7))), corrupt(4), None),
        ("another format marker", text + f"dodona2 {size} {checksum} {payload}\n", corrupt(4), None),
        ("a final line ended by a carriage return alone", text + line(extra)[:-1] + "\r", {"torn": True, "entries": 3},
         "There is no line feed after it, so it is a torn ending like any other."),
        ("a well-formed entry of a kind the reader gives no meaning", text + line(note), {"torn": False, "entries": 4}, "A reader keeps entries of every kind.")]
    put("conformance/ledger/more-damage.json", {
        "about": "More damage for conformance/ledger/cases.json. Each case gives the whole file as text (UTF-8) and what protocol/ledger.md says `ledger-read` must answer. Where the answer is corrupt, `ledger-append` must answer corrupt too and leave the file as it was. `unlisted_kind` is an entry of a kind no rule gives a meaning: it is appended through the kernel, kept by the reader, and an append after it works. `bad_requests` are requests to `ledger-append`, given without the ledger's name, that must be answered {\"refused\": \"bad-request\"} with nothing written. Built with the reference encoder; no kernel produced any of it.",
        "damage": [dict({"name": n, "file": f, "expect": e}, **({"note": why} if why else {})) for n, f, e, why in cases],
        "unlisted_kind": {"append": {"kind": "note", "body": note["body"]}, "identity": canonical.identity(note), "file": text + line(note),
                          "then": {"append": {"kind": "evidence", "body": {"obligation": "ob-10", "verdict": "failed"}},
                                   "file": text + line(note) + line({"previous": canonical.identity(note), "kind": "evidence", "body": {"obligation": "ob-10", "verdict": "failed"}})}},
        "bad_requests": [{"name": "no kind", "request": {"body": {"obligation": "ob-9"}}},
                         {"name": "a kind that is a number", "request": {"kind": 7, "body": {"obligation": "ob-9"}}},
                         {"name": "a kind that is null", "request": {"kind": None, "body": {"obligation": "ob-9"}}},
                         {"name": "no body", "request": {"kind": "evidence"}}]})


# ---------------------------------------------------------------- status
def preimage(code: str, tool: str = "checker 1") -> dict:
    return {"obligation": ident("ob/" + code.split()[0]), "kind": "check",
            "inputs": {"specified_by": [ident("spec")], "targets": [ident(code)], "closure": canonical.sort_set([ident(code), ident("spec")]),
                       "tools": [{"name": "checker", "digest": ident(tool)}], "config": ident("bounds"), "expect": "holds"},
            "provider": {"name": "example.checker", "version": "1.0.0", "protocol": "0.2"}}


def evidence(name: str, pre: dict, verdict: str = "passed", writer: str = "kernel-a", platform: str = "p1", key=None, level=None) -> dict:
    body = {"obligation": name, "preimage": pre, "core_key": key or canonical.identity(pre),
            "platform": platform, "verdict": verdict, "writer": writer}
    if level is not None:
        body["level"] = level
    return {"append": {"kind": "evidence", "body": body}}


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
    def shown(level, criterion):
        return {"intents": {"i1": {"shown": {"level": level, "criterion": criterion}}}}
    scenario("the_headline_shows_the_weakest_link", "C24", "The level shown for an intent is the weakest of its criteria, and the report names which. A criterion with nothing passed behind it is none. A record that states no level is only asserted. Two passing records for the same inputs show the stronger. A soft criterion counts here too.",
             [(evidence("ob-a", A, level="bounded"), shown("none", "c2")),
              (evidence("ob-b", B, level="sampled"), shown("sampled", "c2")),
              (evidence("ob-b", B, level="proven"), shown("bounded", "c1")),
              (evidence("ob-a", A, level="proven", platform="p2"), shown("bounded", "c1")),
              (evidence("ob-a", A, level="proven"), shown("proven", "c1")),
              (evidence("ob-a", A, level="observed", platform="p2"), shown("proven", "c1")),
              (evidence("ob-a", A, verdict="failed", level="proven"), shown("none", "c1")),
              ({"change": {"obligation": "ob-a", "preimage": A2}}, shown("none", "c1")),
              (evidence("ob-a", A2), shown("asserted", "c1")),
              (evidence("ob-a", A2, level="made-up"), shown("asserted", "c1"))],
             intents={"i1": dict(intent, criteria={"c1": {"gate": "soft", "checked_by": ["ob-a"]}, "c2": {"gate": "hard", "checked_by": ["ob-b"]}})})

    def grant(actor="owner-1", result="agreed"):
        return {"append": {"kind": "act", "body": act(kind="grant-amendment", target=ident("loosen c1"), result=result,
                                                       lineage={"intent": "i1", "criterion": "c1", "kind": "grant-amendment"},
                                                       actor={"id": actor, "session": "s-" + actor}, worker={"id": "worker-1", "session": "s-100"},
                                                       known_bad=None, given=[{"role": "criteria", "content": ident("criteria")}])}}

    def exceptions(counted, below):
        return {"intents": {"i1": {"exceptions": {"counted": counted, "below_floor": below}}}}
    scenario("exceptions_are_in_the_headline", "C32", "Every exception asked for and agreed is in the report: counted if its owner granted it at or above the floor, and shown apart if not. One that was refused is not an exception. In these scenarios an exception changes no gate; it is only never hidden.",
             [(act_c, exceptions(0, 0)),
              (grant(), exceptions(1, 0)),
              (grant(actor="worker-1"), exceptions(1, 1)),
              (grant(actor="someone-else"), exceptions(1, 2)),
              (grant(result="refused"), exceptions(1, 2)),
              (grant(), exceptions(2, 2))],
             pol=dict(policy, floors=dict(policy["floors"], **{"grant-amendment": "helper"})))
    scenario("an_exception_below_the_floor_does_not_count", "C33", "With the floor at apart and nothing vouching for the grant, the owner's own exception is below the floor.",
             [(grant(), exceptions(0, 1))],
             pol=dict(policy, floors=dict(policy["floors"], **{"grant-amendment": "apart"})))
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


    # ---- added after the second review of the kit (docs/reviews/2026-11-18-newer-scenarios.md).
    # Every expected value below was worked out by hand from conformance/README.md; only identities and check values are computed.
    def sep(weakest, kind, apart, of=3):
        return {"weakest": weakest, "act": kind, "apart_or_better": apart, "of": of}

    def i1(**fields):
        return {"intents": {"i1": fields}}

    def added(record):
        return {"append": {"kind": "act", "body": record}}

    def mcheck(criterion, lineage_criterion=None, lineage_intent="i1", signed=True, result="agreed", kind="match-check", worker="worker-1"):
        record = act(kind=kind, target=link("i1", criterion, {"c1": "ob-a", "c2": "ob-b"}[criterion]), result=result,
                     lineage={"intent": lineage_intent, "criterion": lineage_criterion or criterion, "kind": kind},
                     worker={"id": worker, "session": "s-100", "make": {"vendor": "vendor-a", "family": "family-x"}})
        return added(attest(record) if signed else record)

    def one(obligation):
        return {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {"c1": {"gate": "hard", "checked_by": [obligation]}}}

    scenario("an_act_about_another_worker_is_self", "C36", "An act record whose worker is not the intent's worker is graded self for that intent, whoever vouches for it. A vouched match-check and a vouched confirmation about another worker count for nothing; the owner's plain confirmation about the right worker then confirms.",
             [(mcheck("c1", worker="worker-2"), i1(status="draft", separation=sep("self", "confirm-baseline", 0))),
              (added(attest(confirm("i1", dict(intent, worker="worker-2")))), i1(status="draft", separation=sep("self", "confirm-baseline", 0))),
              (act_c, i1(status="open", separation=sep("self", "match-check", 0)))])
    scenario("a_floor_above_helper_needs_a_vouched_confirmation", "C36", "With the confirmation floor at apart, a declared confirmation is reported at helper and confirms nothing. One vouched for at exactly apart confirms, and counts as apart or better.",
             [(act_c, i1(status="draft", separation=sep("self", "match-check", 0))),
              (added(attest(confirm("i1", intent))), i1(status="open", separation=sep("self", "match-check", 1)))],
             pol=dict(policy, floors={"confirm-baseline": "apart", "match-check": "self"}))
    unordered = {"owner": "owner-1", "worker": "worker-1", "children": ["k2", "k1"], "criteria": {"c1": {"gate": "hard", "checked_by": ["ob-b", "ob-a"]}}}
    in_order = {"owner": "owner-1", "worker": "worker-1", "children": ["k1", "k2"], "criteria": {"c1": {"gate": "hard", "checked_by": ["ob-a", "ob-b"]}}}
    scenario("a_baseline_is_the_same_in_any_order_and_every_check_must_pass", "C29", "Children and checked_by are sets: the baseline sorts them, so a confirmation of the sorted form confirms an intent that lists them in another order. A criterion checked by two obligations is met only when both passed.",
             [(added(confirm("i1", in_order)), i1(status="open", separation=sep("self", "match-check", 0), score={"met": 0, "of": 1})),
              (evidence("ob-a", A), dict(i1(status="open", score={"met": 0, "of": 1}), project={"status": "unknown"})),
              (evidence("ob-b", B), dict(i1(status="fulfilled", score={"met": 1, "of": 1}), project={"status": "passed"})),
              (evidence("ob-b", B, verdict="failed"), dict(i1(status="open", score={"met": 0, "of": 1}), project={"status": "failed"},
                                                           obligations={"ob-a": P, "ob-b": {"status": "conflict"}}))],
             intents={"i1": unordered})
    scenario("a_pairing_is_named_by_its_target", "C36", "A match-check counts for the pairing its target names: not when refused, not under another kind, not by the criterion its lineage mentions. The highest record counts, not the latest.",
             [(act_c, i1(status="open", separation=sep("self", "match-check", 0))),
              (mcheck("c1", result="refused"), i1(separation=sep("self", "match-check", 0))),
              (mcheck("c1", kind="confirm-baseline"), i1(separation=sep("self", "match-check", 0))),
              (mcheck("c2", lineage_criterion="c1"), i1(separation=sep("self", "match-check", 1))),
              (mcheck("c1", signed=False), i1(separation=sep("helper", "confirm-baseline", 1))),
              (mcheck("c2", signed=False), i1(separation=sep("helper", "confirm-baseline", 1)))])
    scenario("a_match_check_is_found_by_its_target_alone", "C36", "A match-check is found by its target and its lineage is not read: one whose lineage names another intent still counts for the pairing its target names. Two kernels disagreed here.",
             [(act_c, i1(separation=sep("self", "match-check", 0))),
              (mcheck("c1", lineage_intent="i9"), i1(separation=sep("self", "match-check", 1)))])
    scenario("a_confirmation_names_its_intent", "C29", "Two intents with the same baseline: a confirmation confirms only the one its lineage names.",
             [(added(confirm("i1", one("ob-a"))), {"intents": {"i1": {"status": "open"}, "i2": {"status": "draft"}}}),
              (added(confirm("i2", one("ob-a"))), {"intents": {"i1": {"status": "open"}, "i2": {"status": "open"}}})],
             intents={"i1": one("ob-a"), "i2": one("ob-a")}, pol=dict(policy, required=["i1", "i2"]))

    def record(name, pre, verdict="passed", writer="kernel-a", **more):
        return dict(evidence(name, pre, verdict=verdict, writer=writer)["append"]["body"], **more)

    def without(body, field):
        return {"append": {"kind": "evidence", "body": {k: v for k, v in body.items() if k != field}}}

    def both(a, b, rejected=0):
        return {"obligations": {"ob-a": a, "ob-b": b}, "rejected": rejected}
    scenario("which_records_count", "C18", "A record counts for the obligation it names and for no other with the same inputs, from this kernel or any trusted writer, and only if it states a writer and a platform. Entries of other kinds take part in nothing, not even the count of rejected records. Extra fields are ignored.",
             [(evidence("ob-a", A), both(P, U)),
              (evidence("ob-b", A, writer="kernel-c"), both(P, P)),
              ({"append": {"kind": "note", "body": record("ob-a", A, verdict="failed")}}, both(P, P)),
              ({"append": {"kind": "note", "body": record("ob-a", A, core_key="sha256:" + "0" * 64)}}, both(P, P)),
              (without(record("ob-a", A, verdict="failed"), "writer"), both(P, P)),
              (without(record("ob-a", A, verdict="failed"), "platform"), both(P, P)),
              ({"append": {"kind": "evidence", "body": record("ob-a", A, verdict="failed", note="x")}}, both({"status": "conflict"}, P))],
             obligations={"ob-a": {"preimage": A}, "ob-b": {"preimage": A}}, pol=dict(policy, trusted_writers=["kernel-b", "kernel-c"]))
    backwards = copy.deepcopy(A)
    backwards["inputs"]["closure"] = list(reversed(backwards["inputs"]["closure"]))
    with_platform = copy.deepcopy(A)
    with_platform["inputs"]["platform"] = {"os": "linux", "arch": "x86_64"}
    scenario("a_preimage_that_cannot_be_keyed_is_rejected", "C18", "A record whose preimage the core-key rules refuse is rejected even though its core_key is the identity of that preimage: a set out of order, and a platform among the inputs. Two kernels disagreed here.",
             [(evidence("ob-a", backwards), both(U, U, rejected=1)),
              (evidence("ob-b", with_platform), both(U, U, rejected=2))],
             obligations={"ob-a": {"preimage": backwards}, "ob-b": {"preimage": B}})
    C = preimage("code c")

    def three(a, b, project):
        return {"intents": {"i1": {"status": a}, "i2": {"status": b}}, "project": {"status": project}}
    scenario("project_status_reads_the_required_intents", "C32", "A failing gate of an intent that is not required fails nothing. Every required intent must be delivered, not just one. A failing hard gate of a required intent fails the project even while that intent is a draft.",
             [(evidence("ob-c", C, verdict="failed"), three("draft", "draft", "unknown")),
              (added(confirm("i1", one("ob-a"))), three("open", "draft", "unknown")),
              (evidence("ob-a", A), three("fulfilled", "draft", "unknown")),
              (evidence("ob-b", B, verdict="failed"), three("fulfilled", "draft", "failed"))],
             obligations={"ob-a": {"preimage": A}, "ob-b": {"preimage": B}, "ob-c": {"preimage": C}},
             intents={"i1": one("ob-a"), "i2": one("ob-b"), "i3": one("ob-c")}, pol=dict(policy, required=["i1", "i2"]))
    only_soft = {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {"c1": {"gate": "soft", "checked_by": []}}}
    soft_bare = {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {"c1": {"gate": "hard", "checked_by": ["ob-a"]}, "c2": {"gate": "soft", "checked_by": []}}}
    mixed = {"owner": "owner-1", "worker": "worker-1", "children": [],
             "criteria": {"c1": {"gate": "hard", "checked_by": ["ob-a"]}, "c2": {"gate": "deferred", "checked_by": ["ob-b"]}, "c3": {"gate": "soft", "checked_by": ["ob-a"]}}}
    scenario("uncovered_comes_first_and_soft_criteria_are_scored", "C30", "Uncovered is reported before unguarded, and for a criterion of any gate. Soft criteria are in the score. A failed deferred check leaves the intent delivered and the project passed.",
             [(added(confirm("i1", only_soft)), {"intents": {"i1": {"status": "uncovered", "gates": {"hard": 0, "soft": 1, "deferred": 0, "deferred_open": 0}, "score": {"met": 0, "of": 1}}}}),
              (added(confirm("i2", soft_bare)), {"intents": {"i2": {"status": "uncovered"}}}),
              (added(confirm("i3", mixed)), {"intents": {"i3": {"status": "open"}}}),
              (evidence("ob-a", A), {"intents": {"i3": {"status": "delivered", "score": {"met": 2, "of": 3}}, "i2": {"status": "uncovered", "score": {"met": 1, "of": 2}}}, "project": {"status": "passed"}}),
              (evidence("ob-b", B, verdict="failed"), {"intents": {"i3": {"status": "delivered", "gates": {"hard": 1, "soft": 1, "deferred": 1, "deferred_open": 1}, "score": {"met": 2, "of": 3}}}, "project": {"status": "passed"}})],
             intents={"i1": only_soft, "i2": soft_bare, "i3": mixed}, pol=dict(policy, required=["i3"]))
    still = {"obligations": {"ob-a": P, "ob-b": U}, "intents": {"i1": {"status": "draft", "gates": {"hard": 1, "soft": 0, "deferred": 1, "deferred_open": 1}, "score": {"met": 1, "of": 2}, "separation": sep0}},
             "project": {"status": "unknown"}, "rejected": 0}
    scenario("steps_with_nothing_to_act_on_change_nothing", "C29", "A step that names an obligation, intent or criterion that does not exist changes nothing. It does not create what it names.",
             [(evidence("ob-a", A), still),
              ({"change": {"obligation": "ob-z", "preimage": B}}, still),
              ({"set_gate": {"intent": "i9", "criterion": "c1", "to": "soft"}}, still),
              ({"set_gate": {"intent": "i1", "criterion": "c9", "to": "hard"}}, still)])
    scenario("the_match_check_floor_withholds_nothing", "C36", "The floor for match-check is read by no rule: a pairing below it is still reported at its level.",
             [(act_c, i1(separation=sep("self", "match-check", 0))),
              (mcheck("c1", signed=False), i1(separation=sep("self", "match-check", 0))),
              (mcheck("c2", signed=False), i1(separation=sep("helper", "confirm-baseline", 0)))],
             pol=dict(policy, floors={"confirm-baseline": "helper", "match-check": "apart"}))

    def nothing(status="draft"):
        return {"obligations": {"ob-a": U, "ob-b": U}, "rejected": 0, "intents": {"i1": {"status": status}}}
    whole = record("ob-a", A, verdict="failed")
    scenario("what_is_not_a_record_counts_for_nothing", "C18", "An evidence entry with a verdict that is neither passed nor failed, with a field missing, or with a body that is not an object, counts for nothing and is not counted as rejected either. An act with no actor is malformed and confirms nothing. The kernel answers every one of these steps and carries on: the last two steps are ordinary and must work.",
             [(evidence("ob-a", A, verdict="error"), nothing()),
              (evidence("ob-a", A, verdict="error", key=canonical.identity(A2)), nothing()),
              ({"append": {"kind": "evidence", "body": {}}}, nothing()),
              ({"append": {"kind": "evidence", "body": "passed"}}, nothing())]
             + [(without(whole, field), nothing()) for field in ("obligation", "platform", "writer", "core_key", "preimage")]
             # Not rejected either: with a wrong key these would be rejected if they were records. They are not records.
             + [(without(record("ob-a", A, core_key=canonical.identity(A2)), field), nothing()) for field in ("writer", "platform")]
             + [(added({k: v for k, v in confirm("i1", intent).items() if k != "actor"}), nothing()),
                (added([]), nothing()),
                (evidence("ob-a", A), {"obligations": {"ob-a": P, "ob-b": U}, "rejected": 0, "intents": {"i1": {"status": "draft"}}}),
                (act_c, {"obligations": {"ob-a": P, "ob-b": U}, "rejected": 0, "intents": {"i1": {"status": "delivered"}}, "project": {"status": "passed"}})])
    two_checks = {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {"c1": {"gate": "hard", "checked_by": ["ob-a", "ob-z"]}}}
    scenario("names_the_scenario_does_not_define", "C32", "An obligation that a criterion names and the scenario does not define is unknown, never run: the criterion is covered and not met. A required intent that the scenario does not define is not delivered, so the project is never passed; a failure elsewhere still fails it.",
             [(added(confirm("i1", one("ob-a"))), {"intents": {"i1": {"status": "open"}, "i2": {"status": "draft"}}, "project": {"status": "unknown"}}),
              (added(confirm("i2", two_checks)), {"intents": {"i1": {"status": "open"}, "i2": {"status": "open"}}, "project": {"status": "unknown"}}),
              (evidence("ob-a", A), {"obligations": {"ob-a": P}, "intents": {"i1": {"status": "fulfilled"}, "i2": {"status": "open", "score": {"met": 0, "of": 1}}}, "project": {"status": "unknown"}}),
              (evidence("ob-a", A, verdict="failed"), {"obligations": {"ob-a": {"status": "conflict"}}, "project": {"status": "failed"}})],
             obligations={"ob-a": {"preimage": A}}, intents={"i1": one("ob-a"), "i2": two_checks}, pol=dict(policy, required=["i1", "i9"]))
    empty = {"owner": "owner-1", "worker": "worker-1", "children": [], "criteria": {}}

    def levels(level, criterion):
        return {"intents": {"i1": {"shown": {"level": level, "criterion": criterion}}, "i2": {"shown": {"level": "none", "criterion": None}}}}
    scenario("a_stated_none_is_none_and_no_criteria_show_nothing", "C24", "A record that states the level none is taken at none: it is on the scale, so it is not raised to asserted. A stronger record for the same inputs then decides. An intent with no criteria shows none and names no criterion.",
             [(evidence("ob-a", A, level="none"), dict(levels("none", "c1"), obligations={"ob-a": P})),
              (evidence("ob-a", A, level="sampled"), levels("sampled", "c1"))],
             intents={"i1": one("ob-a"), "i2": empty}, obligations={"ob-a": {"preimage": A}})


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
