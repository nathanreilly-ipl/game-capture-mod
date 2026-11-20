-- Checks that the loader can run a job: reads the player and camera state and
-- logs a few frames of timing. Changes nothing in the game.
return function(ctx)
	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local ok, pos = ctx.try('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
	if ok and pos then
		ctx.log('player ped %s at %.3f, %.3f, %.3f', tostring(ped), pos.x, pos.y, pos.z)
		ctx.result.player_pos = string.format('%.3f,%.3f,%.3f', pos.x, pos.y, pos.z)
	else
		ctx.log('could not read the player position: %s', tostring(pos))
	end

	local cam = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD')
	local rot = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_ROT', 2)
	local fov = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_FOV')
	ctx.log('camera at %.3f, %.3f, %.3f  rot %.3f, %.3f, %.3f  fov %.3f',
		cam.x, cam.y, cam.z, rot.x, rot.y, rot.z, fov)
	ctx.result.cam_pos = string.format('%.3f,%.3f,%.3f', cam.x, cam.y, cam.z)
	ctx.result.cam_rot = string.format('%.3f,%.3f,%.3f', rot.x, rot.y, rot.z)
	ctx.result.cam_fov = string.format('%.3f', fov)

	for i = 1, 5 do
		ctx.log('tick %d: game timer %s ms, frame time %.5f s, frame count %s', i,
			tostring(ctx.call('MISC', 'GET_GAME_TIMER')),
			ctx.call('MISC', 'GET_FRAME_TIME'),
			tostring(ctx.call('MISC', 'GET_FRAME_COUNT')))
		ctx.wait(1)
	end
end
