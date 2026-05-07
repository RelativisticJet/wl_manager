"""
Stub for splunk.persistconn.application module.

Provides a minimal `PersistentServerConnectionApplication` base class so
`bin/wl_handler.py` (`class WhitelistHandler(PersistentServerConnectionApplication)`)
can be imported in unit/integration tests without a live Splunk runtime.

Real Splunk's PSCApplication has a richer lifecycle (handle, prepare,
shutdown) that we don't need to model here — tests construct the
handler directly and invoke its methods. The base class only needs to
be a no-op constructor so subclassing works.
"""


class PersistentServerConnectionApplication(object):
    """No-op stub of Splunk's persistent-connection app base class.

    Tests should treat any reliance on parent-class behaviour as a
    smell; if a test breaks because this stub doesn't model some
    Splunk-side hook, the right fix is usually to extract the hook
    into a testable helper, not to expand this stub.
    """

    def __init__(self, command_line=None, command_arg=None):
        # Real Splunk passes command_line + command_arg here; we
        # accept both for compatibility but ignore them. Tests that
        # need to introspect them can patch this constructor.
        self.command_line = command_line
        self.command_arg = command_arg
