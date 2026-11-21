-- Checks that the loader runs jobs in GTA V: the player, the rendered camera, the clocks, and
-- one frame through the capture add-on.
return function(ctx)
	local ver, game = misc.gamever()
	ctx.result.game = tostring(game) .. ' ' .. tostring(ver)
	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local pos = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true)
	ctx.result.player_pos = string.format('%.3f %.3f %.3f', pos.x, pos.y, pos.z)
	ctx.result.player_heading = string.format('%.2f', ctx.call('ENTITY', 'GET_ENTITY_HEADING', ped))
	local cam = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD')
	local rot = ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_ROT', 2)
	ctx.result.cam = string.format('%.3f %.3f %.3f rot %.2f %.2f %.2f fov %.2f', cam.x, cam.y, cam.z, rot.x, rot.y, rot.z,
		ctx.call('CAM', 'GET_FINAL_RENDERED_CAM_FOV'))
	ctx.result.clock = string.format('%02d:%02d', ctx.call('CLOCK', 'GET_CLOCK_HOURS'), ctx.call('CLOCK', 'GET_CLOCK_MINUTES'))
	local t0, f0 = ctx.call('MISC', 'GET_GAME_TIMER'), ctx.call('MISC', 'GET_FRAME_COUNT')
	ctx.wait(60)
	ctx.result.timer_ms_per_60_ticks = ctx.call('MISC', 'GET_GAME_TIMER') - t0
	ctx.result.frames_per_60_ticks = ctx.call('MISC', 'GET_FRAME_COUNT') - f0
	ctx.result.pause_menu = tostring(ctx.call('HUD', 'IS_PAUSE_MENU_ACTIVE'))
	local ack = ctx.capture('smoke')
	ctx.result.frame = tostring(ack.file) .. ' ' .. tostring(ack.width) .. 'x' .. tostring(ack.height)
end
