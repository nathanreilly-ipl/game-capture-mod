-- capture_loader.lua
-- RedLua script: runs Lua "jobs" on request, so tests can be driven from outside
-- the game without pressing keys. Load it once per game session (F7 menu, or
-- turn on Autorun). It uses no keys.
--
-- Files in OUT_DIR:
--   command.txt    written by scripts/run_job.ps1:  id=<id>, file=<path to a job .lua>,
--                  timeout_s=<seconds>, plus any extra key=value pairs (ctx.args).
--                  stop=1 instead of file= stops the running job.
--   result.txt     written here when a job ends: id, status (ok|error|timeout|stopped),
--                  message, plus whatever the job put in ctx.result
--   heartbeat.txt  rewritten about once a second while this script is running
--   jobs\<id>\     job.log, a copy of result.txt, and any frames the job captured
--
-- A job file returns a function(ctx). It runs as a coroutine, one step per game
-- tick, and may call:
--   ctx.log(fmt, ...)             line in jobs\<id>\job.log
--   ctx.wait(frames)              let the game run this many ticks
--   ctx.call(ns, name, ...)       call a native; errors end the job
--   ctx.try(ns, name, ...)        call a native; returns ok, result
--   ctx.capture(stem [, timeout]) ask the ReShade add-on for jobs\<id>\<stem>.bmp;
--                                 returns the ack table, errors if there is no add-on
--   ctx.defer(fn)                 run fn when the job ends, however it ends
--   ctx.each_tick = fn            run fn on every tick ctx.wait and ctx.capture pass (e.g. calls
--                                 the game needs every frame, like hiding the HUD)
--   ctx.result.<key> = value      extra lines for result.txt
--   ctx.args, ctx.id, ctx.out_dir, ctx.job_dir

-- The exchange folder. This default is RDR2's; `capture install <game>` writes each game's own
-- folder into this line (adapters/common/redlua.py, loader_text).
local OUT_DIR = (os.getenv('USERPROFILE') or 'C:') .. '\\Documents\\RDR2Modding\\captures'
local POLL_TICKS = 10        -- look for command.txt every this many ticks
local DEFAULT_TIMEOUT_S = 60
local CAPTURE_TIMEOUT_S = 10

local t = {}
local job = nil
local ticks = 0
local last_beat = -1

local function make_dirs(path)
	local ok, ffi = pcall(require, 'ffi')
	if not ok then
		return
	end
	pcall(ffi.cdef, 'int CreateDirectoryA(const char *path, void *security);')
	local from = 4 -- skip the drive, e.g. "C:\"
	while true do
		local sep = path:find('\\', from, true)
		local prefix = sep and path:sub(1, sep - 1) or path
		-- Fails harmlessly for levels that already exist.
		pcall(function() ffi.C.CreateDirectoryA(prefix, nil) end)
		if not sep then
			break
		end
		from = sep + 1
	end
end

local function append(path, text)
	local f = io.open(path, 'a')
	if f then
		f:write(text)
		f:close()
	end
end

-- Writes through a temp file so a reader never sees a partial file.
local function write_atomic(path, text)
	local tmp = path .. '.tmp'
	local f, err = io.open(tmp, 'w')
	if not f then
		return false, err
	end
	f:write(text)
	f:close()
	os.remove(path)
	return os.rename(tmp, path)
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
	append(OUT_DIR .. '\\loader.log', line)
	if job then
		append(job.dir .. '\\job.log', line)
	end
end

local function write_heartbeat()
	local now = os.time()
	if now == last_beat then
		return
	end
	last_beat = now
	write_atomic(OUT_DIR .. '\\heartbeat.txt',
		string.format('time=%d\nticks=%d\njob=%s\n', now, ticks, job and job.id or ''))
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
	os.remove(OUT_DIR .. '\\request.txt')
	write_atomic(ending.dir .. '\\result.txt', text)
	write_atomic(OUT_DIR .. '\\result.txt', text)
end

local function make_ctx(j, args)
	local ctx = { id = j.id, args = args, out_dir = OUT_DIR, job_dir = j.dir, result = {} }

	function ctx.log(fmt, ...)
		log(fmt, ...)
	end

	function ctx.wait(frames)
		for _ = 1, frames or 1 do
			if ctx.each_tick then ctx.each_tick() end
			coroutine.yield()
		end
	end

	function ctx.call(ns, name, ...)
		return native.call(ns, name, ...)
	end

	function ctx.try(ns, name, ...)
		return pcall(native.call, ns, name, ...)
	end

	function ctx.defer(fn)
		j.deferred[#j.deferred + 1] = fn
	end

	function ctx.capture(stem, timeout_s)
		if not tostring(stem):match('^[%w_%-]+$') then
			error('capture name may only contain letters, digits, _ and -: ' .. tostring(stem))
		end
		j.captures = j.captures + 1
		local req_id = string.format('%s_%d', j.id, j.captures)
		local name = 'jobs/' .. j.id .. '/' .. stem
		local ok, err = write_atomic(OUT_DIR .. '\\request.txt', 'id=' .. req_id .. '\nname=' .. name .. '\n')
		if not ok then
			error('cannot write request.txt: ' .. tostring(err))
		end
		local deadline = os.time() + (timeout_s or CAPTURE_TIMEOUT_S)
		while true do
			if ctx.each_tick then ctx.each_tick() end
			coroutine.yield()
			local ack = read_kv(OUT_DIR .. '\\ack.txt')
			if ack and ack.id == req_id then
				if ack.status ~= 'ok' then
					error('add-on reported: ' .. tostring(ack.message))
				end
				return ack
			end
			if os.time() > deadline then
				os.remove(OUT_DIR .. '\\request.txt')
				error('no ack from the add-on for ' .. name .. '; is capture_mod.addon64 loaded?')
			end
		end
	end

	return ctx
end

local function start(cmd)
	local id = cmd.id or ''
	if not id:match('^[%w_%-]+$') then
		log('ignored a command with a missing or invalid id')
		return
	end

	local j = { id = id, dir = OUT_DIR .. '\\jobs\\' .. id, deferred = {}, captures = 0 }
	make_dirs(j.dir)
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
	j.co = coroutine.create(fn)
end

local function poll_commands()
	local path = OUT_DIR .. '\\command.txt'
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

local function step_job()
	if not job or not job.co then
		return
	end
	local current = job
	local ok, err = coroutine.resume(current.co, current.ctx)
	if job ~= current then
		return
	end
	if not ok then
		finish('error', debug.traceback(current.co, tostring(err)))
	elseif coroutine.status(current.co) == 'dead' then
		finish('ok', '')
	elseif os.time() > current.deadline then
		finish('timeout', 'job ran past its timeout')
	end
end

function t.OnLoad()
	make_dirs(OUT_DIR)
	-- A command left over from before this load is stale; do not run it.
	os.remove(OUT_DIR .. '\\command.txt')
	log('loader ready; watching %s', OUT_DIR)
end

function t.OnTick()
	ticks = ticks + 1
	if ticks % POLL_TICKS == 0 then
		poll_commands()
	end
	step_job()
	write_heartbeat()
end

function t.OnStop()
	finish('stopped', 'loader stopped')
	os.remove(OUT_DIR .. '\\heartbeat.txt')
end

function t.OnReload()
	finish('stopped', 'loader reloaded')
end

return t
