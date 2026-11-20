-- RedLua returns PLAYER_ID() typed as Cam here ("Cam: 4354"), which Player natives reject.
-- Checks that a Player built with native.new('Player', 1) (value 0, the single-player index)
-- is our player: GET_PLAYER_PED of it must be PLAYER_PED_ID().
return function(ctx)
	local function try(label, fn)
		local ok, res = pcall(fn)
		ctx.result[label] = (ok and 'ok ' or 'error ') .. tostring(res)
	end
	local ped = native.call('PLAYER', 'PLAYER_PED_ID')
	ctx.result.ped = tostring(ped)
	ctx.result.player_id = tostring(native.call('PLAYER', 'PLAYER_ID'))
	local p = native.new('Player', 1)[0]
	ctx.result.made = tostring(p)
	try('ped_of_made', function() return tostring(native.call('PLAYER', 'GET_PLAYER_PED', p)) end)
	try('same_ped', function()
		local other = native.call('PLAYER', 'GET_PLAYER_PED', p)
		return tostring(native.call('ENTITY', 'GET_ENTITY_COORDS', other, true, true).x) .. ' vs '
			.. tostring(native.call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true).x)
	end)
	try('wanted_score', function() return native.call('LAW', 'GET_WANTED_SCORE', p) end)
	try('is_playing', function() return native.call('PLAYER', 'IS_PLAYER_PLAYING', p) end)
end
