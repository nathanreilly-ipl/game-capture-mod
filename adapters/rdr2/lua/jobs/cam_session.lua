-- Interactive camera session, driven from outside (adapters/rdr2/session.py).
--
-- The outside tool writes session_in.txt in the captures folder:
--   seq=<n>
--   cmd=<command>
--   args=<space separated numbers or a name>
-- This job runs the command and writes session_out.txt with the same seq,
-- status=ok|error, message, and the current camera state.
--
-- Commands:
--   pose x y z pitch yaw fov    place the script camera (rotation order 2, degrees)
--   freeze                       photo-mode freeze (world and camera stop)
--   unfreeze
--   wait n                       let n ticks pass
--   capture stem                 save a frame through the add-on into this job's folder
--   shoot n stem                 wait n ticks, then capture
--   teleport x y z h [ticks]     move the player and wait for the scene to load
--   ground x y z                 height of the ground below a point
--   player_visible 0|1, clock h m, exposure ..., advance s [scale], project x y z
--   state                        only report the state
--   end                          finish the job
-- Every answer carries the rendered camera, the game timer, and health lines
-- (player_visible, pause_menu, player_heading, clock) for the per-shot checks.
return function(ctx)
	local IN = ctx.out_dir .. '\\session_in.txt'
	local OUT = ctx.out_dir .. '\\session_out.txt'
	local IDLE_TIMEOUT_S = tonumber(ctx.args.idle_s) or 300

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

	-- The outside tool may hold the file open for reading; retry over a few ticks.
	local function write_atomic(path, text)
		local tmp = path .. '.tmp'
		local last_err
		for _ = 1, 60 do
			local f = io.open(tmp, 'w')
			if f then
				f:write(text)
				f:close()
				os.remove(path)
				local ok, err = os.rename(tmp, path)
				if ok then
					return
				end
				last_err = err
			end
			ctx.wait(1)
		end
		error('cannot write ' .. path .. ': ' .. tostring(last_err))
	end

	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	-- RedLua returns PLAYER_ID() typed as a Cam here ("Cam: 4354"), which every Player native
	-- rejects. A Player made with native.new holds 0, the single-player index; checked
	-- 2026-11-20 (lua/jobs/type_probe.lua): GET_PLAYER_PED of it is PLAYER_PED_ID().
	local pid = native.new('Player', 1)[0]
	local cam = nil
	local frozen = false
	local held = false -- player position frozen (hold, teleport, park)

	ctx.defer(function()
		if frozen then
			pcall(native.call, 'ANIMSCENE', '_REQUEST_PHOTO_MODE_DEFREEZE')
		end
		if cam then
			native.call('CAM', 'RENDER_SCRIPT_CAMS', false, false, 0, true, false, 0)
			native.call('CAM', 'SET_CAM_ACTIVE', cam, false)
			native.call('CAM', 'DESTROY_CAM', cam, false)
		end
		os.remove(IN)
	end)

	-- Zone name hashes at a point, for a readable place title (adapters/rdr2/zones.py):
	-- written label, printed label, town, water body, district, state.
	local function zone_line(x, y, z)
		local out = {}
		for _, ty in ipairs({ 12, 11, 1, 'water', 10, 0 }) do
			local ok, h
			if ty == 'water' then
				ok, h = ctx.try('ZONE', '_GET_WATER_MAP_ZONE_AT_COORDS', x, y, z)
			else
				ok, h = ctx.try('ZONE', '_GET_MAP_ZONE_AT_COORDS', x, y, z, ty)
			end
			out[#out + 1] = ok and tostring(h or 0) or '0'
		end
		return 'zones=' .. table.concat(out, ' ')
	end

	local function state_lines()
		local p = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
		local c = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD')
		local r = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_ROT', 2)
		local fov = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_FOV')
		local lines = {
			string.format('player=%.9g %.9g %.9g', p.x, p.y, p.z),
			string.format('rendered_pos=%.9g %.9g %.9g', c.x, c.y, c.z),
			string.format('rendered_rot=%.9g %.9g %.9g', r.x, r.y, r.z),
			string.format('rendered_fov=%.9g', fov),
			'frozen=' .. (frozen and '1' or '0'),
			'game_timer=' .. tostring(ctx.call('MISC', 'GET_GAME_TIMER')),
		}
		-- Health, for the per-shot checks: these must not end the session if one fails.
		local okh, heading = ctx.try('ENTITY', 'GET_ENTITY_HEADING', ped)
		if okh then
			lines[#lines + 1] = string.format('player_heading=%.9g', heading)
		end
		local okv, visible = ctx.try('ENTITY', 'IS_ENTITY_VISIBLE', ped)
		if okv then
			lines[#lines + 1] = 'player_visible=' .. (visible and '1' or '0')
		end
		local okp, paused = ctx.try('HUD', 'IS_PAUSE_MENU_ACTIVE')
		if okp then
			lines[#lines + 1] = 'pause_menu=' .. (paused and '1' or '0')
		end
		lines[#lines + 1] = zone_line(p.x, p.y, p.z)
		local okc, hh = ctx.try('CLOCK', 'GET_CLOCK_HOURS')
		local okm, mm = ctx.try('CLOCK', 'GET_CLOCK_MINUTES')
		if okc and okm then
			lines[#lines + 1] = string.format('clock=%02d:%02d', hh, mm)
		end
		if cam then
			local sc = ctx.call('CAM', 'GET_CAM_COORD', cam)
			lines[#lines + 1] = string.format('script_cam_pos=%.9g %.9g %.9g', sc.x, sc.y, sc.z)
		end
		return lines
	end

	local function respond(seq, status, message, extra)
		local lines = { 'seq=' .. tostring(seq), 'status=' .. status, 'message=' .. (message or '') }
		for _, l in ipairs(extra or {}) do
			lines[#lines + 1] = l
		end
		for _, l in ipairs(state_lines()) do
			lines[#lines + 1] = l
		end
		write_atomic(OUT, table.concat(lines, '\n') .. '\n')
	end

	local function numbers(s)
		local out = {}
		for n in (s or ''):gmatch('[^%s]+') do
			out[#out + 1] = tonumber(n)
		end
		return out
	end

	local handlers = {}

	function handlers.pose(args)
		local a = numbers(args)
		if #a < 6 then
			error('pose needs x y z pitch yaw fov')
		end
		if not cam then
			cam = ctx.call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
			ctx.call('CAM', 'SET_CAM_COORD', cam, a[1], a[2], a[3])
			ctx.call('CAM', 'SET_CAM_ROT', cam, a[4], 0.0, a[5], 2)
			ctx.call('CAM', 'SET_CAM_FOV', cam, a[6])
			ctx.call('CAM', 'SET_CAM_ACTIVE', cam, true)
			ctx.call('CAM', 'RENDER_SCRIPT_CAMS', true, false, 0, true, false, 0)
		else
			ctx.call('CAM', 'SET_CAM_COORD', cam, a[1], a[2], a[3])
			ctx.call('CAM', 'SET_CAM_ROT', cam, a[4], 0.0, a[5], 2)
			ctx.call('CAM', 'SET_CAM_FOV', cam, a[6])
		end
	end

	function handlers.freeze()
		ctx.call('ANIMSCENE', '_REQUEST_PHOTO_MODE_FREEZE')
		frozen = true
	end

	function handlers.unfreeze()
		ctx.call('ANIMSCENE', '_REQUEST_PHOTO_MODE_DEFREEZE')
		frozen = false
	end

	function handlers.wait(args)
		ctx.wait(math.max(1, math.floor(numbers(args)[1] or 1)))
	end

	function handlers.capture(args)
		local ack = ctx.capture(args)
		return { 'width=' .. tostring(ack.width), 'height=' .. tostring(ack.height),
			'file=' .. ctx.job_dir .. '\\' .. args .. '.bmp' }
	end

	function handlers.state() end

	-- clock h m: set the time of day.
	function handlers.clock(args)
		local a = numbers(args)
		ctx.call('CLOCK', 'SET_CLOCK_TIME', math.floor(a[1] or 12), math.floor(a[2] or 0), 0)
		return { string.format('clock=%02d:%02d', ctx.call('CLOCK', 'GET_CLOCK_HOURS'), ctx.call('CLOCK', 'GET_CLOCK_MINUTES')) }
	end

	-- shoot n stem: let n ticks pass, then capture (one round trip per shot).
	function handlers.shoot(args)
		local n, stem = (args or ''):match('^(%d+)%s+(%S+)$')
		ctx.wait(math.max(1, tonumber(n) or 1))
		return handlers.capture(stem)
	end

	-- ground x y z: height of the ground below a point.
	function handlers.ground(args)
		local a = numbers(args)
		local gz = native.new('float', 1)
		local ok = ctx.call('MISC', 'GET_GROUND_Z_FOR_3D_COORD', a[1], a[2], a[3], gz, false)
		return { 'ground_found=' .. tostring(ok), string.format('ground_z=%.9g', gz[0]) }
	end

	-- focus x y z | focus clear: stream the world around a point instead of around the player.
	local focused = false
	ctx.defer(function()
		if focused then
			pcall(native.call, 'STREAMING', 'CLEAR_FOCUS')
		end
	end)
	function handlers.focus(args)
		if (args or ''):match('clear') then
			ctx.call('STREAMING', 'CLEAR_FOCUS')
			focused = false
		else
			local a = numbers(args)
			ctx.call('STREAMING', 'SET_FOCUS_POS_AND_VEL', a[1], a[2], a[3], 0.0, 0.0, 0.0)
			focused = true
		end
		return { 'focused=' .. (focused and '1' or '0') }
	end

	-- park x y z: put the player at an exact point with gravity off (position frozen, no
	-- collision), e.g. high above the capture location. Undone when the session ends.
	local parked, park_return = false, nil
	ctx.defer(function()
		if parked then
			-- back to where the player was before, so releasing the hold cannot drop them from the sky
			pcall(native.call, 'ENTITY', 'FREEZE_ENTITY_POSITION', ped, true)
			if park_return then
				pcall(native.call, 'ENTITY', 'SET_ENTITY_COORDS', ped, park_return.x, park_return.y, park_return.z,
					false, false, false, false)
			end
			pcall(native.call, 'ENTITY', 'SET_ENTITY_COLLISION', ped, true, true)
			pcall(native.call, 'ENTITY', 'FREEZE_ENTITY_POSITION', ped, false)
		end
	end)
	function handlers.park(args)
		local a = numbers(args)
		if not parked then
			park_return = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
		end
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, true)
		ctx.call('ENTITY', 'SET_ENTITY_COLLISION', ped, false, false)
		ctx.call('ENTITY', 'SET_ENTITY_COORDS', ped, a[1], a[2], a[3], false, false, false, false)
		held, parked = true, true
	end

	-- ghost 0|1: the player as absent as the game allows: ignored by everyone, no law
	-- response or wanted score, silent, invincible, no collision. Undone when the session ends.
	local ghost = false
	local function set_ghost(on)
		ctx.try('PLAYER', 'SET_EVERYONE_IGNORE_PLAYER', pid, on)
		ctx.try('PLAYER', 'SET_PLAYER_INVINCIBLE', pid, on)
		ctx.try('PLAYER', 'SET_PLAYER_NOISE_MULTIPLIER', pid, on and 0.0 or 1.0)
		ctx.try('PLAYER', 'SET_WANTED_LEVEL_MULTIPLIER', on and 0.0 or 1.0)
		ctx.try('LAW', 'SET_LAW_SENSE_RANGE_MODIFIER', pid, on and 0.0 or 1.0)
		ctx.try('LAW', '_SET_LAW_DISABLED', on)
		if on then
			ctx.try('LAW', 'CLEAR_WANTED_SCORE', pid)
			ctx.try('EVENT', 'REMOVE_ALL_SHOCKING_EVENTS', false)
		end
		ctx.try('ENTITY', 'SET_ENTITY_COLLISION', ped, not on, not on)
		ghost = on
	end
	ctx.defer(function()
		if ghost then
			pcall(set_ghost, false)
		end
	end)
	function handlers.ghost(args)
		set_ghost((numbers(args)[1] or 1) ~= 0)
		return { 'ghost=' .. (ghost and '1' or '0') }
	end

	-- law: the player's wanted score, bounty, and whether a law incident is active
	function handlers.law()
		local _, score = ctx.try('LAW', 'GET_WANTED_SCORE', pid)
		local _, incident = ctx.try('LAW', 'IS_LAW_INCIDENT_ACTIVE', pid)
		local _, bounty = ctx.try('LAW', 'GET_BOUNTY', pid)
		return { 'wanted_score=' .. tostring(score), 'law_incident=' .. tostring(incident), 'bounty=' .. tostring(bounty) }
	end

	-- place x y z: zone name hashes at a point (answer line place_zones=...)
	function handlers.place(args)
		local a = numbers(args)
		return { 'place_' .. zone_line(a[1], a[2], a[3]) }
	end

	-- hold 0|1: keep the player's position frozen (no stumbling after a teleport, no drifting
	-- while hidden). Released when the session ends.
	ctx.defer(function()
		if held then
			pcall(native.call, 'ENTITY', 'FREEZE_ENTITY_POSITION', ped, false)
		end
	end)
	function handlers.hold(args)
		held = (numbers(args)[1] or 1) ~= 0
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, held)
		return { 'held=' .. (held and '1' or '0') }
	end

	-- teleport x y z heading [max_ticks] [hold]: move the player to (x, y), standing on the
	-- ground near z, and wait until collision and the scene around it have loaded. With hold
	-- (the default), the player's position stays frozen afterwards (see hold).
	function handlers.teleport(args)
		local a = numbers(args)
		if #a < 3 then
			error('teleport needs x y z [heading] [max_ticks] [hold]')
		end
		local x, y, z, h = a[1], a[2], a[3], a[4] or 0.0
		local max_ticks = math.floor(a[5] or 900)
		local keep = (a[6] or 1) ~= 0
		parked = false -- a teleport ends any parking (collision is restored below by ghost/park owners)
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, true)
		ctx.call('ENTITY', 'SET_ENTITY_COORDS', ped, x, y, z + 1.0, false, false, false, false)
		ctx.call('ENTITY', 'SET_ENTITY_HEADING', ped, h)
		local scene_ok = ctx.try('STREAMING', 'LOAD_SCENE_START', x, y, z, 0.0, 0.0, 0.0, 200.0, 0)
		local ticks, loaded = 0, false
		while ticks < max_ticks do
			ctx.try('STREAMING', 'REQUEST_COLLISION_AT_COORD', x, y, z)
			ctx.wait(1)
			ticks = ticks + 1
			local _, coll = ctx.try('ENTITY', 'HAS_COLLISION_LOADED_AROUND_ENTITY', ped)
			local oks, scene = ctx.try('STREAMING', 'IS_LOAD_SCENE_LOADED')
			if ticks >= 30 and coll and (scene or not oks or not scene_ok) then
				loaded = true
				break
			end
		end
		ctx.try('STREAMING', 'LOAD_SCENE_STOP')
		local gz = native.new('float', 1)
		local found = ctx.call('MISC', 'GET_GROUND_Z_FOR_3D_COORD', x, y, z + 2.0, gz, false)
		if found then
			ctx.call('ENTITY', 'SET_ENTITY_COORDS', ped, x, y, gz[0] + 1.0, false, false, false, false)
		end
		ctx.call('ENTITY', 'SET_ENTITY_HEADING', ped, h)
		-- Stand still: no landing stumble or leftover movement from before the teleport.
		ctx.try('TASK', 'CLEAR_PED_TASKS_IMMEDIATELY', ped, false, true)
		held = keep
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, keep)
		return { 'loaded=' .. tostring(loaded), 'ticks=' .. ticks, 'ground_found=' .. tostring(found),
			string.format('ground_z=%.9g', gz[0]), 'held=' .. (keep and '1' or '0') }
	end

	-- player_visible 0|1
	local player_hidden = false
	ctx.defer(function()
		if player_hidden then
			pcall(native.call, 'ENTITY', 'SET_ENTITY_VISIBLE', ped, true)
		end
	end)
	function handlers.player_visible(args)
		local on = (numbers(args)[1] or 1) ~= 0
		ctx.call('ENTITY', 'SET_ENTITY_VISIBLE', ped, on)
		player_hidden = not on
	end

	-- advance seconds [scale]: release the freeze at a reduced time scale until the
	-- summed frame time reaches `seconds`, then freeze again. Reports what was advanced.
	function handlers.advance(args)
		local a = numbers(args)
		local target = a[1] or (1 / 30)
		local scale = a[2] or 0.1
		local t0 = ctx.call('MISC', 'GET_GAME_TIMER')
		local acc, ticks, steps = 0.0, 0, {}
		ctx.call('MISC', 'SET_TIME_SCALE', scale)
		ctx.call('ANIMSCENE', '_REQUEST_PHOTO_MODE_DEFREEZE')
		frozen = false
		local last = 0
		while true do
			ctx.wait(1)
			ticks = ticks + 1
			local dt = ctx.call('MISC', 'GET_FRAME_TIME')
			acc = acc + dt
			steps[#steps + 1] = string.format('%.5f', dt)
			last = dt
			-- The freeze takes effect one tick after it is requested (measured: every step
			-- overshot by one tick), so count that tick, then stop at the nearest tick.
			if acc + last * 1.5 >= target or ticks > 2000 then
				break
			end
		end
		ctx.call('ANIMSCENE', '_REQUEST_PHOTO_MODE_FREEZE')
		frozen = true
		ctx.wait(2)
		local after = 0.0
		for _ = 1, 3 do
			after = after + ctx.call('MISC', 'GET_FRAME_TIME')
			ctx.wait(1)
		end
		return {
			string.format('advanced_s=%.9g', acc),
			'ticks=' .. ticks,
			'timer_ms=' .. tostring(ctx.call('MISC', 'GET_GAME_TIMER') - t0),
			string.format('frame_time_after_freeze=%.6g', after / 3),
			'dts=' .. table.concat(steps, ' '),
		}
	end

	-- exposure lock|unlock|reset|get|set <value>   (photo-mode exposure controls)
	local exposure_locked = false
	ctx.defer(function()
		if exposure_locked then
			pcall(native.call, 'GRAPHICS', '_SET_PHOTO_MODE_EXPOSURE_LOCKED', false)
		end
	end)
	function handlers.exposure(args)
		local verb, value = (args or ''):match('^(%a+)%s*(%S*)')
		if verb == 'lock' or verb == 'unlock' then
			ctx.call('GRAPHICS', '_SET_PHOTO_MODE_EXPOSURE_LOCKED', verb == 'lock')
			exposure_locked = verb == 'lock'
		elseif verb == 'reset' then
			ctx.call('GRAPHICS', '_UPDATE_PHOTO_MODE_EXPOSURE')
		elseif verb == 'set' then
			ctx.call('GRAPHICS', '_CHANGE_PHOTO_MODE_EXPOSURE', tonumber(value))
		elseif verb == 'adapt' then
			ctx.call('GRAPHICS', 'RESET_ADAPTATION', math.floor(tonumber(value) or 1))
		elseif verb ~= 'get' then
			error('exposure lock|unlock|reset|get|set <value>|adapt <n>')
		end
		return { string.format('exposure=%.9g', ctx.call('GRAPHICS', '_GET_PHOTO_MODE_EXPOSURE')) }
	end

	-- project x y z: where the engine puts a world point on screen (0..1 each way).
	local sx, sy
	function handlers.project(args)
		local a = numbers(args)
		if not sx then
			sx, sy = native.new('float', 1), native.new('float', 1)
		end
		local on = ctx.call('GRAPHICS', 'GET_SCREEN_COORD_FROM_WORLD_COORD', a[1], a[2], a[3], sx, sy)
		return { 'onscreen=' .. tostring(on), string.format('screen=%.9g %.9g', sx[0], sy[0]) }
	end

	-- While this file is fresh, other scripts (the scout overlay) stay off the screen.
	local ACTIVE = ctx.out_dir .. '\\session_active.txt'
	local function mark_active()
		local f = io.open(ACTIVE, 'w')
		if f then
			f:write(tostring(os.time()))
			f:close()
		end
	end
	ctx.defer(function() os.remove(ACTIVE) end)
	mark_active()

	os.remove(IN)
	respond(0, 'ok', 'ready')
	ctx.log('session ready')

	local last_seq = 0
	local idle_deadline = os.time() + IDLE_TIMEOUT_S
	local hide_hud = ctx.args.hide_hud ~= '0'
	local tick = 0
	while true do
		ctx.wait(1)
		tick = tick + 1
		if tick % 60 == 0 then
			mark_active()
		end
		if hide_hud then
			pcall(native.call, 'HUD', 'HIDE_HUD_AND_RADAR_THIS_FRAME')
			pcall(native.call, 'HUD', '_UI_PROMPT_DISABLE_PROMPTS_THIS_FRAME')
		end
		local req = read_kv(IN)
		local seq = req and tonumber(req.seq)
		if seq and seq > last_seq then
			last_seq = seq
			idle_deadline = os.time() + IDLE_TIMEOUT_S
			local cmd = req.cmd or ''
			if cmd == 'end' then
				respond(seq, 'ok', 'ending')
				return
			end
			local h = handlers[cmd]
			if not h then
				respond(seq, 'error', 'unknown command ' .. cmd)
			else
				local ok, res = pcall(h, req.args)
				if ok then
					respond(seq, 'ok', '', res)
				else
					respond(seq, 'error', tostring(res))
				end
			end
		elseif os.time() > idle_deadline then
			error('no command for ' .. IDLE_TIMEOUT_S .. ' s')
		end
	end
end
