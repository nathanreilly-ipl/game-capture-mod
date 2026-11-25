-- Interactive camera session for Cyberpunk 2077, driven from outside (adapters/cyberpunk/adapter.py
-- through adapters/common/redlua.py). The same protocol as the RDR2 and GTA V session jobs:
--
-- The outside tool writes session_in.txt in the exchange folder:
--   seq=<n>
--   cmd=<command>
--   args=<space separated numbers or a name>
-- This job runs the command and writes session_out.txt with the same seq, status=ok|error,
-- message, any answer lines, and the current state (player, rendered camera, times, health).
--
-- Cyber Engine Tweaks has no coroutines, so a command that takes several frames answers later:
-- its handler returns ASYNC and calls reply(lines) (or fail(message)) from a ctx.after function.
--
-- Commands:
--   wait n, capture stem, shoot n stem, state, end
--   eval                 run exchange/eval_in.lua (development: the game's script API from outside);
--                        its return values and out(...) lines go to exchange/eval_out.txt
return function(ctx)
	local IN = ctx.dir .. '/session_in.txt'
	local OUT = ctx.dir .. '/session_out.txt'
	local IDLE_TIMEOUT_S = tonumber(ctx.args.idle_s) or 300
	local ASYNC = {}

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

	-- The outside tool may hold the file open for reading; then the write is tried again on the
	-- next frames.
	local out_pending = nil
	local function try_write(path, text)
		local tmp = path .. '.tmp'
		local f = io.open(tmp, 'w')
		if not f then
			return false
		end
		f:write(text)
		f:close()
		os.remove(path)
		return os.rename(tmp, path) and true or false
	end

	local function numbers(s)
		local out = {}
		for n in (s or ''):gmatch('[^%s]+') do
			out[#out + 1] = tonumber(n)
		end
		return out
	end

	local function try(fn, ...)
		local ok, a, b, c = pcall(fn, ...)
		if ok then
			return a, b, c
		end
		return nil
	end

	local function v3(v)
		return string.format('%.9g %.9g %.9g', v.x, v.y, v.z)
	end

	local REASON = 'capture_mod'   -- our name for the time dilation and the save lock
	local HOLD = 0.0000001         -- the dilation that holds the world (the engine reports 1e-6; time stands still)
	local frozen = false
	local real_dt = 0
	local parked = nil             -- where the player stood before it was parked: { pos, yaw }
	local anchor = nil             -- world transform of the camera component's parent: { p, r, f, u }
	local hud_hidden = false
	local CLOCK_IN, CLOCK_OUT = ctx.dir .. '/clock.txt', ctx.dir .. '/clock_status.txt'   -- our clock plug-in (rtclock)
	local clock_held = false

	local player = Game.GetPlayer()
	local cam = player:GetFPPCameraComponent()
	local cs = Game.GetCameraSystem()
	local ts = Game.GetTimeSystem()
	local fov0 = cam.fov   -- the field of view it is set to (GetFOV is where its easing is right now)

	local function sim_time()
		return EngineTime.ToDouble(ts:GetSimTime())
	end

	-- While the session runs the player takes no movement or look input: the camera hangs on the
	-- player's head, so a nudged mouse would turn every pose.
	local restricted = 0
	for _, name in ipairs({ 'GameplayRestriction.NoCameraControl', 'GameplayRestriction.NoMovement' }) do
		local id = TweakDBID.new(name)
		if pcall(function() StatusEffectHelper.ApplyStatusEffect(player, id) end) then
			restricted = restricted + 1
			ctx.defer(function() pcall(function() StatusEffectHelper.RemoveStatusEffect(player, id) end) end)
		end
	end

	local function vec(x, y, z)
		return Vector4.new(x, y, z, 1.0)
	end

	-- What every answer carries. Each line is on its own: one failing call must not end the session.
	local function state_lines()
		local lines = { 'frozen=' .. (frozen and '1' or '0'), 'tick=' .. tostring(ctx.ticks()),
			string.format('real_dt=%.9g', real_dt), 'parked=' .. (parked and '1' or '0'),
			'hud_hidden=' .. (hud_hidden and '1' or '0'), 'restricted=' .. tostring(restricted),
			'rtclock_held=' .. (clock_held and '1' or '0') }
		local function add(key, fn)
			local ok, v = pcall(fn)
			if ok and v ~= nil then
				lines[#lines + 1] = key .. '=' .. tostring(v)
			end
		end
		add('player', function() return v3(player:GetWorldPosition()) end)
		add('player_heading', function() return string.format('%.9g', player:GetWorldYaw()) end)
		add('rendered_pos', function()
			local tr = Transform.new()   -- filled in place
			return cs:GetActiveCameraWorldTransform(tr) and v3(tr.position) or nil
		end)
		add('rendered_fwd', function() return v3(cs:GetActiveCameraForward()) end)
		add('rendered_right', function() return v3(cs:GetActiveCameraRight()) end)
		add('rendered_up', function() return v3(cs:GetActiveCameraUp()) end)
		add('rendered_fov', function() return string.format('%.9g', cs:GetActiveCameraFOV()) end)
		add('sim_time', function() return string.format('%.9f', sim_time()) end)
		add('dilation', function() return string.format('%.9g', ts:GetActiveTimeDilation()) end)
		add('clock', function()
			local t = ts:GetGameTime()
			return string.format('%02d:%02d', t:Hours(), t:Minutes())
		end)
		add('game_seconds', function()   -- the clock of day in seconds (for steps crossing a minute)
			local t = ts:GetGameTime()
			return string.format('%d', t:Hours() * 3600 + t:Minutes() * 60 + t:Seconds())
		end)
		add('paused', function() return Game.GetSystemRequestsHandler():IsGamePaused() and 1 or 0 end)
		add('menu', function()   -- the inventory, map, journal...: they hold the world and have their own camera
			local defs = GetAllBlackboardDefs().UI_System
			return Game.GetBlackboardSystem():Get(defs):GetBool(defs.IsInMenu) and 1 or 0
		end)
		add('saving_locked', function() return Game.IsSavingLocked() and 1 or 0 end)
		return lines
	end

	local function respond(seq, status, message, extra)
		local lines = { 'seq=' .. tostring(seq), 'status=' .. status, 'message=' .. ((message or ''):gsub('[\r\n]+', ' | ')) }
		for _, l in ipairs(extra or {}) do
			lines[#lines + 1] = l
		end
		for _, l in ipairs(state_lines()) do
			lines[#lines + 1] = l
		end
		local text = table.concat(lines, '\n') .. '\n'
		if not try_write(OUT, text) then
			out_pending = text
		end
	end

	local handlers = {}

	function handlers.state() end

	function handlers.wait(args, reply)
		ctx.after(math.max(1, math.floor(numbers(args)[1] or 1)), function() reply() end)
		return ASYNC
	end

	function handlers.capture(args, reply, fail)
		local stem = (args or ''):match('^(%S+)')
		ctx.capture(stem, function(ack, err)
			if not ack then
				return fail(err)
			end
			reply({ 'width=' .. tostring(ack.width), 'height=' .. tostring(ack.height),
				'file=jobs/' .. ctx.id .. '/' .. stem .. '.bmp' })
		end)
		return ASYNC
	end

	-- shoot n stem: let n frames pass, then capture (one round trip per shot).
	function handlers.shoot(args, reply, fail)
		local n, stem = (args or ''):match('^(%d+)%s+(%S+)$')
		ctx.after(math.max(1, tonumber(n) or 1), function()
			handlers.capture(stem, reply, fail)
		end)
		return ASYNC
	end

	-- freeze / unfreeze: hold the world at one instant. With the time dilation near zero the
	-- simulation time stands still (0 s over 60 frames, 2026-11-21) while frames render, scripts run,
	-- a moved camera component is followed and a teleport still takes effect.
	function handlers.freeze()
		ts:SetTimeDilation(REASON, HOLD)
		frozen = true
	end

	function handlers.unfreeze()
		ts:UnsetTimeDilation(REASON)
		frozen = false
	end
	ctx.defer(function() pcall(function() ts:UnsetTimeDilation(REASON) end) end)

	-- advance seconds [dilation] [tolerance]: let the world run for that much simulation time and
	-- hold it again. Every frame the time dilation is set so that the next frame covers a fifth of
	-- what is left (never more than `dilation`, 0.1 by default), so the world closes in on the
	-- target from below and is held within `tolerance` seconds of it (2e-6 by default). The real
	-- frame rate only sets how many frames that takes.
	function handlers.advance(args, reply)
		local a = numbers(args)
		local target = a[1] or (1 / 30)
		local dmax, tol = a[2] or 0.1, a[3] or 0.000002
		local s0 = sim_time()
		local frames = 0
		local function dilation(left)
			return math.min(dmax, math.max(left / (5 * math.max(real_dt, 0.002)), 0.000002))
		end
		ts:SetTimeDilation(REASON, dilation(target))
		local function tick()
			frames = frames + 1
			local left = target - (sim_time() - s0)
			if frames > 5000 then
				error('the world did not reach the time step: ' .. left .. ' s left after ' .. frames .. ' frames')
			end
			if left <= tol then
				ts:SetTimeDilation(REASON, HOLD)
				frozen = true
				return ctx.after(3, function()
					reply({ string.format('advanced_s=%.9f', sim_time() - s0), 'frames=' .. frames })
				end)
			end
			ts:SetTimeDilation(REASON, dilation(left))
			ctx.after(1, tick)
		end
		ctx.after(1, tick)
		return ASYNC
	end

	-- timepause 0|1: the time system's own paused state (what menus use), for probing what it stops
	-- that a near-zero time dilation does not.
	local time_paused = false
	ctx.defer(function()
		if time_paused then pcall(function() ts:SetPausedState(false, REASON) end) end
	end)
	function handlers.timepause(args)
		time_paused = (numbers(args)[1] or 1) ~= 0
		ts:SetPausedState(time_paused, REASON)
		return { 'time_paused=' .. tostring(ts:IsPausedState()) }
	end

	-- rtclock hold [scale] [mask] | run | state: the clock the game's own code reads (the real
	-- time), which video ads, holograms and blinking lights run on and a time dilation does not
	-- hold. Our clock plug-in (addons/clock, capture_clock.asi) holds it: scale is how fast it
	-- then runs (0: not at all), mask (hex) which clocks of which modules (for probing; all by
	-- default). The plug-in answers in clock_status.txt; its lines come back as clock_<key>.
	local function clock_lines(st)
		local lines = {}
		for k, v in pairs(st) do
			lines[#lines + 1] = 'clock_' .. k .. '=' .. v
		end
		return lines
	end
	-- The plug-in takes a command when clock.txt changes; its status file is rewritten after each
	-- one, so reading it while it is replaced can fail (a step sends a command every frame): the
	-- sequence number is read once and counted here after that.
	local clock_seq = nil
	local function clock_send(verb)
		if not clock_seq then
			local st = read_kv(CLOCK_OUT)
			if not st or not st.seq then
				error('the clock plug-in does not answer (no clock_status.txt): is capture_clock.asi installed?')
			end
			clock_seq = tonumber(st.seq) or 0
		end
		clock_seq = clock_seq + 1
		local seq = clock_seq
		local f = io.open(CLOCK_IN, 'w')
		if not f then
			error('cannot write clock.txt')
		end
		f:write(seq .. ' ' .. verb .. '\n')
		f:close()
		return seq
	end
	ctx.defer(function()
		if clock_held then
			pcall(clock_send, 'run')
		end
	end)
	function handlers.rtclock(args, reply, fail)
		local verb, rest = (args or ''):match('^(%S+)%s*(.*)$')
		if verb == 'state' then
			local st = read_kv(CLOCK_OUT)
			if not st then
				error('the clock plug-in does not answer (no clock_status.txt)')
			end
			return clock_lines(st)
		end
		if verb ~= 'hold' and verb ~= 'run' then
			error('rtclock hold [scale] [mask] | run | state')
		end
		local seq = clock_send(verb == 'hold' and ('hold ' .. (rest ~= '' and rest or '0')) or 'run')
		clock_held = verb == 'hold'
		local frames = 0
		local function check()
			local st = read_kv(CLOCK_OUT)
			if st and tonumber(st.seq) == seq then
				return reply(clock_lines(st))
			end
			frames = frames + 1
			if frames > 300 then
				return fail('the clock plug-in did not take "' .. verb .. '" within 300 frames')
			end
			ctx.after(1, check)
		end
		ctx.after(1, check)
		return ASYNC
	end

	-- step seconds hold_scale [tolerance]: a time step that moves the simulation and the clock our
	-- plug-in holds (screens, holograms, foliage, whatever the game runs on its own clock) by the
	-- same amount. The game's frame time follows that clock (world running with the clock at 0.1:
	-- 0.355 s of simulation in 3.5 s, Kabuki 2026-11-23), so here the time dilation is 1 and the
	-- clock alone is slowed, every frame to cover a fifth of what is left, down to hold_scale (the
	-- slowest the game tolerates); below that the dilation takes the last microseconds. Ends held:
	-- dilation HOLD, the clock at hold_scale. advance (above) instead slows only the simulation,
	-- with the clock released, so what runs on the clock moved 1.67 s per 1/30 s step.
	function handlers.step(args, reply, fail)
		local a = numbers(args)
		local target, floor, tol = a[1] or (1 / 30), a[2] or 0.0002, a[3] or 0.000002
		local s0 = sim_time()
		local frames, last = 0, nil
		local dts = {}   -- the last real frame times: a frame can take several times the one before
		local trace, s_prev = {}, s0   -- per frame: simulation advanced (ms), real frame (ms), clock scale
		local function set_clock(scale)
			local verb = string.format('hold %.9g', scale)
			if verb ~= last then
				clock_send(verb)
				last = verb
			end
		end
		clock_held = true
		local function tick()
			frames = frames + 1
			local now = sim_time()
			local left = target - (now - s0)
			if #trace < 400 then
				trace[#trace + 1] = string.format('%.3f/%.0f/%s', (now - s_prev) * 1000, real_dt * 1000, (last or ''):sub(6))
			end
			s_prev = now
			if frames > 5000 then
				return fail('the world did not reach the time step: ' .. left .. ' s left after ' .. frames .. ' frames')
			end
			if left <= tol then
				ts:SetTimeDilation(REASON, HOLD)
				frozen = true
				set_clock(floor)
				return ctx.after(3, function()
					reply({ string.format('advanced_s=%.9f', sim_time() - s0), 'frames=' .. frames, 'trace=' .. table.concat(trace, ' ') })
				end)
			end
			dts[frames % 4 + 1] = real_dt
			local dt_hi = 0.04
			for _, v in pairs(dts) do
				dt_hi = math.max(dt_hi, v)
			end
			-- an eighth of what is left over the longest of the last 4 frames, never faster than a
			-- twentieth of real time: a new scale takes effect a frame late (the per-frame trace),
			-- and a slow frame after quick ones overshot a step by up to 7 ms at a fifth and 1/4
			local want = left / (8 * dt_hi)   -- clock seconds per real second
			local scale = math.min(0.05, math.max(want, floor))
			set_clock(scale)
			ts:SetTimeDilation(REASON, math.max(math.min(1, want / scale), 0.000002))
			ctx.after(1, tick)
		end
		ts:SetTimeDilation(REASON, HOLD)
		set_clock(floor)
		ctx.after(1, tick)
		return ASYNC
	end

	-- hud 0|1: the whole HUD (minimap, quest tracker, calls, hints) off or on, through the UI's
	-- "Empty" game context.
	local EMPTY = Enum.new('UIGameContext', 12)
	local function set_hud(visible)
		if visible == not hud_hidden then
			return
		end
		if visible then
			Game.GetUISystem():PopGameContext(EMPTY)
		else
			Game.GetUISystem():PushGameContext(EMPTY)
		end
		hud_hidden = not visible
	end
	ctx.defer(function() pcall(set_hud, true) end)
	function handlers.hud(args)
		set_hud((numbers(args)[1] or 1) ~= 0)
	end

	-- park depth / unpark: the player out of every camera. Its body cannot be hidden from here
	-- (SetInvisible only hides it from other characters), so while the world is held it is moved
	-- straight down under the ground; a teleport takes effect in a held world. The camera component
	-- hangs on the player, so anchor must follow.
	local function teleport(x, y, z, yaw)
		Game.GetTeleportationFacility():Teleport(player, vec(x, y, z), EulerAngles.new(0, 0, yaw))
	end
	function handlers.park(args, reply)
		if not frozen then
			error('park needs a held world (freeze first): a running world lets the player fall')
		end
		local depth = numbers(args)[1] or 12
		if not parked then
			local pos = player:GetWorldPosition()
			parked = { x = pos.x, y = pos.y, z = pos.z, yaw = player:GetWorldYaw() }
		end
		parked.depth = depth
		teleport(parked.x, parked.y, parked.z - depth, parked.yaw)
		anchor = nil
		ctx.after(3, function() reply() end)
		return ASYNC
	end
	local function unpark()
		if parked then
			teleport(parked.x, parked.y, parked.z, parked.yaw)
			parked = nil
			anchor = nil
		end
	end
	ctx.defer(function() pcall(unpark) end)
	function handlers.unpark(_, reply)
		unpark()
		ctx.after(3, function() reply() end)
		return ASYNC
	end

	-- anchor: find the world transform of the camera component's parent. The component is placed
	-- relative to its parent (the player's head: it follows the body and the view pitch), so with
	-- its own offset zeroed its world matrix is the parent's. pose then places it relative to that.
	-- The parent stands still while the world is held; anchor again after anything moves the player.
	local function reset_camera()
		cam:SetLocalTransform(vec(0, 0, 0), Quaternion.new(0, 0, 0, 1))
	end
	ctx.defer(function()
		pcall(reset_camera)
		pcall(function() cam:SetFOV(fov0) end)
	end)
	function handlers.anchor(_, reply)
		reset_camera()
		ctx.after(3, function()
			local m = cam:GetLocalToWorld()
			anchor = { p = { m.W.x, m.W.y, m.W.z }, r = { m.X.x, m.X.y, m.X.z }, f = { m.Y.x, m.Y.y, m.Y.z },
				u = { m.Z.x, m.Z.y, m.Z.z } }
			reply({ 'anchor_pos=' .. v3(m.W), 'anchor_right=' .. v3(m.X), 'anchor_fwd=' .. v3(m.Y), 'anchor_up=' .. v3(m.Z) })
		end)
		return ASYNC
	end

	-- pose x y z  rx ry rz  fx fy fz  ux uy uz  fov: the camera at a world position with world axes
	-- right, forward, up, and a vertical field of view in degrees.
	local function dot(a, b)
		return a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
	end
	-- (i, j, k, r) of the rotation whose matrix has these columns
	local function quat(c1, c2, c3)
		local m11, m21, m31 = c1[1], c1[2], c1[3]
		local m12, m22, m32 = c2[1], c2[2], c2[3]
		local m13, m23, m33 = c3[1], c3[2], c3[3]
		local t = m11 + m22 + m33
		if t > 0 then
			local s = math.sqrt(t + 1) * 2
			return (m32 - m23) / s, (m13 - m31) / s, (m21 - m12) / s, s / 4
		elseif m11 > m22 and m11 > m33 then
			local s = math.sqrt(1 + m11 - m22 - m33) * 2
			return s / 4, (m12 + m21) / s, (m13 + m31) / s, (m32 - m23) / s
		elseif m22 > m33 then
			local s = math.sqrt(1 + m22 - m11 - m33) * 2
			return (m12 + m21) / s, s / 4, (m23 + m32) / s, (m13 - m31) / s
		end
		local s = math.sqrt(1 + m33 - m11 - m22) * 2
		return (m13 + m31) / s, (m23 + m32) / s, s / 4, (m21 - m12) / s
	end
	function handlers.pose(args)
		local a = numbers(args)
		if #a < 13 then
			error('pose needs x y z, right, forward, up (3 numbers each) and fov')
		end
		if not anchor then
			error('pose needs anchor first')
		end
		local A = anchor
		local d = { a[1] - A.p[1], a[2] - A.p[2], a[3] - A.p[3] }
		local function to_parent(w)
			return { dot(w, A.r), dot(w, A.f), dot(w, A.u) }
		end
		local lp = to_parent(d)
		local i, j, k, r = quat(to_parent({ a[4], a[5], a[6] }), to_parent({ a[7], a[8], a[9] }),
			to_parent({ a[10], a[11], a[12] }))
		cam:SetLocalTransform(vec(lp[1], lp[2], lp[3]), Quaternion.new(i, j, k, r))
		cam:SetFOV(a[13])
	end

	-- fov v: the vertical field of view the camera eases towards (degrees). It arrives after about
	-- a second of world time, so never in a held world (adapters/cyberpunk/fov.py writes it there).
	function handlers.fov(args)
		cam:SetFOV(numbers(args)[1])
	end

	-- teleport x y z yaw [max_frames]: move the player and wait until the ground under the spot is
	-- there (collision has loaded) on 5 checks in a row.
	-- Built ground is in the collision group 'Static', open land in 'Terrain' (the Badlands' dirt
	-- is not 'Static'): the higher of the two hits below the start is the ground.
	local function ground_under(x, y, z, above, below)
		local a, b = vec(x, y, z + (above or 2.0)), vec(x, y, z - (below or 30.0))
		local best = nil
		for _, group in ipairs({ 'Static', 'Terrain' }) do
			local hit, res = Game.GetSpatialQueriesSystem():SyncRaycastByCollisionGroup(a, b, group, false, false)
			if hit and (not best or res.position.z > best) then
				best = res.position.z
			end
		end
		return best
	end
	function handlers.teleport(args, reply)
		local a = numbers(args)
		if #a < 3 then
			error('teleport needs x y z [yaw] [max_frames]')
		end
		local x, y, z, yaw, max_frames = a[1], a[2], a[3], a[4] or 0, a[5] or 3600
		parked, anchor = nil, nil
		teleport(x, y, z, yaw)
		-- A long jump puts up a loading screen, behind which the world does not run: loaded means
		-- the ground is there on 5 checks in a row and the simulation clock has run 0.5 s since.
		local frames, good, s_good = 0, 0, nil
		local function check()
			frames = frames + 10
			local pos = player:GetWorldPosition()
			local near = math.abs(pos.x - x) < 2 and math.abs(pos.y - y) < 2
			local gz = near and ground_under(x, y, z)
			good = gz and (good + 1) or 0
			if good == 0 then
				s_good = nil
			elseif not s_good then
				s_good = sim_time()
			end
			local running = frozen or (s_good and sim_time() - s_good >= 0.5)
			local loaded = good >= 5 and running and frames >= 60
			if loaded or frames >= max_frames then
				return reply({ 'loaded=' .. tostring(loaded and true or false), 'frames=' .. frames,
					'ground_found=' .. tostring(gz ~= nil), string.format('ground_z=%.9g', gz or z) })
			end
			ctx.after(10, check)
		end
		ctx.after(10, check)
		return ASYNC
	end

	-- ground x y z: height of the ground below a point.
	function handlers.ground(args)
		local a = numbers(args)
		local gz = ground_under(a[1], a[2], a[3])
		return { 'ground_found=' .. tostring(gz ~= nil), string.format('ground_z=%.9g', gz or a[3]) }
	end

	-- clock h m: set the time of day.
	function handlers.clock(args)
		local a = numbers(args)
		ts:SetGameTimeByHMS(math.floor(a[1] or 12), math.floor(a[2] or 0), 0)
		local t = ts:GetGameTime()
		return { string.format('clock=%02d:%02d', t:Hours(), t:Minutes()) }
	end

	-- project x y z: where the engine puts a world point on screen (its own units, as returned).
	function handlers.project(args)
		local a = numbers(args)
		local s = cs:ProjectPoint(vec(a[1], a[2], a[3]))
		return { string.format('screen=%.9g %.9g %.9g %.9g', s.x, s.y, s.z, s.w) }
	end

	-- settings get | settings set: read or set game settings listed in exchange/settings_in.txt, one
	-- per line "group name value" with the names the game's settings system uses (e.g.
	-- "/video/display WindowMode Windowed"). Answers s<n>=<group> <name> <the value now, or why
	-- not>, how many changed, and whether the game wants a restart for them.
	-- Reading is the normal use: the installer writes the capture settings into the game's
	-- settings file while the game is closed. Setting them here crashed the game the second time
	-- it changed the renderer in a running world (2026-11-21), and they were not written to the file.
	function handlers.settings(args)
		local read_only = not (args or ''):match('set')
		local ss = Game.GetSettingsSystem()
		local out, n, changed = {}, 0, 0
		local f = assert(io.open(ctx.dir .. '/settings_in.txt', 'r'), 'no settings_in.txt in the exchange folder')
		for line in f:lines() do
			local group, name, value = line:match('^(%S+)%s+(%S+)%s+(.-)%s*$')
			if group then
				n = n + 1
				local ok, now = pcall(function()
					local v = ss:GetVar(group, name)
					if not v then
						return '(no such setting)'
					end
					local cls = tostring(v:GetClassName().value)
					if cls:find('List') then
						local idx
						for i, x in ipairs(v:GetValues()) do
							if tostring(type(x) == 'userdata' and x.value or x) == value then
								idx = i - 1
							end
						end
						if read_only then
							local x = v:GetValues()[v:GetIndex() + 1]
							return tostring(type(x) == 'userdata' and x.value or x)
						end
						if idx == nil then
							return '(not one of its values)'
						end
						if v:GetIndex() ~= idx then
							v:SetIndex(idx)
							changed = changed + 1
						end
						return value
					end
					local want = value
					if cls:find('Bool') then
						want = value == 'true'
					elseif tonumber(value) then
						want = tonumber(value)
					end
					if not read_only and v:GetValue() ~= want then
						v:SetValue(want)
						changed = changed + 1
					end
					local now = v:GetValue()
					return type(now) == 'number' and string.format('%.6g', now) or tostring(now)
				end)
				out[#out + 1] = string.format('s%d=%s %s %s', n, group, name, ok and now or ('(error: ' .. tostring(now) .. ')'))
			end
		end
		f:close()
		if changed > 0 then
			pcall(function() ss:ConfirmChanges() end)
			pcall(function() Game.GetSystemRequestsHandler():RequestSaveUserSettings() end)
		end
		out[#out + 1] = 'settings_count=' .. n
		out[#out + 1] = 'settings_changed=' .. changed
		out[#out + 1] = 'needs_restart=' .. tostring(select(2, pcall(function() return ss:NeedsRestartToApply() end)))
		return out
	end

	-- option get <category> <key> | option set <category> <key> <value>: an engine option (the ones
	-- Cyber Engine Tweaks lists with GameOptions.Dump), e.g. Rendering ForcedExposureAvgLum. Every
	-- option set here goes back to what it was when the session ends.
	local option_was = {}
	ctx.defer(function()
		for id, o in pairs(option_was) do
			pcall(o.put, o.value)
		end
	end)
	function handlers.option(args)
		local what, category, key, value = (args or ''):match('^(%S+)%s+(%S+)%s+(%S+)%s*(%S*)')
		if not key then
			error('option needs get|set, a category and a key')
		end
		if what == 'set' then
			local put
			if value == 'true' or value == 'false' then
				put = function(v) GameOptions.SetBool(category, key, v == 'true') end
			elseif value:match('^%-?%d+$') then
				put = function(v) GameOptions.SetInt(category, key, tonumber(v)) end
			else
				put = function(v) GameOptions.SetFloat(category, key, tonumber(v)) end
			end
			local id = category .. '/' .. key
			if not option_was[id] then
				option_was[id] = { value = tostring(GameOptions.Get(category, key)), put = put }
			end
			put(value)
		end
		return { 'option=' .. tostring(GameOptions.Get(category, key)) }
	end

	-- weather NAME [blend seconds] | weather free | weather state: set and hold a weather type
	-- (24h_weather_sunny, _light_clouds, _cloudy, _heavy_clouds, _fog, _rain, _toxic_rain,
	-- _pollution, _sandstorm), let the game choose again, or just report it. These calls are
	-- Codeware's: patch 2.5 took SetWeather out of the game's own script interface.
	function handlers.weather(args)
		local ws = Game.GetWeatherSystem()
		local name, blend = (args or ''):match('^(%S+)%s*(%S*)')
		if name == 'free' then
			ws:ResetWeather(true, 0.0)
		elseif name and name ~= 'state' then
			-- its return value is false also when the weather is already that one; the caller
			-- checks the state it answers with
			ws:SetWeather(name, tonumber(blend) or 0.0, 9)
		end
		local st = ws:GetWeatherState()
		return { 'weather=' .. tostring(st and st.name.value) }
	end

	-- devices off [radius] | devices on: switch off the devices around the player that are on
	-- (screens, terminals, vending machines, traffic and crossing lights; not doors or lifts), and
	-- switch those back on. Their screens, holograms and blinking lights run on real time, so in
	-- a held world they differ from one shot to the next; off, they are dark and still. Screens
	-- that are part of the map rather than devices are not reached (2026-11-21: the market's two
	-- hanging screens and its hologram tree kept playing).
	local switched_off = {}
	local function devices_on()
		local n = 0
		for _, e in ipairs(switched_off) do
			if pcall(function() e:GetDevicePS():ForceEnableDevice() end) then
				n = n + 1
			end
		end
		switched_off = {}
		return n
	end
	ctx.defer(function() pcall(devices_on) end)
	function handlers.devices(args, reply)
		local what, radius = (args or ''):match('^(%S+)%s*(%S*)')
		if what == 'on' then
			local n = devices_on()
			ctx.after(5, function() reply({ 'devices_on=' .. n }) end)
			return ASYNC
		end
		local seen = 0
		for _, e in ipairs(player:GetEntitiesAroundObject(tonumber(radius) or 60)) do
			if select(2, pcall(function() return e:IsDevice() end)) == true then
				local class = tostring(e:GetClassName().value)
				local on = select(2, pcall(function() return e:GetDevicePS():IsON() end)) == true
				seen = seen + 1
				if on and not (class:find('Door') or class:find('Elevator') or class:find('Lift')) then
					-- the device's own TurnOffDevice leaves it on; its state's ForceDisableDevice works,
					-- and ForceEnableDevice brings it back (2026-11-21: 14 screens off, then on)
					if pcall(function() e:GetDevicePS():ForceDisableDevice() end) then
						switched_off[#switched_off + 1] = e
					end
				end
			end
		end
		ctx.after(30, function()
			local still = 0
			for _, e in ipairs(switched_off) do
				if select(2, pcall(function() return e:GetDevicePS():IsON() end)) == true then
					still = still + 1
				end
			end
			reply({ 'devices_seen=' .. seen, 'devices_off=' .. #switched_off, 'devices_still_on=' .. still })
		end)
		return ASYNC
	end

	-- obstacles x y z radius: every character and vehicle within radius of a point, one answer
	-- line each, as an oriented box:
	--   o<n>=<kind>|<quest 0/1>|<centre x y z>|<right x y z>|<forward x y z>|<up x y z>|<half a b c>
	-- The boxes are stock sizes around the entity's position and axes (its real bounds are not
	-- open to scripts). The entities are kept for `remove` until the next obstacles call.
	local SIZES = { human = { half = { 0.35, 0.35, 0.92 }, lift = 0.92 }, vehicle = { half = { 1.3, 3.0, 1.0 }, lift = 0.9 } }
	local listed = {}
	function handlers.obstacles(args)
		local a = numbers(args)
		local r = a[4] or 30
		-- entities are listed around the player, which may be parked under the point
		local pp = player:GetWorldPosition()
		local reach = r + math.sqrt((pp.x - a[1]) ^ 2 + (pp.y - a[2]) ^ 2 + (pp.z - a[3]) ^ 2)
		listed = {}
		local out = {}
		for _, e in ipairs(player:GetEntitiesAroundObject(reach)) do
			local kind = nil
			if select(2, pcall(function() return e:IsVehicle() end)) == true then
				kind = 'vehicle'
			elseif select(2, pcall(function() return e:IsNPC() end)) == true then
				kind = 'human'
			end
			if kind then
				local p = e:GetWorldPosition()
				if (p.x - a[1]) ^ 2 + (p.y - a[2]) ^ 2 + (p.z - a[3]) ^ 2 <= r * r then
					local R, F, U = e:GetWorldRight(), e:GetWorldForward(), e:GetWorldUp()
					local s = SIZES[kind]
					local quest = select(2, pcall(function() return e:IsQuest() end)) == true
					listed[#listed + 1] = { e = e, kind = kind, quest = quest }
					out[#out + 1] = string.format('o%d=%s|%d|%.4f %.4f %.4f|%s|%s|%s|%.3f %.3f %.3f', #listed, kind,
						quest and 1 or 0, p.x + U.x * s.lift, p.y + U.y * s.lift, p.z + U.z * s.lift, v3(R), v3(F), v3(U),
						s.half[1], s.half[2], s.half[3])
				end
			end
		end
		out[#out + 1] = 'obstacle_count=' .. #listed
		return out
	end

	-- remove n n ...: take listed obstacles out of the scene: moved far under the ground (which
	-- takes effect in a held world) and disposed of. Quest characters and vehicles are never
	-- touched; answer lines removed=<count>, skipped=<n,n,...>.
	function handlers.remove(args, reply)
		local removed, skipped = 0, {}
		for _, n in ipairs(numbers(args)) do
			local item = listed[n]
			if item then
				if item.quest then
					skipped[#skipped + 1] = tostring(n)
				else
					local e = item.e
					pcall(function()
						local p = e:GetWorldPosition()
						Game.GetTeleportationFacility():Teleport(e, vec(p.x, p.y, p.z - 300.0), EulerAngles.new(0, 0, e:GetWorldYaw()))
					end)
					pcall(function() e:Dispose() end)
					removed = removed + 1
				end
			end
		end
		ctx.after(3, function()
			reply({ 'removed=' .. removed, 'skipped=' .. table.concat(skipped, ',') })
		end)
		return ASYNC
	end

	-- raycast [per_frame]: line probes for the scene around a location. Reads rays_in.txt in the
	-- exchange folder, one ray per line "x1 y1 z1 x2 y2 z2"; writes rays_out.txt, one line per ray,
	-- "1 x y z nx ny nz" (hit point, surface normal) or "0". A ray stops at built things ('Static')
	-- or open land ('Terrain'), whichever is nearer; not at characters or vehicles.
	function handlers.raycast(args, reply)
		local per_frame = math.floor(numbers(args)[1] or 3000)
		local rays = {}
		for line in assert(io.open(ctx.dir .. '/rays_in.txt', 'r')):lines() do
			local a = numbers(line)
			if #a >= 6 then
				rays[#rays + 1] = a
			end
		end
		local sq = Game.GetSpatialQueriesSystem()
		local fout = assert(io.open(ctx.dir .. '/rays_out.txt.tmp', 'w'))
		local i, nhit, t0 = 0, 0, os.clock()
		local function chunk()
			local stop = math.min(i + per_frame, #rays)
			while i < stop do
				i = i + 1
				local a = rays[i]
				local from, to = vec(a[1], a[2], a[3]), vec(a[4], a[5], a[6])
				local best, bd = nil, nil
				for _, group in ipairs({ 'Static', 'Terrain' }) do
					local hit, res = sq:SyncRaycastByCollisionGroup(from, to, group, false, false)
					if hit then
						local p = res.position
						local d = (p.x - a[1]) ^ 2 + (p.y - a[2]) ^ 2 + (p.z - a[3]) ^ 2
						if not bd or d < bd then
							best, bd = res, d
						end
					end
				end
				if best then
					nhit = nhit + 1
					fout:write(string.format('1 %.4f %.4f %.4f %.4f %.4f %.4f\n', best.position.x, best.position.y,
						best.position.z, best.normal.x, best.normal.y, best.normal.z))
				else
					fout:write('0\n')
				end
			end
			if i < #rays then
				return ctx.after(1, chunk)
			end
			fout:close()
			os.remove(ctx.dir .. '/rays_out.txt')
			os.rename(ctx.dir .. '/rays_out.txt.tmp', ctx.dir .. '/rays_out.txt')
			reply({ 'rays=' .. #rays, 'hits=' .. nhit, string.format('cpu_s=%.2f', os.clock() - t0) })
		end
		chunk()
		return ASYNC
	end

	-- people radius: every character within radius of the player, one answer line each,
	-- e<n>=<entity id hash>|<x y z>, to check that a held world stays as it is.
	function handlers.people(args)
		local list = player:GetNPCsAroundObject(numbers(args)[1] or 60)
		local out = {}
		for n, e in ipairs(list) do
			out[#out + 1] = string.format('e%d=%s|%s', n, tostring(e:GetEntityID().hash), v3(e:GetWorldPosition()))
		end
		out[#out + 1] = 'people_count=' .. #list
		return out
	end

	-- eval: runs exchange/eval_in.lua with a few helpers in scope, for finding out how the game's
	-- script API behaves. E is a table that lasts for the session; out(...) adds a line to the answer;
	-- after(frames, fn) runs fn later; a chunk that returns ASYNC answers when it calls done().
	local E = {}
	function handlers.eval(_, reply, fail)
		local f = io.open(ctx.dir .. '/eval_in.lua', 'r')
		if not f then
			error('no eval_in.lua in the exchange folder')
		end
		local code = f:read('*a')
		f:close()
		local lines = {}
		local function out(...)
			local parts = {}
			for i = 1, select('#', ...) do
				parts[#parts + 1] = tostring((select(i, ...)))
			end
			lines[#lines + 1] = table.concat(parts, ' ')
		end
		local finished = false
		local function done(...)
			if finished then
				return
			end
			finished = true
			if select('#', ...) > 0 then
				out(...)
			end
			local of = io.open(ctx.dir .. '/eval_out.txt', 'w')
			if of then
				of:write(table.concat(lines, '\n') .. '\n')
				of:close()
			end
			reply({ 'eval_lines=' .. #lines })
		end
		local chunk, err = loadstring('local E, ctx, out, after, done, ASYNC, state_lines = ...\n' .. code, 'eval')
		if not chunk then
			error('eval_in.lua does not compile: ' .. tostring(err))
		end
		local res = { pcall(chunk, E, ctx, out, ctx.after, done, ASYNC, state_lines) }
		if not res[1] then
			out('ERROR: ' .. tostring(res[2]))
			done()
			return ASYNC
		end
		if res[2] == ASYNC then
			return ASYNC
		end
		for i = 2, #res do
			out(res[i])
		end
		done()
		return ASYNC
	end

	-- While this file is fresh, other scripts stay off the screen.
	local ACTIVE = ctx.dir .. '/session_active.txt'
	local function mark_active()
		local f = io.open(ACTIVE, 'w')
		if f then
			f:write(tostring(os.time()))
			f:close()
		end
	end
	ctx.defer(function() os.remove(ACTIVE) end)
	ctx.defer(function() os.remove(IN) end)
	mark_active()

	os.remove(IN)
	respond(0, 'ok', 'ready')
	ctx.log('session ready')

	local last_seq = 0
	local busy = nil            -- seq of the command still running
	local idle_deadline = os.time() + IDLE_TIMEOUT_S
	local tick = 0

	-- an error in a function a command left for later answers that command
	ctx.on_error = function(message)
		if busy then
			local seq = busy
			busy = nil
			respond(seq, 'error', message)
		else
			ctx.log('error outside a command: %s', message)
		end
	end

	ctx.each_tick = function(dt)
		real_dt = dt or 0
		tick = tick + 1
		if tick % 60 == 0 then
			mark_active()
		end
		if out_pending and try_write(OUT, out_pending) then
			out_pending = nil
		end
		if E.each_tick then
			local ok, err = pcall(E.each_tick, dt)
			if not ok then
				E.each_tick = nil
				ctx.log('E.each_tick failed and was removed: %s', tostring(err))
			end
		end
		if busy then
			return
		end
		local req = read_kv(IN)
		local seq = req and tonumber(req.seq)
		if seq and seq > last_seq then
			last_seq = seq
			idle_deadline = os.time() + IDLE_TIMEOUT_S
			local cmd = req.cmd or ''
			if cmd == 'end' then
				respond(seq, 'ok', 'ending')
				ctx.finish('ok', '')
				return
			end
			local h = handlers[cmd]
			if not h then
				respond(seq, 'error', 'unknown command ' .. cmd)
				return
			end
			busy = seq
			local function reply(lines)
				if busy == seq then
					busy = nil
					idle_deadline = os.time() + IDLE_TIMEOUT_S
					respond(seq, 'ok', '', lines)
				end
			end
			local function fail(message)
				if busy == seq then
					busy = nil
					respond(seq, 'error', tostring(message))
				end
			end
			local ok, res = pcall(h, req.args, reply, fail)
			if not ok then
				fail(res)
			elseif res ~= ASYNC then
				reply(res)
			end
		elseif os.time() > idle_deadline then
			ctx.finish('error', 'no command for ' .. IDLE_TIMEOUT_S .. ' s')
		end
	end
end
