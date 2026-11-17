# Path check

Draft **0.1**. Every path dodona handles, in configuration, in the lock, in messages and in the index of a project, passes this check. A path is accepted on every platform or on none, so a project that works on one system cannot be broken by being checked out on another.

The check is a pure function of the path. It never looks at a file system.

## Checking one path

A path is a sequence of bytes. The rules are applied in this order, and the reason reported is the first rule broken.

| # | Rule | Reason |
|---|---|---|
| 1 | The bytes are valid UTF-8 | `not-utf8` |
| 2 | The path is not empty | `empty` |
| 3 | The whole path is at most 200 bytes | `too-long` |
| 4 | Splitting on `/`, no segment is empty. So no leading slash, no trailing slash, no doubled slash | `empty-segment` |
| 5 | No segment is `.` or `..` | `dot-segment` |
| 6 | No segment is longer than 100 bytes | `segment-too-long` |
| 7 | The path contains none of: characters U+0000 to U+001F, U+007F, and `\` `:` `*` `?` `"` `<` `>` `\|` | `forbidden-character` |
| 8 | No segment ends with a dot or a space | `trailing-dot-or-space` |
| 9 | No segment starts with a space | `leading-space` |
| 10 | No segment is a reserved device name. Take the segment up to its first dot, ignoring case: it must not be `CON`, `PRN`, `AUX`, `NUL`, or `COM` or `LPT` followed by one of `0` to `9`, `¹`, `²`, `³` | `reserved-name` |
| 11 | The path is in Unicode Normalization Form C. A path that is not is refused, never normalised | `not-nfc` |
| 12 | Every character is assigned in the pinned Unicode version | `unassigned-character` |

Rules 7 to 10 exist because some supported platform cannot store such a name, or silently stores a different one.

## Checking a set of paths

Within one project, no two paths may be equal when case is ignored. Two paths collide when they are equal after this folding: normalise to NFD, apply Unicode full case folding, normalise to NFD again. This is Unicode's canonical caseless match.

A collision is reported with reason `case-collision` and names both paths.

## Unicode version

Rules 11 and the folding depend on Unicode's tables. The version is pinned so that every implementation agrees: **Unicode 15.1**. That is why rule 12 refuses a code point not assigned in that version. Raising the version is a change to this document and to the vectors.

## What is not a path

Symbolic links and similar indirections inside a project are refused when a project is indexed, by a separate rule. File modes never take part in identity.

## Test vectors

[`conformance/vectors/paths.json`](../conformance/vectors/paths.json) holds paths that must be accepted, paths that must be refused with the exact reason, byte sequences that are not UTF-8, and sets of paths with whether they collide. Hostile names are stored there as data and never as real files, so the vectors can be checked out on every platform.

The expected results in the vectors were written by hand from the rules above, not produced by a program.
