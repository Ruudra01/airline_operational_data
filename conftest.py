"""Root conftest.

Its only job is to exist: pytest puts the directory containing the topmost
conftest.py on sys.path, which makes `config`, `elt.transform.validation`,
etc. importable from the tests without any packaging ceremony.
"""
