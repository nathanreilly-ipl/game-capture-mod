"""Helpers game adapters share, none of them tied to one game (Windows only):

    window.py   find the game window, focus it, send keys, grab what is on screen
    mem.py      read, search and write a running game's memory
    redlua.py   drive a game through RedLua (RDR2 and GTA V builds): the job loader
                (lua/capture_loader.lua) and the client for a long session job

Each adapter binds them to its game (process name, window class, exchange folder).
"""
