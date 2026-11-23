"""GTA V story mode adapters: Legacy (gtav, dropped) and Enhanced (gtave)."""
from capture import host

# Rockstar's games share one launcher and one sign-in, so under Proton they share one prefix
for _game in ("gtav", "gtave"):
    host.use_prefix(_game, "rockstar")
