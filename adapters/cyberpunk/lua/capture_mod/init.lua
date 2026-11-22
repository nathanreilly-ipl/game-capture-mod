-- capture_mod: a Cyber Engine Tweaks mod that runs Lua "jobs" on request, so Cyberpunk 2077 can
-- be driven from outside the game without pressing keys. The same file protocol as the RedLua
-- loader of RDR2 and GTA V (adapters/common/lua/capture_loader.lua), so the same client drives it
-- (adapters/common/redlua.py). Two things differ, both because of Cyber Engine Tweaks' sandbox:
--
--   * A mod may only read and write inside its own folder, with relative paths. The exchange
--     folder is therefore this mod's "exchange" subfolder, job files are loaded from inside it,
--     and folders are made by the outside tool (Lua has no way to make one here).
--   * There are no coroutines. A job cannot wait in the middle of a function: it asks for a
--     function to be called later (ctx.after, ctx.capture) and ends itself with ctx.finish.
--
-- Files in exchange/:
--   command.txt    id=<id>, file=<job .lua, relative to this mod's folder>, timeout_s=<seconds>,
--                  plus any extra key=value pairs (ctx.args). stop=1 instead of file= stops the job.
--   result.txt     written when a job ends: id, status (ok|error|timeout|stopped), message, plus
--                  whatever the job put in ctx.result
--   heartbeat.txt  rewritten about once a second: time, ticks, job, ingame (1 once a save is loaded
--                  and the player is in the world), paused
--   jobs/<id>/     job.log, a copy of result.txt, the frames a job captured (made by the outside tool)
--
-- A job file returns a function(ctx), called once. It stays the running job until it calls
-- ctx.finish, is replaced or stopped, or passes its timeout. It may use:
--   ctx.log(fmt, ...)                 line in jobs/<id>/job.log
--   ctx.after(frames, fn)             call fn after this many game frames
--   ctx.capture(stem, fn, timeout_s)  ask the ReShade add-on for jobs/<id>/<stem>.bmp, then call
--                                     fn(ack) or fn(nil, message)
--   ctx.defer(fn)                     run fn when the job ends, however it ends
--   ctx.each_tick = fn(dt)            run on every frame while the job runs
--   ctx.on_error = fn(message)        an error inside a later call (default: the job ends)
--   ctx.finish(status, message)       end the job
--   ctx.result.<key> = value          extra lines for result.txt
--   ctx.args, ctx.id, ctx.dir (the exchange folder), ctx.job_dir, ctx.ticks()

local EX = 'exchange'
local POLL_TICKS = 10
local DEFAULT_TIMEOUT_S = 60
local CAPTURE_TIMEOUT_S = 10

local job = nil
local ticks = 0
local last_beat = -1
local ready = false
local pending_writes = {}   -- path -> text, for files the outside tool had open when we wrote

local function append(path, text)
	local f = io.open(path, 'a')
	if f then
		f:write(text)
		f:close()
	end
end

-- Writes through a temp file so a reader never sees a partial file. os.rename refuses to replace
-- a file here, so the old one is removed first; if the outside tool has it open, that fails and
-- the write is tried again on the next frames (flush_writes).
local function try_write(path, text)
	local tmp = path .. '.tmp'
	local f = io.open(tmp, 'w')
	if not f then
		return false
	end
	f:write(text)
	f:close()
	os.remove(path)
	local ok = os.rename(tmp, path)
	return ok and true or false
end

local function write_atomic(path, text)
	if try_write(path, text) then
		pending_writes[path] = nil
	else
		pending_writes[path] = text
	end
end

local function flush_writes()
	for path, text in pairs(pending_writes) do
		if try_write(path, text) then
			pending_writes[path] = nil
		end
	end
end

local function read_kv(path)
	local f = io.open(path, 'r')
	if not f then
		return nil
	end
	local text = f:read('*a')
	f:close()
	local kv = {}
	for k, v in text:gmatch('([%w_]+)=([^\r\n]*)') do
		kv[k] = v
	end
	return kv
end

local function one_line(v)
	return (tostring(v):gsub('[\r\n]+', ' | '))
end

local function log(fmt, ...)
	local line = os.date('%Y-%m-%d %H:%M:%S ') .. string.format(fmt, ...) .. '\n'
	append(EX .. '/loader.log', line)
	if job then
		append(job.dir .. '/job.log', line)
	end
end

-- True once a save is loaded and the player is in the world (not the main menu).
local function in_game()
	local ok, res = pcall(function()
		if Game.GetSystemRequestsHandler():IsPreGame() then
			return false
		end
		return Game.GetPlayer() ~= nil
	end)
	return ok and res or false
end

local world_up, sim_runs, last_sim = false, 0, -1

