-- First end-to-end check of the add-on: captures the gameplay view, then a
-- script camera looking at the player, live and frozen. The frozen frames are
-- taken from one pose at different moments, so any difference between them is
-- something time scale 0 did not stop.
--
-- Extra command arguments: radius, height, angle_deg, fov, gap (ticks between frozen frames)
return function(ctx)
	local radius = tonumber(ctx.args.radius) or 6.0
	local height = tonumber(ctx.args.height) or 1.5
	local angle = math.rad(tonumber(ctx.args.angle_deg) or 0)
	local fov = tonumber(ctx.args.fov) or 50.0
	local gap = tonumber(ctx.args.gap) or 120

	ctx.capture('00_gameplay')

	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local p = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
	local center = { x = p.x, y = p.y, z = p.z }

	local cam = ctx.call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
	ctx.defer(function()
		native.call('CAM', 'RENDER_SCRIPT_CAMS', false, false, 0, true, false, 0)
		native.call('CAM', 'SET_CAM_ACTIVE', cam, false)
		native.call('CAM', 'DESTROY_CAM', cam, false)
		native.call('MISC', 'SET_TIME_SCALE', 1.0)
	end)

	ctx.call('CAM', 'SET_CAM_COORD', cam,
		center.x + radius * math.cos(angle), center.y + radius * math.sin(angle), center.z + height)
	ctx.call('CAM', 'POINT_CAM_AT_COORD', cam, center.x, center.y, center.z)
	ctx.call('CAM', 'SET_CAM_FOV', cam, fov)
	ctx.call('CAM', 'SET_CAM_ACTIVE', cam, true)
	ctx.call('CAM', 'RENDER_SCRIPT_CAMS', true, false, 0, true, false, 0)

	local function report(label)
		local c = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD')
		local r = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_ROT', 2)
		ctx.log('%s: cam %.3f, %.3f, %.3f  rot %.3f, %.3f, %.3f  fov %.3f  game timer %s', label,
			c.x, c.y, c.z, r.x, r.y, r.z, ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_FOV'),
			tostring(ctx.call('MISC', 'GET_GAME_TIMER')))
	end

	ctx.wait(60)
	report('live a')
	ctx.capture('01_live_a')
	ctx.wait(gap)
	report('live b')
	ctx.capture('02_live_b')

	ctx.call('MISC', 'SET_TIME_SCALE', 0.0)
	ctx.wait(30)
	for i, name in ipairs({ '03_frozen_a', '04_frozen_b', '05_frozen_c' }) do
		report(name)
		local ack = ctx.capture(name)
		ctx.result.width, ctx.result.height = ack.width, ack.height
		if i < 3 then
			ctx.wait(gap)
		end
	end
end
