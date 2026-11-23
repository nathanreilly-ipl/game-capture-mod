"""RDR2 story mode adapter: Lua jobs (lua/), the ReShade frame-capture add-on (addon/),
launch and recovery scripts (scripts/), the render camera writer (render_camera.py), and
research probes (probes/)."""

from capture import host

# Rockstar's games share one launcher and one sign-in, so under Proton they share one prefix
host.use_prefix("rdr2", "rockstar")
