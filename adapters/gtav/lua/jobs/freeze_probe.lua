-- Tests one way of freezing GTA V's world (it has no photo-mode freeze like RDR2's). Holds a
-- script camera on the player, measures how far the player's hands and head and the nearest
-- people and vehicles move per tick while live and while frozen, and captures frames from the
-- same pose at different moments, plus one after moving the camera away and back.
--
-- Extra command arguments:
--   method = timescale | paused | both        (default timescale)
--   gap    = ticks between frozen captures    (default 120)
--   radius, height, angle_deg, fov            camera placement
return function(ctx)
	local method = ctx.args.method or 'timescale'
	local gap = tonumber(ctx.args.gap) or 120
	local radius = tonumber(ctx.args.radius) or 6.0
	local height = tonumber(ctx.args.height) or 1.5
	local angle = math.rad(tonumber(ctx.args.angle_deg) or 0)
	local fov = tonumber(ctx.args.fov) or 50.0

	-- keep this script (RedLua, inside Script Hook V) running if the game is paused
	ctx.try('MISC', 'SET_THIS_SCRIPT_CAN_BE_PAUSED', false)

	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local p = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true)
	local center = { x = p.x, y = p.y, z = p.z }
	local BONES = { 57005, 18905, 31086 }    -- SKEL_R_Hand, SKEL_L_Hand, SKEL_Head

	-- the nearest few other people and vehicles, to see whether the world holds, not just the player
	local others = {}
	local pool = native.new('Entity', 1024)
	for _, kind in ipairs({ 'peds', 'vehicles' }) do
		local n = kind == 'peds' and native.allpeds(pool) or native.allvehicles(pool)
		local near = {}
		for i = 0, n - 1 do
			local e = pool[i]
			if e ~= ped then
				local q = ctx.call('ENTITY', 'GET_ENTITY_COORDS', e, true)
				local d = math.sqrt((q.x - p.x) ^ 2 + (q.y - p.y) ^ 2 + (q.z - p.z) ^ 2)
				if d < 60 then near[#near + 1] = { e = e, d = d } end
			end
		end
		table.sort(near, function(a, b) return a.d < b.d end)
		for i = 1, math.min(4, #near) do others[#others + 1] = near[i].e end
		ctx.log('%s within 60 m: %d (tracking %d)', kind, #near, math.min(4, #near))
	end

	local function positions()
		local out = {}
		for _, b in ipairs(BONES) do
			local v = ctx.call('PED', 'GET_PED_BONE_COORDS', ped, b, 0.0, 0.0, 0.0)
			out[#out + 1] = { v.x, v.y, v.z }
		end
		for _, e in ipairs(others) do
			local ok, v = ctx.try('ENTITY', 'GET_ENTITY_COORDS', e, true)
			out[#out + 1] = ok and { v.x, v.y, v.z } or { 0, 0, 0 }
		end
		return out
	end

	-- Lets the game run for `frames` ticks; logs the summed travel (player bones, others) in metres,
	-- the game timer change and the frame count change.
	local function travel(label, frames)
		local t0, f0 = ctx.call('MISC', 'GET_GAME_TIMER'), ctx.call('MISC', 'GET_FRAME_COUNT')
		local prev = positions()
		local mine, theirs = 0, 0
		for _ = 1, frames do
			ctx.wait(1)
			local now = positions()
			for i = 1, #now do
				local dx, dy, dz = now[i][1] - prev[i][1], now[i][2] - prev[i][2], now[i][3] - prev[i][3]
				local s = math.sqrt(dx * dx + dy * dy + dz * dz)
				if i <= #BONES then mine = mine + s else theirs = theirs + s end
			end
			prev = now
		end
		local dt = ctx.call('MISC', 'GET_GAME_TIMER') - t0
		local df = ctx.call('MISC', 'GET_FRAME_COUNT') - f0
		ctx.log('%s: %d ticks, player bones %.6f m, %d others %.6f m, game timer +%d ms, frame count +%d, frame time %.5f',
			label, frames, mine, #others, theirs, dt, df, ctx.call('MISC', 'GET_FRAME_TIME'))
		ctx.result[label .. '_player_m'] = string.format('%.6f', mine)
		ctx.result[label .. '_others_m'] = string.format('%.6f', theirs)
		ctx.result[label .. '_timer_ms'] = dt
		ctx.result[label .. '_frames'] = df
	end

	local function set_frozen(on)
		if method == 'timescale' or method == 'both' then
			ctx.call('MISC', 'SET_TIME_SCALE', on and 0.0 or 1.0)
		end
		if method == 'paused' or method == 'both' then
			ctx.call('MISC', 'SET_GAME_PAUSED', on)
		end
	end

	local function render(on)
		-- p5 is typed Any; RedLua may only take a typed pointer there
		local ok = pcall(native.call, 'CAM', 'RENDER_SCRIPT_CAMS', on, false, 0, true, false, 0)
		if not ok then
			native.call('CAM', 'RENDER_SCRIPT_CAMS', on, false, 0, true, false, native.new('Any', 1))
		end
	end

	local cam = ctx.call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
	ctx.defer(function()
		pcall(native.call, 'MISC', 'SET_GAME_PAUSED', false)
		native.call('MISC', 'SET_TIME_SCALE', 1.0)
		pcall(render, false)
		native.call('CAM', 'SET_CAM_ACTIVE', cam, false)
		native.call('CAM', 'DESTROY_CAM', cam, false)
	end)

	local function place(a)
		ctx.call('CAM', 'SET_CAM_COORD', cam,
			center.x + radius * math.cos(a), center.y + radius * math.sin(a), center.z + height)
		ctx.call('CAM', 'POINT_CAM_AT_COORD', cam, center.x, center.y, center.z)
	end

	place(angle)
	ctx.call('CAM', 'SET_CAM_FOV', cam, fov)
	ctx.call('CAM', 'SET_CAM_ACTIVE', cam, true)
	render(true)
	ctx.wait(60)

	ctx.log('method: %s', method)
	travel('live_before', 60)
	ctx.capture('live_before')

	set_frozen(true)
	ctx.wait(30)
	ctx.capture('frozen_a')
	travel('frozen_1', gap)
	ctx.capture('frozen_b')
	travel('frozen_2', gap)
	ctx.capture('frozen_c')

	-- a quarter turn while frozen, then back: frozen_back should match frozen_a if the freeze
	-- holds and the camera still obeys
	place(angle + math.pi / 2)
	ctx.wait(30)
	ctx.capture('frozen_moved')
	place(angle)
	ctx.wait(30)
	ctx.capture('frozen_back')
	local c = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD')
	ctx.result.rendered_cam = string.format('%.3f %.3f %.3f', c.x, c.y, c.z)

	set_frozen(false)
	ctx.wait(30)
	travel('live_after', 60)
	ctx.capture('live_after')
end
