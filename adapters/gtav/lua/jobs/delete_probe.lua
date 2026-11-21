-- Which way of removing a person works in GTA V through RedLua? Spawns four random people next to
-- the player and removes each a different way, then reports whether each still exists and where.
--   A  DELETE_ENTITY on a native.new('Entity') array holding the handle
--   B  DELETE_PED on a native.new('Ped') array holding the handle
--   C  DELETE_ENTITY on the person's own slot of a native.allpeds pool
--   D  moved 300 m down (SET_ENTITY_COORDS_NO_OFFSET), position frozen
return function(ctx)
	local ped = ctx.call('PLAYER', 'PLAYER_PED_ID')
	local p0 = ctx.call('ENTITY', 'GET_ENTITY_COORDS', ped, true)
	local people = {}
	for i, way in ipairs({ 'A', 'B', 'C', 'D' }) do
		local q = ctx.call('PED', 'CREATE_RANDOM_PED', p0.x + 2 * i, p0.y + 2, p0.z)
		people[way] = q
		ctx.log('%s: created %s', way, tostring(q))
	end
	ctx.wait(30)
	for way, q in pairs(people) do
		ctx.try('ENTITY', 'SET_ENTITY_AS_MISSION_ENTITY', q, true, true)
	end
	-- A
	local ra = native.new('Entity', 1)
	ra[0] = people.A
	ctx.log('A: array holds %s', tostring(ra[0]))
	ctx.result.A_call = tostring(select(1, ctx.try('ENTITY', 'DELETE_ENTITY', ra)))
	-- B
	local rb = native.new('Ped', 1)
	rb[0] = people.B
	ctx.result.B_call = tostring(select(1, ctx.try('PED', 'DELETE_PED', rb)))
	-- C
	local pool = native.new('Entity', 1024)
	local n = native.allpeds(pool)
	local key = tostring(people.C)
	local hit = false
	for i = 0, n - 1 do
		local ok, v = ctx.try('ENTITY', 'GET_PED_INDEX_FROM_ENTITY_INDEX', pool[i])
		if ok and tostring(v) == key then
			ctx.result.C_call = tostring(select(1, ctx.try('ENTITY', 'DELETE_ENTITY', pool[i])))
			hit = true
			break
		end
	end
	ctx.result.C_found_in_pool = tostring(hit)
	-- D
	ctx.try('ENTITY', 'FREEZE_ENTITY_POSITION', people.D, true)
	ctx.result.D_call = tostring(select(1, ctx.try('ENTITY', 'SET_ENTITY_COORDS_NO_OFFSET', people.D, p0.x, p0.y, p0.z - 300.0, false, false, false)))
	ctx.wait(10)
	for way, q in pairs(people) do
		local _, exists = ctx.try('ENTITY', 'DOES_ENTITY_EXIST', q)
		local okc, c = ctx.try('ENTITY', 'GET_ENTITY_COORDS', q, true)
		ctx.result[way .. '_exists'] = tostring(exists)
		ctx.result[way .. '_z'] = okc and string.format('%.1f', c.z) or '-'
	end
	-- clean up whatever is left
	for _, q in pairs(people) do
		local r = native.new('Entity', 1)
		r[0] = q
		pcall(native.call, 'ENTITY', 'SET_ENTITY_COORDS_NO_OFFSET', q, p0.x, p0.y, p0.z - 300.0, false, false, false)
	end
end
