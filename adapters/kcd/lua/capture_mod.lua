-- capture_mod: the session script for Kingdom Come: Deliverance (adapters/kcd in the capture_mod
-- repository). Installed as a mod (Mods\capture_mod\mod.manifest and Data\capture_mod.pak holding
-- Scripts\Startup\capture_mod.lua), so the game runs it at start, at the main menu (29 s after the
-- exe starts, 2026-11-23). It can also be loaded into a running game (session.load_lua).
--
-- Commands come in through the game's console (started with -devmode), as Lua lines:
--     #CaptureMod.cmd(<seq>, "<op>", args...)
-- (at most about 250 characters a line: longer ones come in pieces, CaptureMod.chunk / run) and
-- answers go out through the game's log (kcd.log in the game folder) as lines holding
--     [CaptureMod] d|<seq>|...          data
--     [CaptureMod] s|<seq>|key=value    the state
--     [CaptureMod] e|<seq>|ok|text      or e|<seq>|error|text, always last
--     [CaptureMod] t|<seq>|...          a time step's result, when it is done
-- (adapters/common/console.py reads them).

CaptureMod = CaptureMod or {}
CaptureMod.ops = CaptureMod.ops or {}

local P = "[CaptureMod] "

local function line(s)
    System.LogAlways(P .. s)
end
CaptureMod.line = line

local function f(v, n)
    return string.format("%." .. (n or 4) .. "f", v or 0)
end

local function v3(v)
    if not v then return "0,0,0" end
    return f(v.x) .. "," .. f(v.y) .. "," .. f(v.z)
end

local function b(v) return v and 1 or 0 end

local function dist2(a, c)
    return math.sqrt((a.x - c.x) ^ 2 + (a.y - c.y) ^ 2)
end

-- The main menu is a view of the real Rattay level with a player in it (sv_map is "rataje" there
-- too), so "a save is loaded" is told by the player standing somewhere else than the main menu's
-- spot (728.86, 3411.60 on 2026-11-23, 1.9.8).
CaptureMod.MENU_POS = {x = 728.86, y = 3411.60}

function CaptureMod.in_world()
    if not player then return false end
    return dist2(player:GetWorldPos(), CaptureMod.MENU_POS) > 2.0
end

