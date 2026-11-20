-- Tests one way of freezing the world. Holds a script camera on the player,
-- measures how far the player's hand and head travel per tick while live and
-- while frozen, and captures frames from the same pose at different moments.
--
-- Extra command arguments:
--   method = timescale | photo | photo_timescale | paused     (default timescale)
--   gap    = ticks between frozen captures                    (default 120)
--   radius, height, angle_deg, fov                            camera placement
return function(ctx)
	local method = ctx.args.method or 'timescale'
	local gap = tonumber(ctx.args.gap) or 120
	local radius = tonumber(ctx.args.radius) or 6.0
	local height = tonumber(ctx.args.height) or 1.5
	local angle = math.rad(tonumber(ctx.args.angle_deg) or 0)
	local fov = tonumber(ctx.args.fov) or 50.0

	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local p = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
	local center = { x = p.x, y = p.y, z = p.z }

	local bones = {}
	for _, name in ipairs({ 'SKEL_R_Hand', 'SKEL_L_Hand', 'SKEL_Head' }) do
		local ok, index = ctx.try('ENTITY', 'GET_ENTITY_BONE_INDEX_BY_NAME', ped, name)
		ctx.log('bone %s -> %s', name, tostring(index))
		if ok and type(index) == 'number' and index >= 0 then
			bones[#bones + 1] = index
		end
	end

	local function bone_positions()
		local out = {}
		for i, index in ipairs(bones) do
			local v = ctx.call('ENTITY', 'GET_WORLD_POSITION_OF_ENTITY_BONE', ped, index)
			out[i] = { v.x, v.y, v.z }
		end
		return out
	end

	-- Lets the game run for `frames` ticks and returns the summed bone travel in
	-- metres, the largest single-tick travel, and the game-timer change in ms.
	local function travel(label, frames)
		local t0 = ctx.call('MISC', 'GET_GAME_TIMER')
		local prev = bone_positions()
		local total, biggest = 0, 0
		for _ = 1, frames do
			ctx.wait(1)
			local now = bone_positions()
			local step = 0
			for i = 1, #now do
				local dx, dy, dz = now[i][1] - prev[i][1], now[i][2] - prev[i][2], now[i][3] - prev[i][3]
				step = step + math.sqrt(dx * dx + dy * dy + dz * dz)
			end
			total = total + step
			if step > biggest then
				biggest = step
			end
			prev = now
		end
		local dt = ctx.call('MISC', 'GET_GAME_TIMER') - t0
		ctx.log('%s: %d ticks, bone travel %.6f m total, %.6f m largest tick, game timer +%d ms, frame time now %.5f s',
			label, frames, total, biggest, dt, ctx.call('MISC', 'GET_FRAME_TIME'))
		ctx.result[label .. '_travel_m'] = string.format('%.6f', total)
		ctx.result[label .. '_timer_ms'] = dt
		return total
	end

	local function set_frozen(on)
		if method == 'timescale' or method == 'photo_timescale' then
			ctx.call('MISC', 'SET_TIME_SCALE', on and 0.0 or 1.0)
		end
		if method == 'photo' or method == 'photo_timescale' then
			ctx.call('ANIMSCENE', on and '_REQUEST_PHOTO_MODE_FREEZE' or '_REQUEST_PHOTO_MODE_DEFREEZE')
		end
		if method == 'paused' then
			ctx.call('MISC', 'SET_GAME_PAUSED', on)
		end
	end

	local cam = ctx.call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
	ctx.defer(function()
		pcall(native.call, 'MISC', 'SET_GAME_PAUSED', false)
		pcall(native.call, 'ANIMSCENE', '_REQUEST_PHOTO_MODE_DEFREEZE')
		native.call('MISC', 'SET_TIME_SCALE', 1.0)
		native.call('CAM', 'RENDER_SCRIPT_CAMS', false, false, 0, true, false, 0)
		native.call('CAM', 'SET_CAM_ACTIVE', cam, false)
		native.call('CAM', 'DESTROY_CAM', cam, false)
	end)

	local function place(a)
		ctx.call('CAM', 'SET_CAM_COORD', cam,
			center.x + radius * math.cos(a), center.y + radius * math.sin(a), center.z + height)
		ctx.call('CAM', 'POINT_CAM_AT_COORD', cam, center.x, center.y, center.z)
	end

	local function letterbox(label)
		local _, has = ctx.try('CAM', 'HAS_LETTER_BOX')
		local _, ratio = ctx.try('CAM', 'GET_LETTER_BOX_RATIO')
		ctx.log('%s: letter box %s, ratio %s', label, tostring(has), tostring(ratio))
	end

	place(angle)
	ctx.call('CAM', 'SET_CAM_FOV', cam, fov)
	ctx.call('CAM', 'SET_CAM_ACTIVE', cam, true)
	ctx.call('CAM', 'RENDER_SCRIPT_CAMS', true, false, 0, true, false, 0)
	ctx.wait(60)

	ctx.log('method: %s', method)
	letterbox('live')
	travel('live_before', 60)

	set_frozen(true)
	ctx.wait(30)
	letterbox('frozen')
	ctx.capture('frozen_a')
	travel('frozen_1', gap)
	ctx.capture('frozen_b')
	travel('frozen_2', gap)
	ctx.capture('frozen_c')

	-- Move the camera a quarter turn while frozen, then come back. frozen_back
	-- should match frozen_a if the freeze holds and the camera still obeys.
	place(angle + math.pi / 2)
	ctx.wait(30)
	ctx.capture('frozen_moved')
	place(angle)
	ctx.wait(30)
	ctx.capture('frozen_back')

	set_frozen(false)
	ctx.wait(30)
	travel('live_after', 60)
	ctx.capture('live_after')
end
