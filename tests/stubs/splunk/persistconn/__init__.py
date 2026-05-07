"""
Stub for splunk.persistconn package.

Real Splunk ships this as part of the bundled Python on the indexer.
Outside Splunk we substitute a minimal package so handler modules
can be imported in unit tests.

DO NOT add behaviour here — the stub exists only to satisfy `from
splunk.persistconn.application import PersistentServerConnectionApplication`.
Tests that need to exercise the handler should construct it directly
and call its methods; they should not rely on parent-class behaviour.
"""
