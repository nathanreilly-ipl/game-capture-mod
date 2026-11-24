"""Kingdom Come: Deliverance adapter (adapter.py), its install (install.py), launch, session and probes."""

from capture import host

# The game checks its licence with a running Steam client at start ("License not verified - SteamAPI
# init failed" without one, a CoreWeave node, 2026-11-24). Under Proton it shares the prefix that
# holds the Steam client of the Rockstar games (`capture host steam`); nothing on Windows.
host.use_prefix("kcd", "rockstar")
