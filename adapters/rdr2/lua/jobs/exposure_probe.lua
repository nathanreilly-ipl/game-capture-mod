-- Is a dark take the scene or the exposure lock? Captures the gameplay view, then
-- the same view after locking the photo-mode exposure, and logs the game clock.
return function(ctx)
	ctx.result.clock = string.format('%02d:%02d', ctx.call('CLOCK', 'GET_CLOCK_HOURS'), ctx.call('CLOCK', 'GET_CLOCK_MINUTES'))
	ctx.wait(30)
	ctx.capture('a_unlocked')
	ctx.call('GRAPHICS', '_SET_PHOTO_MODE_EXPOSURE_LOCKED', true)
	ctx.defer(function() pcall(native.call, 'GRAPHICS', '_SET_PHOTO_MODE_EXPOSURE_LOCKED', false) end)
	ctx.wait(40)
	ctx.capture('b_locked')
	ctx.call('ANIMSCENE', '_REQUEST_PHOTO_MODE_FREEZE')
	ctx.defer(function() pcall(native.call, 'ANIMSCENE', '_REQUEST_PHOTO_MODE_DEFREEZE') end)
	ctx.wait(60)
	ctx.capture('c_locked_frozen')
	ctx.call('GRAPHICS', '_SET_PHOTO_MODE_EXPOSURE_LOCKED', false)
	ctx.wait(60)
	ctx.capture('d_unlocked_frozen')
end
