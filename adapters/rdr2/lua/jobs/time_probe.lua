-- Measures what SET_TIME_SCALE does to the game's own clocks: logs the game
-- timer and frame time at normal speed, at time scale 0, and across single-tick
-- advances. Restores normal speed when it ends.
--
-- Extra command arguments: scale=<frozen time scale, default 0>
return function(ctx)
	local frozen_scale = tonumber(ctx.args.scale) or 0.0

	local function sample(label, frames)
		local first = ctx.call('MISC', 'GET_GAME_TIMER')
		local last = first
		for i = 1, frames do
			ctx.wait(1)
			local now = ctx.call('MISC', 'GET_GAME_TIMER')
			ctx.log('%s tick %2d: game timer %s ms (+%s), frame time %.5f s', label, i,
				tostring(now), tostring(now - last), ctx.call('MISC', 'GET_FRAME_TIME'))
			last = now
		end
		return last - first
	end

	ctx.defer(function() native.call('MISC', 'SET_TIME_SCALE', 1.0) end)

	ctx.result.normal_ms_over_20_ticks = sample('normal', 20)

	ctx.call('MISC', 'SET_TIME_SCALE', frozen_scale)
	ctx.wait(5) -- let the change take effect before measuring
	ctx.result.frozen_ms_over_20_ticks = sample('frozen', 20)

	-- One tick at normal speed between frozen stretches, three times over.
	for step = 1, 3 do
		local before = ctx.call('MISC', 'GET_GAME_TIMER')
		ctx.call('MISC', 'SET_TIME_SCALE', 1.0)
		ctx.wait(1)
		ctx.call('MISC', 'SET_TIME_SCALE', frozen_scale)
		ctx.wait(5)
		local after = ctx.call('MISC', 'GET_GAME_TIMER')
		ctx.log('step %d: one normal tick advanced the game timer by %s ms', step, tostring(after - before))
		ctx.result['step_' .. step .. '_ms'] = after - before
	end
end
