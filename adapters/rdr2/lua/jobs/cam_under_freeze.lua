-- Finds a way to move the camera while the world is held by the photo-mode
-- freeze. Tries several strategies; for each one it logs whether the rendered
-- camera reached the requested position and how far the player's bones moved.
--
-- Extra command arguments:
--   tests  = comma list of: plain, params, newcam, thaw1, thaw2, thaw3   (default: all)
--   shots  = 1 to capture a frame after each strategy                      (default 0)
return function(ctx)
	local wanted = {}
	for name in (ctx.args.tests or 'plain,params,newcam,thaw1,thaw2,thaw3'):gmatch('[%w_]+') do
		wanted[#wanted + 1] = name
	end
	local shots = ctx.args.shots == '1'
	local radius, height, fov = 6.0, 1.5, 50.0

	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local p = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
	local center = { x = p.x, y = p.y, z = p.z }

	local bones = {}
	for _, name in ipairs({ 'SKEL_R_Hand', 'SKEL_L_Hand', 'SKEL_Head' }) do
		bones[#bones + 1] = ctx.call('ENTITY', 'GET_ENTITY_BONE_INDEX_BY_NAME', ped, name)
	end
	local function bone_positions()
		local out = {}
		for i, index in ipairs(bones) do
			local v = ctx.call('ENTITY', 'GET_WORLD_POSITION_OF_ENTITY_BONE', ped, index)
			out[i] = { v.x, v.y, v.z }
		end
		return out
	end
	local function bone_shift(a, b)
		local total = 0
		for i = 1, #a do
			local dx, dy, dz = a[i][1] - b[i][1], a[i][2] - b[i][2], a[i][3] - b[i][3]
			total = total + math.sqrt(dx * dx + dy * dy + dz * dz)
		end
		return total
	end

	local function pose(angle_deg)
		local a = math.rad(angle_deg)
		return { x = center.x + radius * math.cos(a), y = center.y + radius * math.sin(a), z = center.z + height }
	end
	local function miss(target)
		local c = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD')
		local dx, dy, dz = c.x - target.x, c.y - target.y, c.z - target.z
		return math.sqrt(dx * dx + dy * dy + dz * dz)
	end

	-- Pitch and yaw (degrees, rotation order 2) that aim a camera at `from` towards the centre.
	local function look_rot(from)
		local dx, dy, dz = center.x - from.x, center.y - from.y, center.z - from.z
		return math.deg(math.atan2(dz, math.sqrt(dx * dx + dy * dy))), math.deg(math.atan2(-dx, dy))
	end

	-- cam_type=KIT_CAMERA is the type the game's handheld-camera script creates.
	-- WARNING: activating and rendering a KIT_CAMERA this way raised an exception
	-- in RedLua.asi (2026-11-19) and killed all RedLua scripts until a game restart.
	local cam_type = ctx.args.cam_type or 'DEFAULT_SCRIPTED_CAMERA'
	local any0 = native.new('Any', 1) -- RedLua only accepts this for "Any" parameters
	local cams = {}
	local function new_cam(at)
		local pitch, yaw = look_rot(at)
		local cam = ctx.call('CAM', 'CREATE_CAM_WITH_PARAMS', cam_type, at.x, at.y, at.z, pitch, 0.0, yaw, fov, false, 2)
		cams[#cams + 1] = cam
		return cam
	end
	local function set_pose(cam, at)
		local pitch, yaw = look_rot(at)
		ctx.call('CAM', 'SET_CAM_COORD', cam, at.x, at.y, at.z)
		ctx.call('CAM', 'SET_CAM_ROT', cam, pitch, 0.0, yaw, 2)
	end

	-- freeze=photo (default) uses the photo-mode freeze; freeze=paused uses SET_GAME_PAUSED.
	local freeze_kind = ctx.args.freeze or 'photo'
	local function freeze(on)
		if freeze_kind == 'paused' then
			ctx.call('MISC', 'SET_GAME_PAUSED', on)
		else
			ctx.call('ANIMSCENE', on and '_REQUEST_PHOTO_MODE_FREEZE' or '_REQUEST_PHOTO_MODE_DEFREEZE')
		end
	end

	ctx.defer(function()
		pcall(native.call, 'MISC', 'SET_GAME_PAUSED', false)
		pcall(native.call, 'ANIMSCENE', '_REQUEST_PHOTO_MODE_DEFREEZE')
		native.call('MISC', 'SET_TIME_SCALE', 1.0)
		native.call('CAM', 'RENDER_SCRIPT_CAMS', false, false, 0, true, false, 0)
		for _, cam in ipairs(cams) do
			pcall(native.call, 'CAM', 'SET_CAM_ACTIVE', cam, false)
			pcall(native.call, 'CAM', 'DESTROY_CAM', cam, false)
		end
	end)

	local home = pose(0)
	local cam = new_cam(home)
	ctx.call('CAM', 'SET_CAM_ACTIVE', cam, true)
	ctx.call('CAM', 'RENDER_SCRIPT_CAMS', true, false, 0, true, false, 0)
	ctx.wait(60)
	ctx.log('at home pose, live: camera misses the target by %.3f m', miss(home))

	local angle = 0
	for _, test in ipairs(wanted) do
		-- Start every strategy frozen at the current pose.
		ctx.call('MISC', 'SET_TIME_SCALE', 1.0)
		freeze(true)
		ctx.wait(20)
		local before = bone_positions()

		angle = angle + 45
		local target = pose(angle)
		local thaw = tonumber(test:match('^thaw(%d+)$'))

		if test == 'plain' then
			set_pose(cam, target)
		elseif test == 'params' then
			-- The argument pattern the game's photo-mode script uses.
			local pitch, yaw = look_rot(target)
			ctx.call('CAM', 'SET_CAM_PARAMS', cam, target.x, target.y, target.z, pitch, 0.0, yaw, fov,
				any0, 1, 1, 2, any0, any0)
		elseif test == 'pausethreads' then
			-- The game's photo script pauses the other script threads after freezing.
			ctx.call('ANIMSCENE', '_PAUSE_SCRIPT_THREADS', true)
			ctx.defer(function() pcall(native.call, 'ANIMSCENE', '_PAUSE_SCRIPT_THREADS', false) end)
			set_pose(cam, target)
			ctx.wait(20)
			local pitch, yaw = look_rot(target)
			ctx.call('CAM', 'SET_CAM_PARAMS', cam, target.x, target.y, target.z, pitch, 0.0, yaw, fov,
				any0, 1, 1, 2, any0, any0)
			ctx.wait(20)
			ctx.call('ANIMSCENE', '_PAUSE_SCRIPT_THREADS', false)
		elseif test == 'photocam' then
			-- Unnamed natives the game's photo script calls every frame while frozen.
			-- Crash risk: their meaning is unknown.
			local function getters()
				local out = {}
				for _, h in ipairs({ '_0x14C4A49E36C29E49', '_0xF824530B612FE0CE', '_0xEF9A3132A0AA6B19', '_0x2AB7C81B3F70570C' }) do
					local ok, v = ctx.try('CAM', h)
					out[#out + 1] = h:sub(1, 8) .. '=' .. tostring(ok and v or 'ERR')
				end
				return table.concat(out, ' ')
			end
			ctx.log('photocam getters before: %s', getters())
			for _ = 1, 40 do
				ctx.try('CAM', '_0x3C8F74E8FE751614')
				ctx.try('CAM', '_0x8505E05FC8822843', any0)
				set_pose(cam, target)
				ctx.wait(1)
			end
			ctx.log('photocam getters after: %s', getters())
		elseif test == 'newcam' then
			local fresh = new_cam(target)
			ctx.call('CAM', 'SET_CAM_ACTIVE', fresh, true)
			ctx.call('CAM', 'SET_CAM_ACTIVE', cam, false)
			ctx.call('CAM', 'RENDER_SCRIPT_CAMS', true, false, 0, true, false, 0)
			cam = fresh
		elseif thaw then
			-- Release the freeze for a few ticks at time scale 0 so the camera
			-- system runs, then freeze again.
			ctx.call('MISC', 'SET_TIME_SCALE', 0.0)
			set_pose(cam, target)
			freeze(false)
			ctx.wait(thaw)
			freeze(true)
		else
			error('unknown test: ' .. test)
		end

		ctx.wait(20)
		local off = miss(target)
		local shift = bone_shift(before, bone_positions())
		ctx.log('%-7s camera misses the target by %.3f m (%s); bones moved %.6f m; set-cam reads %.3f m off',
			test, off, off < 0.01 and 'MOVED' or 'did not move', shift,
			(function()
				local c = ctx.call('CAM', 'GET_CAM_COORD', cam)
				local dx, dy, dz = c.x - target.x, c.y - target.y, c.z - target.z
				return math.sqrt(dx * dx + dy * dy + dz * dz)
			end)())
		ctx.result[test .. '_miss_m'] = string.format('%.3f', off)
		ctx.result[test .. '_bones_m'] = string.format('%.6f', shift)
		if shots then
			ctx.capture('after_' .. test)
		end

		-- Thaw fully between strategies so each starts from a clean state.
		ctx.call('MISC', 'SET_TIME_SCALE', 1.0)
		freeze(false)
		ctx.wait(30)
	end
end
