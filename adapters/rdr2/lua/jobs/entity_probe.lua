-- Which way of reading an entity's size works? For the nearest human, animal and vehicle near the
-- player (nothing is deleted): model dimensions with the hash as returned / as a signed int32,
-- and the entity's world-space box corners.
return function(ctx)
	local player = native.call('PLAYER', 'PLAYER_PED_ID')
	local pp = native.call('ENTITY', 'GET_ENTITY_COORDS', player, true, true)
	local function v3(v) return string.format('%.2f %.2f %.2f', v[0].x, v[0].y, v[0].z) end
	local function dims(e)
		local out = {}
		local model = native.call('ENTITY', 'GET_ENTITY_MODEL', e)
		local signed = model >= 2147483648 and model - 4294967296 or model
		for label, h in pairs({ asis = model, signed = signed }) do
			local mn, mx = native.new('Vector3', 1), native.new('Vector3', 1)
			local ok, err = pcall(native.call, 'MISC', 'GET_MODEL_DIMENSIONS', h, mn, mx)
			out[#out + 1] = label .. (ok and (' ' .. v3(mn) .. ' / ' .. v3(mx)) or (' error ' .. tostring(err)))
		end
		local mn, mx = native.new('Vector3', 1), native.new('Vector3', 1)
		local ok, err = pcall(native.call, 'ENTITY', '_GET_ENTITY_WORLD_POSITION_OF_DIMENSIONS', e, mn, mx)
		local r, f, u, pos = native.new('Vector3', 1), native.new('Vector3', 1), native.new('Vector3', 1), native.new('Vector3', 1)
		native.call('ENTITY', 'GET_ENTITY_MATRIX', e, r, f, u, pos)
		local function loc(c)
			local d = { c[0].x - pos[0].x, c[0].y - pos[0].y, c[0].z - pos[0].z }
			local function dot(a) return d[1] * a[0].x + d[2] * a[0].y + d[3] * a[0].z end
			return string.format('%.2f %.2f %.2f', dot(r), dot(f), dot(u))
		end
		out[#out + 1] = 'world ' .. (ok and (v3(mn) .. ' / ' .. v3(mx)) or ('error ' .. tostring(err)))
		out[#out + 1] = string.format('heading %.0f', math.deg(math.atan2(-f[0].x, f[0].y)))
		out[#out + 1] = 'local (right fwd up) ' .. loc(mn) .. ' / ' .. loc(mx)
		return table.concat(out, ' | ')
	end
	local pool = native.new('Entity', 2048)
	local found = {}
	for _, kind in ipairs({ 'peds', 'vehicles' }) do
		local n = kind == 'peds' and native.allpeds(pool) or native.allvehicles(pool)
		for i = 0, n - 1 do
			local e = pool[i]
			local p = native.call('ENTITY', 'GET_ENTITY_COORDS', e, true, true)
			local d = math.sqrt((p.x - pp.x) ^ 2 + (p.y - pp.y) ^ 2)
			local label
			if kind == 'vehicles' then
				label = 'vehicle'
			elseif not native.call('PED', 'IS_PED_A_PLAYER', e) then
				label = native.call('PED', 'IS_PED_HUMAN', e) and 'human' or 'animal'
			end
			if label and d < 80 and (not found[label] or d < found[label].d) then
				found[label] = { e = e, d = d }
			end
		end
	end
	for label, f in pairs(found) do
		local ok, s = pcall(dims, f.e)
		ctx.result[label] = string.format('%.1f m: ', f.d) .. tostring(s)
	end
end
