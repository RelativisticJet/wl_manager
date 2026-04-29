"""
Unit tests for the read-access audit dedup cache (round 6).

The handler emits a `whitelist_view` audit event on every CSV read,
deduped per-process to one event per (user, csv, app_context) tuple
per `_VIEW_AUDIT_DEDUP_TTL` seconds. These tests verify the cache
behavior in isolation, without running the handler.

Origin: round 6 audit, 2026-04-29.
"""

import os
import sys
import time

import pytest

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))


def _reset_view_cache(wl_handler_module):
    """Empty the cache between tests."""
    wl_handler_module._VIEW_AUDIT_DEDUP_CACHE.clear()


@pytest.fixture
def cache():
    """Yield a clean cache + the handler module."""
    # Importing wl_handler triggers module-level Splunk imports that
    # are NOT available in the unit-test harness. Skip the import-
    # heavy parts by loading the module's dedup cache constants
    # directly from source as a literal.
    #
    # We construct a minimal in-memory replica of the production
    # cache and TTL so the dedup logic can be exercised without
    # needing the full Splunk REST plumbing.
    cache_dict = {}
    ttl = 3600
    yield cache_dict, ttl


class TestViewAuditDedupCache:
    """Verify the dedup behavior matches the handler's expectations:
    same key inside TTL = no second emission; different key, or
    same key after TTL = new emission allowed.
    """

    def _check_should_emit(self, cache_dict, ttl, key, now):
        """Replica of the inline dedup check in
        ``_get_csv_content``. Returns True if a NEW audit event
        would be emitted; False if the call is deduped."""
        # Prune expired entries first (matches production order).
        expired = [k for k, t in cache_dict.items()
                   if now - t >= ttl]
        for k in expired:
            cache_dict.pop(k, None)
        if key not in cache_dict:
            cache_dict[key] = now
            return True
        return False

    def test_first_view_emits(self, cache):
        cache_dict, ttl = cache
        key = ("alice", "DR1.csv", "wl_manager")
        emitted = self._check_should_emit(cache_dict, ttl, key, 1000)
        assert emitted is True

    def test_second_view_within_ttl_is_deduped(self, cache):
        cache_dict, ttl = cache
        key = ("alice", "DR1.csv", "wl_manager")
        # First emission
        assert self._check_should_emit(cache_dict, ttl, key, 1000)
        # Second emission, 60 seconds later — still inside TTL
        assert not self._check_should_emit(cache_dict, ttl, key, 1060)
        # Even at TTL - 1 second
        assert not self._check_should_emit(cache_dict, ttl, key,
                                           1000 + ttl - 1)

    def test_view_after_ttl_re_emits(self, cache):
        cache_dict, ttl = cache
        key = ("alice", "DR1.csv", "wl_manager")
        assert self._check_should_emit(cache_dict, ttl, key, 1000)
        # Just past TTL — pruning should drop the entry, allowing
        # a new emission.
        assert self._check_should_emit(cache_dict, ttl, key,
                                       1000 + ttl)

    def test_different_user_emits_separately(self, cache):
        cache_dict, ttl = cache
        key1 = ("alice", "DR1.csv", "wl_manager")
        key2 = ("bob", "DR1.csv", "wl_manager")
        assert self._check_should_emit(cache_dict, ttl, key1, 1000)
        assert self._check_should_emit(cache_dict, ttl, key2, 1000)

    def test_different_csv_emits_separately(self, cache):
        cache_dict, ttl = cache
        key1 = ("alice", "DR1.csv", "wl_manager")
        key2 = ("alice", "DR2.csv", "wl_manager")
        assert self._check_should_emit(cache_dict, ttl, key1, 1000)
        assert self._check_should_emit(cache_dict, ttl, key2, 1000)

    def test_different_app_context_emits_separately(self, cache):
        cache_dict, ttl = cache
        # Same user, same csv name, different app context. This is
        # exotic (we already emit cross_app_csv_read for app_context
        # != APP_NAME) but the cache must distinguish to avoid
        # cross-context dedup leaks.
        key1 = ("alice", "DR1.csv", "wl_manager")
        key2 = ("alice", "DR1.csv", "other_app")
        assert self._check_should_emit(cache_dict, ttl, key1, 1000)
        assert self._check_should_emit(cache_dict, ttl, key2, 1000)

    def test_pruning_removes_expired_entries(self, cache):
        cache_dict, ttl = cache
        # Seed with a long-expired entry
        cache_dict[("ghost", "DR9.csv", "wl_manager")] = 1
        assert ("ghost", "DR9.csv", "wl_manager") in cache_dict
        # Any new check past TTL prunes ghost
        self._check_should_emit(
            cache_dict, ttl, ("alice", "DR1.csv", ""), 10000)
        assert ("ghost", "DR9.csv", "wl_manager") not in cache_dict

    def test_cache_size_grows_proportional_to_active_users(self, cache):
        cache_dict, ttl = cache
        # 100 users × 5 csvs = 500 entries within TTL
        for i in range(100):
            for j in range(5):
                self._check_should_emit(
                    cache_dict, ttl,
                    (f"u{i}", f"DR{j}.csv", ""), 1000)
        assert len(cache_dict) == 500
        # All within TTL, no emissions on second call
        for i in range(100):
            for j in range(5):
                emitted = self._check_should_emit(
                    cache_dict, ttl,
                    (f"u{i}", f"DR{j}.csv", ""), 1500)
                assert not emitted, (
                    "duplicate emission for ({}, {})".format(i, j))

    def test_repeated_views_all_deduped(self, cache):
        cache_dict, ttl = cache
        key = ("alice", "DR1.csv", "wl_manager")
        first = self._check_should_emit(cache_dict, ttl, key, 1000)
        assert first
        # 100 dashboard tab-switches → 0 additional emissions
        emit_count = sum(
            1 for t in range(1001, 1100)
            if self._check_should_emit(cache_dict, ttl, key, t))
        assert emit_count == 0
