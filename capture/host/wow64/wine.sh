#!/bin/sh
# wine.sh <proton files folder> <program> [arguments]: runs a Windows program with Proton's Wine,
# straight through Wine's preloader and not through Proton's script. Run inside the Steam Linux
# Runtime container (capture/host/proton.py: wine_direct). Proton's script always puts its own
# stand-in for the Steam client around a program; a real Steam client in the prefix, and the games
# it starts, need Wine without that.
F="$1"; shift
export PATH="$F/bin:$PATH" LD_LIBRARY_PATH="$F/lib:$LD_LIBRARY_PATH" WINELOADERNOEXEC=1
[ -n "$CAPTURE_PRELOAD" ] && export LD_PRELOAD="$CAPTURE_PRELOAD${LD_PRELOAD:+:$LD_PRELOAD}"
[ -n "$CAPTURE_CWD" ] && cd "$CAPTURE_CWD"
exec "$F/lib/wine/x86_64-unix/wine-preloader" "$F/lib/wine/x86_64-unix/wine" "$@"
