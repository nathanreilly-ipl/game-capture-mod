-- Finds out what RedLua accepts for a native parameter typed "Any", using
-- SET_CAM_PARAMS on a camera that is never rendered. Changes nothing visible.
return function(ctx)
	local ffi = require('ffi')
	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local p = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)

	local ok, cam = ctx.try('CAM', 'CREATE_CAM_WITH_PARAMS', 'KIT_CAMERA', p.x, p.y, p.z + 3.0, 0.0, 0.0, 0.0, 50.0, false, 2)
	ctx.log('CREATE_CAM_WITH_PARAMS KIT_CAMERA -> %s %s', tostring(ok), tostring(cam))
	if not ok then
		cam = ctx.call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
	end
	ctx.defer(function() pcall(native.call, 'CAM', 'DESTROY_CAM', cam, false) end)

	local candidates = {
		{ 'native.new Any', function()
			local o = native.new('Any', 1)
			ctx.log('native.new(Any, 1) -> %s (%s)', tostring(o), type(o))
			return o
		end },
		{ 'ffi int64', function() return ffi.new('int64_t', 0) end },
		{ 'ffi int[1]', function() return ffi.new('int[1]', 0) end },
		{ 'nil', function() return nil end },
		{ 'false', function() return false end },
		{ 'string', function() return '0' end },
		{ 'cam handle', function() return cam end },
	}

	local z = p.z + 3.0
	for i, c in ipairs(candidates) do
		local made, value = pcall(c[2])
		if not made then
			ctx.log('%-14s could not be built: %s', c[1], tostring(value))
		else
			z = p.z + 3.0 + i
			local called, err = ctx.try('CAM', 'SET_CAM_PARAMS', cam, p.x, p.y, z, 0.0, 0.0, 0.0, 50.0,
				value, 1, 1, 2, value, value)
			local now = ctx.call('CAM', 'GET_CAM_COORD', cam)
			ctx.log('%-14s call %s%s; cam z is now %.3f (wanted %.3f)', c[1], called and 'ok' or 'FAILED',
				called and '' or (': ' .. tostring(err)), now.z, z)
			ctx.result[(c[1]:gsub('[^%w]', '_'))] = called and string.format('ok dz=%.3f', now.z - z) or 'failed'
		end
		ctx.wait(2)
	end
end
