# Canonical encoding

Draft **0.1**. Used wherever dodona hashes a structured value: evidence keys, record identities, intent identities. Two implementations in different languages must produce the same bytes for the same value, on every platform.

dodona does not invent an encoding. It uses the **JSON Canonicalization Scheme, RFC 8785**, with one restriction.

## The rules

1. The value is JSON: objects, arrays, strings, integers, `true`, `false`, `null`.
2. **Integers only.** A number must be an integer from −9007199254740991 to 9007199254740991 inclusive, written without a fraction or an exponent. `1.0` and `1e3` are refused, not rounded. Anything that needs a fraction is carried as a string or as two integers.
3. Object keys are unique. A repeated key is refused.
4. Object members are written in order of their keys, compared as sequences of UTF-16 code units, which is the order RFC 8785 defines. For ASCII keys this is plain byte order. It differs from code-point order only for characters outside the Basic Multilingual Plane, and the test vectors include such a case.
5. No whitespace between tokens.
6. Strings are written as RFC 8785 says: `"` and `\` are escaped with a backslash; backspace, tab, line feed, form feed and carriage return use their two-character escapes; other characters below U+0020 are written as `\u` and four lowercase hexadecimal digits; everything else, including `/`, U+007F and all non-ASCII text, is written as itself in UTF-8.
7. A string must be valid Unicode. A lone surrogate is refused.
8. The identity of a value is `sha256:` followed by the lowercase hexadecimal SHA-256 of the UTF-8 bytes of its canonical text.

A list that represents a set is sorted before encoding, by the same UTF-16 code-unit order, with duplicates removed. Whether a list is a set is stated by the schema of the field, never guessed.

Strings are not normalised by the encoding. Two strings that look the same and differ in Unicode normalisation are different values. Paths are the one place where normalisation is required, and it is the [path check](path-check.md) that requires it.

## Why this standard

It is published, small, and has existing implementations in most languages. Its number rules are the complicated part, and restricting dodona to integers removes them.

## Test vectors

[`conformance/vectors/canonical.json`](../conformance/vectors/canonical.json) holds values with their exact canonical text and hash, and texts that must be refused with the reason. The expected values were produced by one implementation and confirmed by a second, independent one in another language, before any kernel existed.

Reasons for refusal: `not-json`, `not-an-integer`, `integer-out-of-range`, `duplicate-key`, `invalid-string`.
