# The digest of a tool tree

A tool is pinned as a whole tree of files, not as one file ([decision 0008](../decisions/0008-reproducibility-levels.md)). This is how the digest of a tree is computed, so that two implementations on two platforms get the same answer for the same tree.

## The listing

A tree is described by a **listing**: one item for each file and each symbolic link in it, at any depth. Directories are not listed; an empty directory is not part of a tree.

| Field | Meaning |
|---|---|
| `path` | The path inside the tree, relative, with `/`, passing the [path check](path-check.md) |
| `kind` | `file`, `program` (a file the owner may execute) or `link` (a symbolic link) |
| `identity` | For `file` and `program`: `sha256:` and the hash of the bytes. Absent for a link |
| `target` | For `link`: the link's text exactly as stored. Absent otherwise |

The items are sorted by `path`, as the [canonical encoding](canonical-encoding.md) sorts keys.

## The digest

The digest of the tree is `sha256:` and the hash of the canonical encoding of `{"tree": 1, "items": [...]}` with the items in that order.

## What makes a tree unusable

A tree is refused, and has no digest, if:

- a path fails the path check, or two paths are the same after the comparison the path check uses for collisions;
- a link's target is absolute, or leads outside the tree when followed from where the link is;
- it contains anything that is not a regular file or a symbolic link (a device, a socket, a named pipe);
- it is empty.

## What is left out, on purpose

Owner, group, timestamps and permission bits other than "the owner may execute" take no part. On a platform with no such bit, `kind` comes from the listing the tree was pinned with, not from the file system.

## Vectors

`conformance/vectors/tool-tree.json` holds listings with their digests, and listings that must be refused with the reason. `tools/tooltree.py` is the reference; the repository checks confirm it agrees with the vectors. No kernel computes this yet, and the site's pins still name single files ([decision 0026](../decisions/0026-the-first-host-and-status-are-stage-0-helpers.md)).
