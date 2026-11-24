-- Interactive camera session for GTA V, driven from outside (adapters/gtav/adapter.py through
-- adapters/common/redlua.py). The same protocol as RDR2's session job:
--
-- The outside tool writes session_in.txt in the exchange folder:
--   seq=<n>
--   cmd=<command>
--   args=<space separated numbers or a name>
-- This job runs the command and writes session_out.txt with the same seq, status=ok|error,
-- message, any answer lines, and the current state (player, rendered camera, game timer, health).
--
-- Commands:
--   pose x y z pitch roll yaw fov   the script camera (rotation order 2, degrees, vertical FoV)
--   freeze [method] / unfreeze      hold the world at one instant (method: timescale | paused | both)
--   advance s [scale]               release at a reduced time scale for s seconds, freeze again
--   wait n, capture stem, shoot n stem, state, end
--   teleport x y z h [ticks] [hold], ground x y z, focus x y z|clear, park x y z, hold 0|1
--   player_visible 0|1, ghost 0|1, clock h m, weather NAME|hold|free|state, place x y z
--   obstacles x y z r, remove n n ..., raycast [flags] [per_tick], population x y z, project x y z
return function(ctx)
	local IN = ctx.out_dir .. '\\session_in.txt'
	local OUT = ctx.out_dir .. '\\session_out.txt'
	local IDLE_TIMEOUT_S = tonumber(ctx.args.idle_s) or 300

	-- SET_THIS_SCRIPT_CAN_BE_PAUSED is left alone: Script Hook V's scripts are not game script
	-- threads (suspected in two faults inside lua51.dll, 2026-11-21), and they keep running while
	-- the game is paused anyway (the pause/frames step needs that).
	if ctx.args.can_be_paused == '0' then
		ctx.try('MISC', 'SET_THIS_SCRIPT_CAN_BE_PAUSED', false)
	end

	-- The HUD, radar, notification feed and help text are hidden one frame at a time, so on every
	-- tick, also while a command waits or a capture is pending (a shot's settle showed the minimap
	-- and a notification otherwise, 2026-11-21).
	-- The population multipliers (density command) are per frame too.
	local hide_hud = ctx.args.hide_hud ~= '0'
	local density = nil   -- { people, traffic } multipliers, or nil for the game's own
	ctx.each_tick = function()
		if hide_hud then
			pcall(native.call, 'HUD', 'HIDE_HUD_AND_RADAR_THIS_FRAME')
			pcall(native.call, 'HUD', 'THEFEED_HIDE_THIS_FRAME')
			pcall(native.call, 'HUD', 'HIDE_HELP_TEXT_THIS_FRAME')
		end
		if density then
			pcall(native.call, 'PED', 'SET_PED_DENSITY_MULTIPLIER_THIS_FRAME', density[1])
			pcall(native.call, 'PED', 'SET_SCENARIO_PED_DENSITY_MULTIPLIER_THIS_FRAME', density[1], density[1])
			pcall(native.call, 'VEHICLE', 'SET_VEHICLE_DENSITY_MULTIPLIER_THIS_FRAME', density[2])
			pcall(native.call, 'VEHICLE', 'SET_RANDOM_VEHICLE_DENSITY_MULTIPLIER_THIS_FRAME', density[2])
			pcall(native.call, 'VEHICLE', 'SET_PARKED_VEHICLE_DENSITY_MULTIPLIER_THIS_FRAME', density[2])
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

	-- A Hash argument as a RedLua object: RedLua passes plain Lua numbers through a float, which
	-- changes any hash above 2^24 (BACKLOG.md: the RedLua float bug). An object is pushed as is.
	local function hash_arg(v)
		local o = native.new('Hash', 1)
		o[0] = v
		return o
	end

	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local pid = ctx.call('PLAYER', 'PLAYER_ID')
	local cam = nil
	local frozen = false
	local freeze_method = ctx.args.freeze or 'timescale'
	local held = false -- player position frozen (hold, teleport, park)

	-- An entity's identity as text. An element of a native.allpeds/allvehicles pool prints as the
	-- address of its slot ("Entity*: 0x..."), which another entity takes on the next call; the
	-- index natives give a value-typed handle, which prints as "Ped: 1234" / "Vehicle: 5678".
	local function value_of(e, kind)
		local ok, h
		if kind == 'vehicle' or kind == 'vehicles' then
			ok, h = ctx.try('ENTITY', 'GET_VEHICLE_INDEX_FROM_ENTITY_INDEX', e)
		else
			ok, h = ctx.try('ENTITY', 'GET_PED_INDEX_FROM_ENTITY_INDEX', e)
		end
		return ok and h or e
	end
	local function handle_of(e, kind)
		return tostring(value_of(e, kind))
	end

	-- people this session spawned (crowd): its own, so obstacles reports them as not owned and
	-- remove may delete them; released to the game when the session ends. Keyed by handle_of.
	local spawned = {}
	local kept = {}   -- handles of the ambient people and vehicles `keep` made the session's own
	ctx.defer(function()
		for h, p in pairs(spawned) do
			if kept[h] then
				local ref = native.new('Entity', 1)
				ref[0] = p
				pcall(native.call, 'ENTITY', 'SET_ENTITY_AS_NO_LONGER_NEEDED', ref)
			else
				local ref = native.new('Ped', 1)
				ref[0] = p
				pcall(native.call, 'ENTITY', 'SET_PED_AS_NO_LONGER_NEEDED', ref)
			end
		end
	end)

	local function render(on)
		-- p5 is typed Any; RedLua may only take a typed pointer there
		if not pcall(native.call, 'CAM', 'RENDER_SCRIPT_CAMS', on, false, 0, true, false, 0) then
			native.call('CAM', 'RENDER_SCRIPT_CAMS', on, false, 0, true, false, native.new('Any', 1))
		end
	end

	local function set_frozen(on, method)
		method = method or freeze_method
		if method == 'timescale' or method == 'both' then
			ctx.call('MISC', 'SET_TIME_SCALE', on and 0.0 or 1.0)
		end
		if method == 'paused' or method == 'both' then
			ctx.call('MISC', 'SET_GAME_PAUSED', on)
		end
		frozen = on
	end

	ctx.defer(function()
		pcall(native.call, 'MISC', 'SET_GAME_PAUSED', false)
		pcall(native.call, 'MISC', 'SET_TIME_SCALE', 1.0)
		if cam then
			pcall(render, false)
			native.call('CAM', 'SET_CAM_ACTIVE', cam, false)
			native.call('CAM', 'DESTROY_CAM', cam, false)
		end
		os.remove(IN)
	end)

	-- Where a point is, as numbers: the map zone's index, the hash of its code and the street's name
	-- hash. Names would need the game's strings, which RedLua returns as raw pointers; reading one
	-- through LuaJIT's ffi faulted inside lua51.dll twice (2026-11-21), and Script Hook V then closes
	-- the game. The zone code's pointer goes straight back into GET_HASH_KEY instead, which reads it
	-- inside the game (adapters/gtav/zones.py names the hash).
	local street, crossing = native.new('Hash', 1), native.new('Hash', 1)
	local function place_ids(x, y, z)
		local _, zone = ctx.try('ZONE', 'GET_ZONE_AT_COORDS', x, y, z)
		local zone_hash = 0
		local okn, code = ctx.try('ZONE', 'GET_NAME_OF_ZONE', x, y, z)
		if okn and code then
			local okh, h = ctx.try('MISC', 'GET_HASH_KEY', code)
			if okh and h then zone_hash = h end
		end
		street[0] = 0
		ctx.try('PATHFIND', 'GET_STREET_NAME_AT_COORD', x, y, z, street, crossing)
		return { 'place_zone=' .. tostring(zone), 'place_zone_hash=' .. tostring(zone_hash),
			'place_street=' .. tostring(street[0]) }
	end

	local function state_lines()
		local p = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true)
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
			'frame_count=' .. tostring(ctx.call('MISC', 'GET_FRAME_COUNT')),
			string.format('frame_time=%.9g', ctx.call('MISC', 'GET_FRAME_TIME')),
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
		local okw, wanted = ctx.try('PLAYER', 'GET_PLAYER_WANTED_LEVEL', pid)
		if okw then
			lines[#lines + 1] = 'wanted=' .. tostring(wanted)
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
		if #a < 7 then
			error('pose needs x y z pitch roll yaw fov')
		end
		if not cam then
			cam = ctx.call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
			ctx.call('CAM', 'SET_CAM_ACTIVE', cam, true)
			render(true)
		end
		ctx.call('CAM', 'SET_CAM_COORD', cam, a[1], a[2], a[3])
		ctx.call('CAM', 'SET_CAM_ROT', cam, a[4], a[5], a[6], 2)
		ctx.call('CAM', 'SET_CAM_FOV', cam, a[7])
	end

	function handlers.freeze(args)
		local m = (args or ''):match('^(%a+)')
		if m then
			freeze_method = m
		end
		set_frozen(true)
		return { 'freeze_method=' .. freeze_method }
	end

	function handlers.unfreeze()
		set_frozen(false)
		ctx.call('MISC', 'SET_TIME_SCALE', 1.0)
	end

	-- Exact time steps (adapters/gtav/timestep.py). At time scale 0 every frame advances the world
	-- by the engine's minimum step, which the adapter sets from outside; the game's pause stops
	-- frames from advancing at all, between two frames, while this script keeps running. A step:
	--   pause 1                 hold here (no frame advances), so the outside can set the step size
	--   frames n                let exactly n frames run (each one minimum step), then pause again
	--   pause 0                 render again, the world held by a tiny minimum step
	-- (LuaJIT's ffi cannot write the step itself: an absolute address faulted in lua51.dll.)
	function handlers.pause(args)
		local on = (numbers(args)[1] or 1) ~= 0
		ctx.call('MISC', 'SET_GAME_PAUSED', on)
		ctx.wait(2)
		return { 'paused=' .. (on and '1' or '0') }
	end
	ctx.defer(function() pcall(native.call, 'MISC', 'SET_GAME_PAUSED', false) end)

	function handlers.frames(args)
		local n = math.max(1, math.floor(numbers(args)[1] or 1))
		local t0 = ctx.call('MISC', 'GET_GAME_TIMER')
		local f0 = ctx.call('MISC', 'GET_FRAME_COUNT')
		local acc, dts, done, ticks = 0.0, {}, 0, 0
		ctx.call('MISC', 'SET_GAME_PAUSED', false)
		while done < n and ticks < n * 20 + 200 do
			ctx.wait(1)
			ticks = ticks + 1
			local fc = ctx.call('MISC', 'GET_FRAME_COUNT')
			if fc - f0 > done then
				done = fc - f0
				local dt = ctx.call('MISC', 'GET_FRAME_TIME')
				acc = acc + dt
				dts[#dts + 1] = string.format('%.7f', dt)
				if done >= n then
					ctx.call('MISC', 'SET_GAME_PAUSED', true)
				end
			end
		end
		ctx.call('MISC', 'SET_GAME_PAUSED', true)
		ctx.wait(2)
		return {
			string.format('advanced_s=%.9g', acc),
			'frames_run=' .. tostring(ctx.call('MISC', 'GET_FRAME_COUNT') - f0),
			'ticks=' .. ticks,
			'timer_ms=' .. tostring(ctx.call('MISC', 'GET_GAME_TIMER') - t0),
			'dts=' .. table.concat(dts, ' '),
		}
	end

	-- advance seconds [scale]: release the freeze at a reduced time scale until the summed frame
	-- time reaches `seconds`, then freeze again (real-time hitches make this inexact; the adapter
	-- steps with pause/frames instead). Reports what was advanced.
	function handlers.advance(args)
		local a = numbers(args)
		local target = a[1] or (1 / 30)
		local scale = a[2] or 0.1
		local t0 = ctx.call('MISC', 'GET_GAME_TIMER')
		local acc, ticks, steps = 0.0, 0, {}
		set_frozen(false)
		ctx.call('MISC', 'SET_TIME_SCALE', scale)
		local last = 0
		while true do
			ctx.wait(1)
			ticks = ticks + 1
			local dt = ctx.call('MISC', 'GET_FRAME_TIME')
			acc = acc + dt
			steps[#steps + 1] = string.format('%.5f', dt)
			last = dt
			if acc + last * 0.5 >= target or ticks > 2000 then
				break
			end
		end
		set_frozen(true)
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

	-- obstacles x y z radius: every ped (people, animals; not the player) and vehicle within
	-- radius, one answer line each, as an oriented box from its model's dimensions and its matrix:
	--   o<n>=<kind>|<mission 0/1>|<centre x y z>|<right x y z>|<forward x y z>|<up x y z>|<half a b c>
	-- The entities are kept for `remove` until the next obstacles call.
	local listed = {}
	local obs_pool = nil
	local mn, mx = native.new('Vector3', 1), native.new('Vector3', 1)
	local vf, vr, vu, vp = native.new('Vector3', 1), native.new('Vector3', 1), native.new('Vector3', 1), native.new('Vector3', 1)
	local function v3(v) return string.format('%.4f %.4f %.4f', v.x, v.y, v.z) end
	function handlers.obstacles(args)
		local a = numbers(args)
		local r2 = (a[4] or 30) ^ 2
		-- One pool per kind: a listed entity is a slot of its pool, and refilling one pool with the
		-- vehicles overwrote the people's slots before `remove` used them (2026-11-21: people in
		-- cameras survived every clearing).
		obs_pool = obs_pool or { peds = native.new('Entity', 2048), vehicles = native.new('Entity', 2048) }
		listed = {}
		local out = {}
		for _, kind in ipairs({ 'peds', 'vehicles' }) do
			local pool = obs_pool[kind]
			local n = kind == 'peds' and native.allpeds(pool) or native.allvehicles(pool)
			for i = 0, n - 1 do
				local e = pool[i]
				local skip = kind == 'peds' and select(2, ctx.try('PED', 'IS_PED_A_PLAYER', e))
				local okp, p = ctx.try('ENTITY', 'GET_ENTITY_COORDS', e, true)
				if not skip and okp and p and (p.x - a[1]) ^ 2 + (p.y - a[2]) ^ 2 + (p.z - a[3]) ^ 2 <= r2 then
					local okh, model = ctx.try('ENTITY', 'GET_ENTITY_MODEL', e)
					local okd = okh and ctx.try('MISC', 'GET_MODEL_DIMENSIONS', hash_arg(model), mn, mx)
					local okm = ctx.try('ENTITY', 'GET_ENTITY_MATRIX', e, vf, vr, vu, vp)
					if okd and okm then
						local lo, hi, R, F, U, P = mn[0], mx[0], vr[0], vf[0], vu[0], vp[0]
						local cx, cy, cz = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2
						local centre = { x = P.x + R.x * cx + F.x * cy + U.x * cz, y = P.y + R.y * cx + F.y * cy + U.y * cz,
							z = P.z + R.z * cx + F.z * cy + U.z * cz }
						local label = 'vehicle'
						if kind == 'peds' then
							label = select(2, ctx.try('PED', 'IS_PED_HUMAN', e)) and 'human' or 'animal'
						end
						local mission = select(2, ctx.try('ENTITY', 'IS_ENTITY_A_MISSION_ENTITY', e))
							and not spawned[handle_of(e, kind)]
						listed[#listed + 1] = { e = e, kind = label }
						out[#out + 1] = string.format('o%d=%s|%d|%s|%s|%s|%s|%.4f %.4f %.4f', #listed, label,
							mission and 1 or 0, v3(centre), v3(R), v3(F), v3(U),
							(hi.x - lo.x) / 2, (hi.y - lo.y) / 2, (hi.z - lo.z) / 2)
					end
				end
			end
		end
		out[#out + 1] = 'obstacle_count=' .. #listed
		return out
	end

	-- remove n n ...: delete listed obstacles with their vehicle occupants (or the vehicle a ped
	-- sits in). Entities a game script owns (mission entities) are never deleted; answer lines
	-- removed=<count>, skipped=<n,n,...> (the listed numbers kept).
	local function linked(e, kind, acc, seen)
		if not e or e == 0 or seen[tostring(e)] then
			return
		end
		local ok_exists, exists = ctx.try('ENTITY', 'DOES_ENTITY_EXIST', e)
		if not ok_exists or not exists then
			return
		end
		seen[tostring(e)] = true
		acc[#acc + 1] = { e = e, kind = kind }
		if kind == 'vehicle' then
			for seat = -1, 6 do
				local ok, occ = ctx.try('VEHICLE', 'GET_PED_IN_VEHICLE_SEAT', e, seat, false)
				if ok and occ then linked(occ, 'ped', acc, seen) end
			end
		elseif select(2, ctx.try('PED', 'IS_PED_IN_ANY_VEHICLE', e, false)) then
			linked(select(2, ctx.try('PED', 'GET_VEHICLE_PED_IS_IN', e, false)), 'vehicle', acc, seen)
		end
	end
	function handlers.remove(args)
		local removed, skipped, moved_away = 0, {}, 0
		for _, n in ipairs(numbers(args)) do
			local item = listed[n]
			if item then
				local group, seen = {}, {}
				linked(item.e, item.kind == 'vehicle' and 'vehicle' or 'ped', group, seen)
				local owned = false
				for _, g in ipairs(group) do
					local e = g.e
					if e == ped or select(2, ctx.try('PED', 'IS_PED_A_PLAYER', e))
						or (select(2, ctx.try('ENTITY', 'IS_ENTITY_A_MISSION_ENTITY', e)) and not spawned[handle_of(e, g.kind)]) then
						owned = true
					end
				end
				if owned then
					skipped[#skipped + 1] = tostring(n)
				else
					for _, g in ipairs(group) do
						-- the value-typed handle, not a pool slot (see handle_of)
						local v = value_of(g.e, g.kind)
						ctx.try('ENTITY', 'SET_ENTITY_AS_MISSION_ENTITY', v, true, true)
						local ref = native.new('Entity', 1)
						ref[0] = v
						ctx.try('ENTITY', 'DELETE_ENTITY', ref)
						-- People this script did not create in this job (ambient, or an earlier session's
						-- crowd) survived DELETE_ENTITY (2026-11-21). In a frozen world, moving one far
						-- below the street takes it out of every camera just the same.
						if select(2, ctx.try('ENTITY', 'DOES_ENTITY_EXIST', v)) then
							local okc, c = ctx.try('ENTITY', 'GET_ENTITY_COORDS', v, true)
							if okc then
								ctx.try('ENTITY', 'FREEZE_ENTITY_POSITION', v, true)
								ctx.try('ENTITY', 'SET_ENTITY_COORDS_NO_OFFSET', v, c.x, c.y, c.z - 300.0, false, false, false)
							end
							moved_away = moved_away + 1
						end
						spawned[tostring(v)] = nil
						removed = removed + 1
					end
				end
			end
		end
		return { 'removed=' .. removed, 'moved_away=' .. moved_away, 'skipped=' .. table.concat(skipped, ',') }
	end

	-- raycast [flags] [per_tick]: line probes for the scene around a location. Reads rays_in.txt in
	-- the exchange folder, one ray per line "x1 y1 z1 x2 y2 z2"; writes rays_out.txt, one line per
	-- ray, "1 x y z nx ny nz" (hit point, surface normal) or "0". flags: what the rays stop at
	-- (default 1|16|256: map collision, objects, foliage; not people or vehicles, which the obstacle
	-- check handles).
	function handlers.raycast(args)
		local a0 = numbers(args)
		local flags = math.floor(a0[1] or 273)
		local per_tick = math.floor(a0[2] or 400)
		local inp, outp = ctx.out_dir .. '\\rays_in.txt', ctx.out_dir .. '\\rays_out.txt'
		local fin = assert(io.open(inp, 'r'))
		local fout = assert(io.open(outp .. '.tmp', 'w'))
		local hit, endc, norm, ent = native.new('BOOL', 1), native.new('Vector3', 1), native.new('Vector3', 1), native.new('Entity', 1)
		local n, nhit, t0 = 0, 0, os.clock()
		for line in fin:lines() do
			local a = numbers(line)
			if #a >= 6 then
				-- RedLua keeps one Lua object per handle number, whatever the handle is of: a shape test
				-- whose number is that of the session's camera comes back as that Cam object, and asking
				-- for its result fails ("ScrHandle expected, got Cam": every take after the first failed
				-- so, 2026-11-23). The next test gets another number, so the ray is tried again.
				local status, asked
				for _ = 1, 8 do
					local h = native.call('SHAPETEST', 'START_EXPENSIVE_SYNCHRONOUS_SHAPE_TEST_LOS_PROBE',
						a[1], a[2], a[3], a[4], a[5], a[6], flags, ped, 7)
					asked, status = pcall(native.call, 'SHAPETEST', 'GET_SHAPE_TEST_RESULT', h, hit, endc, norm, ent)
					if asked then break end
				end
				if not asked then error(status, 0) end
				-- A hit is an end point on this ray (the BOOL* hit read back 0 through RedLua in RDR2).
				local dx, dy, dz = a[4] - a[1], a[5] - a[2], a[6] - a[3]
				local ex, ey, ez = endc[0].x - a[1], endc[0].y - a[2], endc[0].z - a[3]
				local len2 = dx * dx + dy * dy + dz * dz
				local t = len2 > 0 and (ex * dx + ey * dy + ez * dz) / len2 or -1
				local px, py, pz = ex - t * dx, ey - t * dy, ez - t * dz
				local on_ray = t >= 0 and t <= 1.0001 and (px * px + py * py + pz * pz) < 0.0025
				if status == 2 and on_ray and (endc[0].x ~= 0 or endc[0].y ~= 0 or endc[0].z ~= 0) then
					fout:write(string.format('1 %.4f %.4f %.4f %.4f %.4f %.4f\n', endc[0].x, endc[0].y, endc[0].z,
						norm[0].x, norm[0].y, norm[0].z))
					nhit = nhit + 1
				else
					fout:write('0\n')
				end
				n = n + 1
				if n % per_tick == 0 then
					ctx.wait(1)
				end
			end
		end
		fin:close()
		fout:close()
		os.remove(outp)
		os.rename(outp .. '.tmp', outp)
		return { 'rays=' .. n, 'hits=' .. nhit, string.format('cpu_s=%.2f', os.clock() - t0) }
	end

	-- density people traffic: population multipliers applied every frame (1 = the game's maximum
	-- setting); density off: back to the game's own.
	function handlers.density(args)
		if (args or ''):match('off') then
			density = nil
			return { 'density=off' }
		end
		local a = numbers(args)
		density = { a[1] or 1.0, a[2] or a[1] or 1.0 }
		ctx.try('STREAMING', 'SET_PED_POPULATION_BUDGET', 3)
		ctx.try('STREAMING', 'SET_VEHICLE_POPULATION_BUDGET', 3)
		return { string.format('density=%g %g', density[1], density[2]) }
	end

	-- populate: fill the ambient population around the player now, instead of over a minute.
	function handlers.populate()
		ctx.try('PED', 'INSTANTLY_FILL_PED_POPULATION')
		ctx.try('VEHICLE', 'INSTANTLY_FILL_VEHICLE_POPULATION')
		ctx.try('MISC', 'POPULATE_NOW')
	end

	-- crowd n x y z radius: n random pedestrians placed 2.5 m to radius from (x, y), walking about
	-- inside the radius. They stay this session's own (the game culls released extra people, also
	-- while the world is frozen: 16 vanished over 2,000 frozen frames, 2026-11-21), so obstacles
	-- reports them as not owned and remove may delete them; they are released when the session ends.
	function handlers.crowd(args)
		local a = numbers(args)
		local n, x, y, z, r = math.floor(a[1] or 8), a[2], a[3], a[4], a[5] or 12
		local gz = native.new('float', 1)
		local made = 0
		for i = 1, n do
			local ang = 2 * math.pi * (i + math.random()) / n
			local d = 2.5 + (r - 2.5) * math.random()
			local px, py = x + d * math.cos(ang), y + d * math.sin(ang)
			local pz = z
			if ctx.call('MISC', 'GET_GROUND_Z_FOR_3D_COORD', px, py, z + 3.0, gz, false, false) then
				pz = gz[0]
			end
			local ok, p = ctx.try('PED', 'CREATE_RANDOM_PED', px, py, pz + 1.0)
			if ok and p and p ~= 0 then
				ctx.try('TASK', 'TASK_WANDER_IN_AREA', p, x, y, z, r, 2.0, 2.0)
				ctx.try('PED', 'SET_PED_KEEP_TASK', p, true)
				spawned[handle_of(p, 'ped')] = p
				made = made + 1
			end
			ctx.wait(1)
		end
		return { 'crowd=' .. made }
	end

	-- entities x y z radius: every ped (not the player) and vehicle within radius, one answer line
	-- each, e<n>=<handle>|<ped|vehicle>|<x y z>, to check that a frozen world stays as it is.
	local ent_pool = nil
	function handlers.entities(args)
		local a = numbers(args)
		local r2 = (a[4] or 60) ^ 2
		ent_pool = ent_pool or native.new('Entity', 2048)
		local out, n = {}, 0
		for _, kind in ipairs({ 'peds', 'vehicles' }) do
			local count = kind == 'peds' and native.allpeds(ent_pool) or native.allvehicles(ent_pool)
			for i = 0, count - 1 do
				local e = ent_pool[i]
				if e ~= ped then
					local okp, q = ctx.try('ENTITY', 'GET_ENTITY_COORDS', e, true)
					if okp and q and (q.x - a[1]) ^ 2 + (q.y - a[2]) ^ 2 + (q.z - a[3]) ^ 2 <= r2 then
						n = n + 1
						out[#out + 1] = string.format('e%d=%s|%s|%.4f %.4f %.4f', n, handle_of(e, kind), kind, q.x, q.y, q.z)
					end
				end
			end
		end
		out[#out + 1] = 'entity_count=' .. n
		return out
	end

	-- keep x y z radius: every ambient person and vehicle within radius becomes the session's own
	-- (a mission entity), so the game's population system cannot take it away while the world steps:
	-- with the multipliers at 0 it removed 5 people and 2 cars within 150 m over 6 steps of 1/30 s
	-- (Vinewood, 2026-11-23, tools/hold_step_check.py), which showed as people vanishing in the
	-- background of 30-clip-frame takes. They are given back to the game when the session ends, like
	-- the crowd; obstacles and remove treat them as the session's own (they may be deleted).
	function handlers.keep(args)
		local a = numbers(args)
		local r2 = (a[4] or 150) ^ 2
		ent_pool = ent_pool or native.new('Entity', 2048)
		local n, peds_n, vehicles_n = 0, 0, 0
		for _, kind in ipairs({ 'peds', 'vehicles' }) do
			local count = kind == 'peds' and native.allpeds(ent_pool) or native.allvehicles(ent_pool)
			for i = 0, count - 1 do
				local e = ent_pool[i]
				local player = kind == 'peds' and select(2, ctx.try('PED', 'IS_PED_A_PLAYER', e))
				if e ~= ped and not player then
					local okp, q = ctx.try('ENTITY', 'GET_ENTITY_COORDS', e, true)
					if okp and q and (q.x - a[1]) ^ 2 + (q.y - a[2]) ^ 2 + (q.z - a[3]) ^ 2 <= r2 then
						local h = handle_of(e, kind)
						if not spawned[h] and not select(2, ctx.try('ENTITY', 'IS_ENTITY_A_MISSION_ENTITY', e)) then
							local v = value_of(e, kind)
							if ctx.try('ENTITY', 'SET_ENTITY_AS_MISSION_ENTITY', v, true, true) then
								spawned[h] = v
								kept[h] = true
								n = n + 1
								if kind == 'peds' then peds_n = peds_n + 1 else vehicles_n = vehicles_n + 1 end
							end
						end
					end
				end
			end
		end
		return { 'kept=' .. n, 'kept_people=' .. peds_n, 'kept_vehicles=' .. vehicles_n }
	end

	-- wind [speed]: the wind speed now (m/s); with a speed, set it first (the game's own weather
	-- sets it again when the weather changes)
	function handlers.wind(args)
		local v = numbers(args)[1]
		if v then
			ctx.call('MISC', 'SET_WIND_SPEED', v)
		end
		return { string.format('wind_speed=%.3f', ctx.call('MISC', 'GET_WIND_SPEED')) }
	end

	-- population x y z: people and vehicles near a point, within 15, 30 and 60 m
	local pool = nil
	function handlers.population(args)
		local a = numbers(args)
		pool = pool or native.new('Entity', 2048)
		local out = {}
		for _, kind in ipairs({ 'peds', 'vehicles' }) do
			local n = kind == 'peds' and native.allpeds(pool) or native.allvehicles(pool)
			local c = { 0, 0, 0 }
			for i = 0, n - 1 do
				local e = pool[i]
				if not (kind == 'peds' and select(2, ctx.try('PED', 'IS_PED_A_PLAYER', e))) then
					local okp, p = ctx.try('ENTITY', 'GET_ENTITY_COORDS', e, true)
					if okp and p then
						local d = math.sqrt((p.x - a[1]) ^ 2 + (p.y - a[2]) ^ 2 + (p.z - a[3]) ^ 2)
						for k, r in ipairs({ 15, 30, 60 }) do
							if d <= r then c[k] = c[k] + 1 end
						end
					end
				end
			end
			out[#out + 1] = string.format('%s=%d %d %d %d', kind, n, c[1], c[2], c[3])
		end
		return out
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

	-- eval: runs eval_in.lua from the exchange folder in this session: a chunk that returns
	-- function(ctx, native); what that returns (a value, or a list of values) comes back as lines
	-- r1=, r2=, ... The agent's way to try natives in a running session
	-- (python -m adapters.common.redlua_eval --game <game> "<lua>").
	function handlers.eval()
		local chunk, err = loadfile(ctx.out_dir .. '\\eval_in.lua')
		if not chunk then
			error('eval: ' .. tostring(err))
		end
		local out = chunk()(ctx, native)
		if type(out) ~= 'table' then
			out = { out }
		end
		local lines = {}
		for i, v in ipairs(out) do
			lines[#lines + 1] = 'r' .. i .. '=' .. tostring(v)
		end
		return lines
	end

	-- shoot n stem: let n ticks pass, then capture (one round trip per shot).
	function handlers.shoot(args)
		local n, stem = (args or ''):match('^(%d+)%s+(%S+)$')
		ctx.wait(math.max(1, tonumber(n) or 1))
		return handlers.capture(stem)
	end

	-- clock h m: set the time of day.
	function handlers.clock(args)
		local a = numbers(args)
		ctx.call('CLOCK', 'SET_CLOCK_TIME', math.floor(a[1] or 12), math.floor(a[2] or 0), 0)
		return { string.format('clock=%02d:%02d', ctx.call('CLOCK', 'GET_CLOCK_HOURS'), ctx.call('CLOCK', 'GET_CLOCK_MINUTES')) }
	end

	-- weather NAME (EXTRASUNNY, CLEAR, CLOUDS, SMOG, FOGGY, OVERCAST, RAIN, THUNDER, CLEARING, ...):
	-- change at once and keep it; weather free: let it change again; weather state / hold: the
	-- previous and next weather type hashes (a persisted weather is already held).
	local function weather_state()
		return { 'weather_prev=' .. tostring(ctx.call('MISC', 'GET_PREV_WEATHER_TYPE_HASH_NAME')),
			'weather_next=' .. tostring(ctx.call('MISC', 'GET_NEXT_WEATHER_TYPE_HASH_NAME')) }
	end
	function handlers.weather(args)
		local name = (args or ''):match('^(%S+)')
		if name == 'state' or name == 'hold' then
			return weather_state()
		end
		if not name or name == 'free' then
			ctx.call('MISC', 'CLEAR_WEATHER_TYPE_PERSIST')
			return { 'weather=free' }
		end
		ctx.call('MISC', 'SET_WEATHER_TYPE_NOW_PERSIST', name:upper())
		local out = weather_state()
		out[#out + 1] = 'weather=' .. name:upper()
		out[#out + 1] = 'weather_hash=' .. tostring(ctx.call('MISC', 'GET_HASH_KEY', name:upper()))
		return out
	end

	-- ground x y z: height of the ground below a point.
	function handlers.ground(args)
		local a = numbers(args)
		local gz = native.new('float', 1)
		local ok = ctx.call('MISC', 'GET_GROUND_Z_FOR_3D_COORD', a[1], a[2], a[3], gz, false, false)
		return { 'ground_found=' .. tostring(ok), string.format('ground_z=%.9g', gz[0]) }
	end

	-- focus x y z | focus clear: stream the world around a point instead of around the player.
	local focused = false
	ctx.defer(function()
		if focused then pcall(native.call, 'STREAMING', 'CLEAR_FOCUS') end
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

	-- park x y z: the player at an exact point, position frozen, no collision (e.g. high above the
	-- capture location). Undone when the session ends.
	local parked, park_return = false, nil
	ctx.defer(function()
		if parked then
			pcall(native.call, 'ENTITY', 'FREEZE_ENTITY_POSITION', ped, true)
			if park_return then
				pcall(native.call, 'ENTITY', 'SET_ENTITY_COORDS_NO_OFFSET', ped, park_return.x, park_return.y, park_return.z,
					false, false, false)
			end
			pcall(native.call, 'ENTITY', 'SET_ENTITY_COLLISION', ped, true, true)
			pcall(native.call, 'ENTITY', 'FREEZE_ENTITY_POSITION', ped, false)
		end
	end)
	function handlers.park(args)
		local a = numbers(args)
		if not parked then
			park_return = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true)
		end
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, true)
		ctx.call('ENTITY', 'SET_ENTITY_COLLISION', ped, false, false)
		ctx.call('ENTITY', 'SET_ENTITY_COORDS_NO_OFFSET', ped, a[1], a[2], a[3], false, false, false)
		held, parked = true, true
	end

	-- ghost 0|1: the player as absent as the game allows: ignored by everyone and the police, no
	-- wanted level, silent, invincible, no collision. Undone when the session ends.
	local ghost = false
	local function set_ghost(on)
		ctx.try('PLAYER', 'SET_EVERYONE_IGNORE_PLAYER', pid, on)
		ctx.try('PLAYER', 'SET_POLICE_IGNORE_PLAYER', pid, on)
		ctx.try('PLAYER', 'SET_DISPATCH_COPS_FOR_PLAYER', pid, not on)
		ctx.try('PLAYER', 'SET_PLAYER_INVINCIBLE', pid, on)
		ctx.try('PLAYER', 'SET_PLAYER_NOISE_MULTIPLIER', pid, on and 0.0 or 1.0)
		ctx.try('PLAYER', 'SET_WANTED_LEVEL_MULTIPLIER', on and 0.0 or 1.0)
		ctx.try('PLAYER', 'SET_MAX_WANTED_LEVEL', on and 0 or 5)
		if on then
			ctx.try('PLAYER', 'CLEAR_PLAYER_WANTED_LEVEL', pid)
			ctx.try('EVENT', 'REMOVE_ALL_SHOCKING_EVENTS', false)
		end
		ctx.try('ENTITY', 'SET_ENTITY_COLLISION', ped, not on, not on)
		ghost = on
	end
	ctx.defer(function()
		if ghost then pcall(set_ghost, false) end
	end)
	function handlers.ghost(args)
		set_ghost((numbers(args)[1] or 1) ~= 0)
		return { 'ghost=' .. (ghost and '1' or '0') }
	end

	-- place x y z: the zone index and street hash at a point (answer lines place_zone, place_street)
	function handlers.place(args)
		local a = numbers(args)
		return place_ids(a[1], a[2], a[3])
	end

	-- hold 0|1: keep the player's position frozen. Released when the session ends.
	ctx.defer(function()
		if held then pcall(native.call, 'ENTITY', 'FREEZE_ENTITY_POSITION', ped, false) end
	end)
	function handlers.hold(args)
		held = (numbers(args)[1] or 1) ~= 0
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, held)
		return { 'held=' .. (held and '1' or '0') }
	end

	-- teleport x y z heading [max_ticks] [hold]: move the player to (x, y), standing on the ground
	-- near z, and wait until collision and the scene around it have loaded.
	function handlers.teleport(args)
		local a = numbers(args)
		if #a < 3 then
			error('teleport needs x y z [heading] [max_ticks] [hold]')
		end
		local x, y, z, h = a[1], a[2], a[3], a[4] or 0.0
		local max_ticks = math.floor(a[5] or 900)
		local keep = (a[6] or 1) ~= 0
		parked = false
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, true)
		ctx.call('ENTITY', 'SET_ENTITY_COORDS_NO_OFFSET', ped, x, y, z + 1.0, false, false, false)
		ctx.call('ENTITY', 'SET_ENTITY_HEADING', ped, h)
		local scene_ok = ctx.try('STREAMING', 'NEW_LOAD_SCENE_START_SPHERE', x, y, z, 200.0, 0)
		local ticks, loaded = 0, false
		while ticks < max_ticks do
			ctx.try('STREAMING', 'REQUEST_COLLISION_AT_COORD', x, y, z)
			ctx.wait(1)
			ticks = ticks + 1
			local _, coll = ctx.try('ENTITY', 'HAS_COLLISION_LOADED_AROUND_ENTITY', ped)
			local oks, scene = ctx.try('STREAMING', 'IS_NEW_LOAD_SCENE_LOADED')
			if ticks >= 30 and coll and (scene or not oks or not scene_ok) then
				loaded = true
				break
			end
		end
		ctx.try('STREAMING', 'NEW_LOAD_SCENE_STOP')
		ctx.call('ENTITY', 'SET_ENTITY_COLLISION', ped, false, false)
		local gz = native.new('float', 1)
		local found = ctx.call('MISC', 'GET_GROUND_Z_FOR_3D_COORD', x, y, z + 2.0, gz, false, false)
		if found then
			-- a ped's origin is about 1 m above its feet
			ctx.call('ENTITY', 'SET_ENTITY_COORDS_NO_OFFSET', ped, x, y, gz[0] + 1.0, false, false, false)
		end
		if not ghost then
			ctx.call('ENTITY', 'SET_ENTITY_COLLISION', ped, true, true)
		end
		ctx.call('ENTITY', 'SET_ENTITY_HEADING', ped, h)
		ctx.try('TASK', 'CLEAR_PED_TASKS_IMMEDIATELY', ped)
		held = keep
		ctx.call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, keep)
		return { 'loaded=' .. tostring(loaded), 'ticks=' .. ticks, 'ground_found=' .. tostring(found),
			string.format('ground_z=%.9g', gz[0]), 'held=' .. (keep and '1' or '0') }
	end

	-- player_visible 0|1
	local player_hidden = false
	ctx.defer(function()
		if player_hidden then pcall(native.call, 'ENTITY', 'SET_ENTITY_VISIBLE', ped, true, false) end
	end)
	function handlers.player_visible(args)
		local on = (numbers(args)[1] or 1) ~= 0
		ctx.call('ENTITY', 'SET_ENTITY_VISIBLE', ped, on, false)
		player_hidden = not on
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

	-- While this file is fresh, other scripts stay off the screen.
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
	local tick = 0
	while true do
		ctx.wait(1)   -- each_tick hides the HUD
		tick = tick + 1
		if tick % 60 == 0 then
			mark_active()
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