function CaptureMod.state_text()
    local out = {}
    local function add(k, v) out[#out + 1] = k .. "=" .. tostring(v) end
    add("ingame", b(CaptureMod.in_world()))
    add("held", b(System.GetCVar("t_Scale") == 0))
    add("world", string.format("%.7f", CaptureMod.world_time()))
    add("t_scale", System.GetCVar("t_Scale"))
    add("time", f(System.GetCurrTime(), 6))
    add("frame", System.GetFrameID())
    add("loading", b(Game.IsLoadingEngineSaveGame and Game.IsLoadingEngineSaveGame()))
    if player then
        add("player", v3(player:GetWorldPos()))
        add("heading", f(math.deg(player:GetWorldAngles().z), 3))
        add("hidden", b(player:IsHidden()))
    end
    add("cam", v3(System.GetViewCameraPos()))
    add("fwd", v3(System.GetViewCameraDir()))
    add("up", v3(System.GetViewCameraUpDir()))
    add("fov", f(math.deg(System.GetViewCameraFov()), 4))
    add("posed", b(CaptureMod.posed))
    add("hud", System.GetCVar("g_showHUD"))
    add("gt", f(Calendar.GetWorldTime(), 2))
    add("map", System.GetCVar("sv_map"))
    add("savelock", b(CaptureMod.savelock))
    add("ghost", b(CaptureMod.ghosted))
    return table.concat(out, " ")
end

local function ok(seq, text)
    line("s|" .. seq .. "|" .. CaptureMod.state_text())
    line("e|" .. seq .. "|ok|" .. (text or ""))
end
CaptureMod.ok = ok

function CaptureMod.cmd(seq, op, ...)
    local fn = CaptureMod.ops[op]
    if not fn then
        line("e|" .. seq .. "|error|no command " .. tostring(op))
        return
    end
    local good, err = pcall(fn, seq, ...)
    if not good then
        pcall(function() line("s|" .. seq .. "|" .. CaptureMod.state_text()) end)
        line("e|" .. seq .. "|error|" .. tostring(err))
    end
end

-- a command too long for one console line (about 250 characters) comes in pieces (session.py)
CaptureMod.buf = CaptureMod.buf or {}

function CaptureMod.reset(seq)
    CaptureMod.buf = {}
    line("e|" .. seq .. "|ok|")
end

function CaptureMod.chunk(seq, piece)
    CaptureMod.buf[#CaptureMod.buf + 1] = piece
    line("e|" .. seq .. "|ok|" .. #CaptureMod.buf)
end

function CaptureMod.run(seq)
    local src = table.concat(CaptureMod.buf)
    CaptureMod.buf = {}
    local fn, err = loadstring("return {" .. src .. "}")
    if not fn then
        line("e|" .. seq .. "|error|" .. tostring(err))
        return
    end
    CaptureMod.cmd(seq, unpack(fn()))
end

-- the numbers of an underscore-separated list ("1.5_-2_3")
local function nums(s)
    local t = {}
    for v in string.gmatch(s, "[^_]+") do t[#t + 1] = tonumber(v) end
    return t
end

CaptureMod.ops.hello = function(seq) ok(seq, "capture_mod 1") end
CaptureMod.ops.state = function(seq) ok(seq) end

-- any Lua, its value back as text: the agent's research tool (an expression, or statements whose
-- `return` gives the value)
CaptureMod.ops.eval = function(seq, code)
    local chunk, err = loadstring("return " .. code)
    if not chunk then chunk, err = loadstring(code) end
    if not chunk then error(err) end
    local r = chunk()
    line("d|" .. seq .. "|" .. tostring(r))
    ok(seq)
end

-- The world held: CryEngine's time scale at 0 (people, the game's timer and the world clock stand
-- still while frames render; 2026-11-23, probes/freeze_probe.py). Script timers run on game time,
-- so none fires while held. Frame-time smoothing off, so that a step's frames are exact.
-- The world's own clock for the take log. The game's timer (System.GetCurrTime, a float) creeps
-- while held although nothing in the world moves (420 s held: the timer 5.9 ms on, the same frame
-- at both ends to 0.0038 levels of 255, none of 17 people moved 0.1 mm; probes/creep_probe.py), so
-- the world's time is counted here: the exact sum of the steps, plus the timer while the world runs
-- free. Lua numbers are doubles.
CaptureMod.world = CaptureMod.world or 0
function CaptureMod.world_time()
    if CaptureMod.free_since then
        return CaptureMod.world + (System.GetCurrTime() - CaptureMod.free_since)
    end
    return CaptureMod.world
end

if CaptureMod.free_since == nil and System.GetCVar("t_Scale") ~= 0 then
    CaptureMod.free_since = System.GetCurrTime()      -- loaded with the world running
end

local function hold_clock()
    if CaptureMod.free_since then
        CaptureMod.world = CaptureMod.world + (System.GetCurrTime() - CaptureMod.free_since)
        CaptureMod.free_since = nil
    end
end

CaptureMod.ops.freeze = function(seq)
    System.SetCVar("t_Smoothing", 0)
    System.SetCVar("t_Scale", 0)
    hold_clock()
    ok(seq)
end

CaptureMod.ops.unfreeze = function(seq)
    if CaptureMod.step then CaptureMod.step.active = false end
    System.SetCVar("t_FixedStep", 0)
    System.SetCVar("t_Scale", 1)
    System.SetCVar("t_Smoothing", 1)
    if not CaptureMod.free_since then CaptureMod.free_since = System.GetCurrTime() end
    ok(seq)
end

-- A time step of dt over n frames of exactly dt/n each (t_FixedStep; frame-time smoothing off, or
-- the first frames after a hold ramp up from 0), counted by a script timer that fires once per
-- frame while the world runs, held again after the n-th. Measured 2026-11-23: 30 steps of 1/30 s
-- in 8 frames, each frame 4.1666 ms, each step 33.3330 ms. Answers at once ("started"); logs
-- "t|<seq>|advanced=<sum of frame times> frames=<n> min=.. max=.." when done.
CaptureMod.step = CaptureMod.step or {}

function CaptureMod.step_tick()
    local st = CaptureMod.step
    if not st.active then return end
    local d = System.GetFrameTime()
    if d > 0 then
        st.n = st.n + 1
        st.sum = st.sum + d
        if d < st.min then st.min = d end
        if d > st.max then st.max = d end
    end
    if st.n >= st.frames or st.ticks > 1000 then
        System.SetCVar("t_Scale", 0)
        System.SetCVar("t_FixedStep", 0)
        st.active = false
        CaptureMod.world = CaptureMod.world + st.sum
        line("t|" .. st.seq .. "|advanced=" .. string.format("%.7f", st.sum) .. " frames=" .. st.n
            .. " min=" .. string.format("%.7f", st.min) .. " max=" .. string.format("%.7f", st.max))
        return
    end
    st.ticks = st.ticks + 1
    Script.SetTimer(1, CaptureMod.step_tick)
end

CaptureMod.ops.step = function(seq, dt, n)
    n = n or 8
    System.SetCVar("t_Smoothing", 0)
    CaptureMod.step = {active = true, seq = seq, frames = n, n = 0, sum = 0, min = 1e9, max = 0, ticks = 0}
    System.SetCVar("t_FixedStep", dt / n)
    System.SetCVar("t_Scale", 1)
    Script.SetTimer(1, CaptureMod.step_tick)
    ok(seq, "started")
end

-- The rendered camera at a world pose: CryAction.SetViewCameraByAngles takes degrees as CryEngine's
-- Ang3 (x pitch, y roll, z yaw; the rotation is Rz(yaw) Ry(roll) Rx(pitch), forward +Y), then the
-- vertical field of view in degrees. Held until cm release.
CaptureMod.ops.pose = function(seq, x, y, z, pitch, roll, yaw, fov)
    CryAction.SetViewCameraByAngles({x = x, y = y, z = z}, {x = pitch, y = roll, z = yaw})
    if fov and fov > 0 then System.SetViewCameraFov(math.rad(fov)) end
    CaptureMod.posed = true
    ok(seq)
end

CaptureMod.ops.release = function(seq)
    CryAction.ResetToNormalCamera()
    CaptureMod.posed = false
    ok(seq)
end

CaptureMod.ops.hud = function(seq, on)
    System.SetCVar("g_showHUD", on)
    System.SetCVar("wh_ui_ShowHud", on)
    ok(seq)
end

-- the player (and a horse he rides) out of the pictures, or back
CaptureMod.ops.hide = function(seq, on)
    player:Hide(on)
    ok(seq)
end

-- A developer command (Libs\Haste\haste.xml) run through the game's own Haste. Haste keeps its last
-- command as running unless its update runs (it does in the developers' interface only), and a
-- second command then fails inside Haste ("The same command can never be on the stack twice"
-- formats two undefined names: "bad argument #2 to 'strFormat'"), so its state is cleared first.
function CaptureMod.haste(name)
    haste.command = nil
    haste.stack = {}
    haste:RunCommand("RPG", name)
end

-- The player out of the scene for a take: not perceived by anyone (the developers' invisibility
-- command: a behaviour tree that disables his perceptibility, Libs\AI\final\haste\common.xml) and
-- no physics (people walk through him; he neither falls nor is pushed), his body hidden. 0 undoes it.
CaptureMod.ops.ghost = function(seq, on)
    if on == 1 and not CaptureMod.ghosted then
        player:Hide(1)
        CaptureMod.haste("invisibility: ON")
        player:EnablePhysics(false)
        CaptureMod.ghosted = true
    elseif on ~= 1 and CaptureMod.ghosted then
        player:EnablePhysics(true)
        CaptureMod.haste("invisibility: OFF")
        CaptureMod.ghosted = false
    end
    ok(seq)
end

CaptureMod.ops.teleport = function(seq, x, y, z, yaw)
    player:SetWorldPos({x = x, y = y, z = z})
    if yaw then player:SetWorldAngles({x = 0, y = 0, z = math.rad(yaw)}) end
    ok(seq)
end

-- no saving (autosaves included) while a session moves the player about
CaptureMod.ops.savelock = function(seq, on)
    if on == 1 and not CaptureMod.savelock then
        Game.AddSaveLock("CaptureMod")
        CaptureMod.savelock = true
    elseif on ~= 1 and CaptureMod.savelock then
        Game.RemoveSaveLock("CaptureMod")
        CaptureMod.savelock = false
    end
    ok(seq)
end

-- people (NPC, NPC_Female) within r of a point: "d|seq|<id> x,y,z <class>"
CaptureMod.PEOPLE = {NPC = true, NPC_Female = true}

local function eid(e)
    return (string.gsub(tostring(e.id), "^.*: ", ""))      -- "userdata: 00000000000045D1"
end

CaptureMod.ops.people = function(seq, x, y, z, r)
    local n = 0
    for _, e in ipairs(System.GetEntitiesInSphere({x = x, y = y, z = z}, r) or {}) do
        if CaptureMod.PEOPLE[e.class] then
            n = n + 1
            line("d|" .. seq .. "|" .. eid(e) .. " " .. v3(e:GetWorldPos()) .. " " .. e.class)
        end
    end
    ok(seq, "people=" .. n)
end

-- moving things near the rig (people and animals) as boxes: "d|seq|id=.. class=.. pos=x,y,z
-- yaw=deg min=x,y,z max=x,y,z" (the box in the entity's own frame)
CaptureMod.MOVING = {NPC = true, NPC_Female = true, Horse = true, Dog = true, Boar = true, Deer = true,
    Hare = true, Sheep = true, Pig = true, Cow = true, Chicken = true, Hen = true, Rooster = true, Wolf = true}

CaptureMod.ops.ents = function(seq, x, y, z, r)
    local n = 0
    for _, e in ipairs(System.GetEntitiesInSphere({x = x, y = y, z = z}, r) or {}) do
        if CaptureMod.MOVING[e.class] and e ~= player then
            local lo, hi = e:GetLocalBBox()
            n = n + 1
            line("d|" .. seq .. "|id=" .. eid(e) .. " class=" .. e.class .. " pos=" .. v3(e:GetWorldPos())
                .. " yaw=" .. f(math.deg(e:GetWorldAngles().z), 2) .. " min=" .. v3(lo) .. " max=" .. v3(hi)
                .. " name=" .. tostring(e:GetName()))
        end
    end
    ok(seq, "ents=" .. n)
end

-- removes the person or animal nearest each point (within 0.5 m): "x_y_z_x_y_z..."
CaptureMod.ops.remove = function(seq, points)
    local p = nums(points)
    local removed, asked = 0, 0
    for i = 1, #p - 2, 3 do
        asked = asked + 1
        local best, bd = nil, 0.5
        for _, e in ipairs(System.GetEntitiesInSphere({x = p[i], y = p[i + 1], z = p[i + 2]}, 1.0) or {}) do
            if CaptureMod.MOVING[e.class] and e ~= player then
                local d = dist2(e:GetWorldPos(), {x = p[i], y = p[i + 1]})
                if d < bd then best, bd = e, d end
            end
        end
        if best then
            System.RemoveEntity(best.id)
            removed = removed + 1
        end
    end
    ok(seq, "asked=" .. asked .. " removed=" .. removed)
end

-- Long inputs come as Lua files: Python writes <game>\Data\capture_mod_in\<name>.lua, which sets
-- CaptureMod.inbox, and cm load runs it. Script.LoadScript reads loose files only while
-- sys_PakPriority is 0 (2026-11-23); the game runs at 2 (paks only, user.cfg: with loose files
-- looked up, a level took minutes to load from a network folder under Wine, 2026-11-24), so the
-- priority is 0 for the one read and goes back (at 2 the same load gave nothing, at 0 the file).
-- Log lines are cut at about 3,900 characters, so long answers are split into lines of at most
-- CaptureMod.LINE characters.
CaptureMod.LINE = 3500

function CaptureMod.load_loose(path)
    local was = System.GetCVar("sys_PakPriority")
    if was ~= 0 then System.SetCVar("sys_PakPriority", 0) end
    local done, err = pcall(Script.LoadScript, path, true, true)    -- forced: ReloadScript skipped a file it had run
    if was ~= 0 then System.SetCVar("sys_PakPriority", was) end
    if not done then error(err) end
end

CaptureMod.ops.load = function(seq, name)
    CaptureMod.inbox = nil
    CaptureMod.load_loose("capture_mod_in/" .. name .. ".lua")
    if CaptureMod.inbox == nil then error("capture_mod_in/" .. name .. ".lua did not load") end
    ok(seq, "loaded " .. name)
end

local function emit(seq, items)
    -- "d|seq|<first index>|item/item/..." in lines that fit the log
    local i, start = 1, 1
    while i <= #items do
        local parts, len = {}, 0
        while i <= #items and len + #items[i] < CaptureMod.LINE do
            parts[#parts + 1] = items[i]
            len = len + #items[i] + 1
            i = i + 1
        end
        if #parts == 0 then parts[1] = items[i]; i = i + 1 end
        line("d|" .. seq .. "|" .. (start - 1) .. "|" .. table.concat(parts, "/"))
        start = i
    end
end

-- line probes against the static scene, the inbox's {x0,y0,z0,x1,y1,z1, ...} (or a packed
-- "x0_y0_..." argument): "d|seq|<first>|h_x_y_z_nx_ny_nz/..." (h 1 hit, 0 none; terrain and
-- static objects, not people), then "e|seq|ok|n=<rays>"
CaptureMod.ops.rays = function(seq, packed)
    local p = packed and nums(packed) or CaptureMod.inbox
    local out = {}
    local mask = ent_terrain + ent_static
    for i = 1, #p - 5, 6 do
        local d = {x = p[i + 3] - p[i], y = p[i + 4] - p[i + 1], z = p[i + 5] - p[i + 2]}
        local hits = {}
        local c = Physics.RayWorldIntersection({x = p[i], y = p[i + 1], z = p[i + 2]}, d, 1, mask, nil, nil, hits)
        if c and c > 0 and hits[1] then
            local h = hits[1]
            out[#out + 1] = "1_" .. f(h.pos.x) .. "_" .. f(h.pos.y) .. "_" .. f(h.pos.z) .. "_" .. f(h.normal.x, 3)
                .. "_" .. f(h.normal.y, 3) .. "_" .. f(h.normal.z, 3)
        else
            out[#out + 1] = "0"
        end
    end
    emit(seq, out)
    ok(seq, "n=" .. #out)
end

-- the ground under a point (a ray straight down from 50 m above it)
CaptureMod.ops.ground = function(seq, x, y, z)
    local hits = {}
    local c = Physics.RayWorldIntersection({x = x, y = y, z = z + 50}, {x = 0, y = 0, z = -200}, 1,
        ent_terrain + ent_static, nil, nil, hits)
    if c and c > 0 then line("d|" .. seq .. "|" .. v3(hits[1].pos)) else line("d|" .. seq .. "|none") end
    ok(seq)
end

-- the world clock (seconds of game time; 86400 a day) set to h:m of the current day
CaptureMod.ops.clock = function(seq, h, m)
    local t = Calendar.GetWorldTime()
    local day = math.floor(t / 86400) * 86400
    Calendar.SetWorldTime(day + h * 3600 + (m or 0) * 60)
    ok(seq)
end

CaptureMod.ops.weather = function(seq, name)
    EnvironmentModule.BlendTimeOfDay(name, 0, true)
    if EnvironmentModule.ForceImmediateWeatherUpdate then EnvironmentModule.ForceImmediateWeatherUpdate() end
    ok(seq)
end

CaptureMod.ops.cvar = function(seq, name, value)
    if value ~= nil then System.SetCVar(name, value) end
    line("d|" .. seq .. "|" .. tostring(System.GetCVar(name)))
    ok(seq)
end

-- a console command, as typed (load, goto, ...)
CaptureMod.ops.exec = function(seq, text)
    System.ExecuteCommand(text)
    ok(seq)
end

line("loaded capture_mod 1")
