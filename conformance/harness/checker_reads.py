"""A small real checker for judging the reference harness. Part of the conformance kit.

It reads the files the harness left in its directory and agrees when every
word the criteria ask for is in the work. Its last line is its answer.
"""
import pathlib

wanted = pathlib.Path("criteria").read_text(encoding="utf-8").split()
work = pathlib.Path("work").read_text(encoding="utf-8").split()
others = sorted(p.name for p in pathlib.Path(".").iterdir())
print("files I was given:", ", ".join(others))
print("agreed" if all(word in work for word in wanted) else "refused")
