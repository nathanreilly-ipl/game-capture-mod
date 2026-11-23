"""Helpers game adapters share, none of them tied to one game:

    window.py   find the game window, focus it, send keys, grab what is on screen
                (window_win32.py on Windows, window_x11.py for a game under Proton)
    mem.py      read, search and write a running game's memory (mem_win32.py, mem_linux.py)
    redlua.py   drive a game through RedLua (RDR2 and GTA V builds): the job loader
                (lua/capture_loader.lua) and the client for a long session job

Each adapter binds them to its game (process name, window class, exchange folder).
"""