local function sim_time()
	local ok, s = pcall(function() return EngineTime.ToDouble(Game.GetTimeSystem():GetSimTime()) end)
	return ok and s or -1
end

-- True when the collision under the player has loaded: a ray straight down hits built ground
-- ('Static') or open land ('Terrain': the Badlands' dirt is not 'Static').
local function ground_under_player()
	local ok, hit = pcall(function()
		local p = Game.GetPlayer():GetWorldPosition()
		local a, b = Vector4.new(p.x, p.y, p.z + 1.0, 1.0), Vector4.new(p.x, p.y, p.z - 4.0, 1.0)
		local sq = Game.GetSpatialQueriesSystem()
		return (sq:SyncRaycastByCollisionGroup(a, b, 'Static', false, false))
			or (sq:SyncRaycastByCollisionGroup(a, b, 'Terrain', false, false))
	end)
	return ok and hit or false
end

local function is_paused()
	local ok, res = pcall(function()
		return Game.GetSystemRequestsHandler():IsGamePaused()
	end)
	return ok and res or false
end

-- Saving is locked whenever a save is loaded: jobs move the player and change the clock, and an
-- autosave would put that into the player's own save slots (and Steam Cloud). The game's own
-- save-lock manager does it (checked 2026-11-21: Game.IsSavingLocked() turns true). A file
-- allow_saves.txt in the exchange folder leaves saving alone. Returns whether saving is locked.
local LOCK = 'capture_mod'
local function lock_saves()
	local ok, locked = pcall(function()
		local m = Game.GetScriptableSystemsContainer():Get('SaveLocksManager')
		if not m then
			return false
		end
		local f = io.open(EX .. '/allow_saves.txt', 'r')
		if f then
			f:close()
			return m:IsSavingLocked()
		end
		local want = CName.new(LOCK)
		local have = false
		for _, r in ipairs(m.saveLocks) do
			if r.hash_lo == want.hash_lo and r.hash_hi == want.hash_hi then
				have = true
			end
		end
		if not have then
			m:AddSaveLock(LOCK)
			log('saving locked (%s)', LOCK)
		end
		return m:IsSavingLocked()
	end)
	return ok and locked or false
end

local function write_heartbeat()
	local now = os.time()
	if now == last_beat then
		return
	end
	last_beat = now
	local world = in_game()
	local locked = world and lock_saves()
	local sim = world and sim_time() or -1
	-- ingame: a save is loaded AND the world is running. Right after a load the player already
	-- exists while the loading screen is still up, and commands sent then crashed the game
	-- (2026-11-21). The world counts as up once the ground under the player is there and the
	-- simulation clock has moved on three heartbeats in a row; it stays so until the main menu.
	if not world then
		world_up, sim_runs = false, 0
	elseif not world_up then
		sim_runs = (sim > last_sim and last_sim >= 0 and ground_under_player()) and sim_runs + 1 or 0
		world_up = sim_runs >= 3
	end
	last_sim = sim
	write_atomic(EX .. '/heartbeat.txt', string.format(
		'time=%d\nticks=%d\njob=%s\ningame=%d\nworld=%d\npaused=%d\nsaving_locked=%d\nsim_time=%.3f\n',
		now, ticks, job and job.id or '', world_up and 1 or 0, world and 1 or 0, is_paused() and 1 or 0,
		locked and 1 or 0, sim))
end

local function finish(status, message)
	if not job then
		return
	end
	local ending = job
	for i = #ending.deferred, 1, -1 do
		local ok, err = pcall(ending.deferred[i])
		if not ok then
			log('cleanup step failed: %s', one_line(err))
		end
	end
	log('job %s ended: %s %s', ending.id, status, one_line(message or ''))

	local lines = {
		'id=' .. ending.id,
		'status=' .. status,
		'message=' .. one_line(message or ''),
	}
	local keys = {}
	for k in pairs(ending.ctx.result) do
		keys[#keys + 1] = tostring(k)
	end
	table.sort(keys)
	for _, k in ipairs(keys) do
		lines[#lines + 1] = k .. '=' .. one_line(ending.ctx.result[k])
	end
	local text = table.concat(lines, '\n') .. '\n'

	job = nil
	os.remove(EX .. '/request.txt')
	write_atomic(ending.dir .. '/result.txt', text)
	write_atomic(EX .. '/result.txt', text)
end

-- Runs one of a job's functions; an error goes to the job's on_error, or ends the job.
local function guarded(j, fn, ...)
	local ok, err = pcall(fn, ...)
	if ok or job ~= j then
		return
	end
	if j.ctx.on_error then
		local ok2, err2 = pcall(j.ctx.on_error, tostring(err))
		if ok2 then
			return
		end
		err = tostring(err) .. ' | then in on_error: ' .. tostring(err2)
	end
	finish('error', tostring(err))
end

local function make_ctx(j, args)
	local ctx = { id = j.id, args = args, dir = EX, job_dir = j.dir, result = {} }

	function ctx.log(fmt, ...)
		log(fmt, ...)
	end

	function ctx.ticks()
		return ticks
	end

	function ctx.after(frames, fn)
		j.timers[#j.timers + 1] = { at = ticks + math.max(1, math.floor(frames or 1)), fn = fn }
	end

	function ctx.defer(fn)
		j.deferred[#j.deferred + 1] = fn
	end

	function ctx.finish(status, message)
		if job == j then
			finish(status or 'ok', message or '')
		end
	end

	function ctx.capture(stem, fn, timeout_s)
		if not tostring(stem):match('^[%w_%-]+$') then
			error('capture name may only contain letters, digits, _ and -: ' .. tostring(stem))
		end
		j.captures = j.captures + 1
		local req_id = string.format('%s_%d', j.id, j.captures)
		local name = 'jobs/' .. j.id .. '/' .. stem
		if not try_write(EX .. '/request.txt', 'id=' .. req_id .. '\nname=' .. name .. '\n') then
			error('cannot write request.txt')
		end
		j.capture = { id = req_id, name = name, fn = fn, deadline = os.time() + (timeout_s or CAPTURE_TIMEOUT_S) }
	end

	return ctx
end

local function start(cmd)
	local id = cmd.id or ''
	if not id:match('^[%w_%-]+$') then
		log('ignored a command with a missing or invalid id')
		return
	end

	local j = { id = id, dir = EX .. '/jobs/' .. id, deferred = {}, timers = {}, captures = 0 }
	j.ctx = make_ctx(j, cmd)
	j.deadline = os.time() + (tonumber(cmd.timeout_s) or DEFAULT_TIMEOUT_S)
	job = j
	log('job %s starting: %s', id, tostring(cmd.file))

	local chunk, load_err = loadfile(cmd.file or '')
	if not chunk then
		finish('error', 'cannot load job file: ' .. tostring(load_err))
		return
	end
	local ok, fn = pcall(chunk)
	if not ok then
		finish('error', 'job file failed while loading: ' .. tostring(fn))
		return
	end
	if type(fn) ~= 'function' then
		finish('error', 'job file must return a function(ctx)')
		return
	end
	local ok2, err = pcall(fn, j.ctx)
	if not ok2 and job == j then
		finish('error', tostring(err))
	end
end

local function poll_commands()
	local path = EX .. '/command.txt'
	local cmd = read_kv(path)
	if not cmd then
		return
	end
	os.remove(path)
	if job then
		finish('stopped', 'replaced by command ' .. tostring(cmd.id))
	end
	if cmd.stop ~= '1' then
		start(cmd)
	end
end

local function step_job(dt)
	local j = job
	if not j then
		return
	end
	if j.ctx.each_tick then
		guarded(j, j.ctx.each_tick, dt)
	end
	-- a frame the add-on was asked for
	local c = j.capture
	if job == j and c then
		local ack = read_kv(EX .. '/ack.txt')
		if ack and ack.id == c.id then
			j.capture = nil
			if ack.status ~= 'ok' then
				guarded(j, c.fn, nil, 'add-on reported: ' .. tostring(ack.message))
			else
				guarded(j, c.fn, ack)
			end
		elseif os.time() > c.deadline then
			j.capture = nil
			os.remove(EX .. '/request.txt')
			guarded(j, c.fn, nil, 'no ack from the add-on for ' .. c.name .. '; is capture_mod.addon64 loaded?')
		end
	end
	-- functions due on this frame (ones they add run on a later frame)
	if job == j and #j.timers > 0 then
		local due, later = {}, {}
		for _, t in ipairs(j.timers) do
			if t.at <= ticks then
				due[#due + 1] = t
			else
				later[#later + 1] = t
			end
		end
		j.timers = later
		for _, t in ipairs(due) do
			if job ~= j then
				break
			end
			guarded(j, t.fn)
		end
	end
	if job == j and os.time() > j.deadline then
		finish('timeout', 'job ran past its timeout')
	end
end

registerForEvent('onInit', function()
	-- A command left over from before this load is stale; do not run it.
	os.remove(EX .. '/command.txt')
	ready = true
	log('loader ready (Cyber Engine Tweaks %s)', tostring(GetVersion()))
end)

registerForEvent('onUpdate', function(dt)
	if not ready then
		return
	end
	ticks = ticks + 1
	flush_writes()
	if ticks % POLL_TICKS == 0 then
		poll_commands()
	end
	step_job(dt)
	write_heartbeat()
end)

registerForEvent('onShutdown', function()
	finish('stopped', 'loader stopped')
	os.remove(EX .. '/heartbeat.txt')
end)
