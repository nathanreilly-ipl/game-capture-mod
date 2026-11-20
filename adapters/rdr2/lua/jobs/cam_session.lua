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
	local cam = nil
	local frozen = false

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

	-- teleport x y z heading [max_ticks]: move the player to (x, y), standing on the ground
	-- near z, and wait until collision and the scene around it have loaded.
	function handlers.teleport(args)
		local a = numbers(args)
		if #a < 3 then
			error('teleport needs x y z [heading] [max_ticks]')
		end
		local x, y, z, h = a[1], a[2], a[3], a[4] or 0.0
		local max_ticks = math.floor(a[5] or 900)
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
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, false)
		return { 'loaded=' .. tostring(loaded), 'ticks=' .. ticks, 'ground_found=' .. tostring(found),
			string.format('ground_z=%.9g', gz[0]) }
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

	os.remove(IN)
	respond(0, 'ok', 'ready')
	ctx.log('session ready')

	local last_seq = 0
	local idle_deadline = os.time() + IDLE_TIMEOUT_S
	local hide_hud = ctx.args.hide_hud ~= '0'
	while true do
		ctx.wait(1)
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
