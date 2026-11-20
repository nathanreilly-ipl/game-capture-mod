-- scout_overlay.lua
-- RedLua script for scouting capture locations. Draws, top left:
--   your position, heading and place name (from the game's map zones)
--   the nearest saved location (or the n-th nearest, F8): id, place name, distance, position;
--   red when it is closer than 25 m, so a near-duplicate is not scouted twice
-- Keys:
--   F11 show / hide the overlay
--   F8  next saved location (by distance)
--   F9  view that location: front, right, back, left of its facing at eye height, then off
--   F10 teleport there (facing its facing)
-- Saved locations come from the capture tool (capture scout / capture locations --publish),
-- which writes captures\scout\locations.txt and zone_names.txt. The overlay stays off the
-- screen while a capture session runs (captures\session_active.txt is fresh).

local DIR = (os.getenv('USERPROFILE') or 'C:') .. '\\Documents\\RDR2Modding\\captures'
-- F4 and F5 belong to Native Trainer, F6 to the game's camera mode, F7 to RedLua.
local KEY_TOGGLE, KEY_NEXT, KEY_VIEW, KEY_TP = 0x7A, 0x77, 0x78, 0x79 -- F11, F8, F9, F10
local NEAR_WARN_M = 25.0
local EYE_HEIGHT = 1.6
local VIEW_FOV = 60.0
local VIEW_DIRS = { { 'front', 0 }, { 'right', -90 }, { 'back', 180 }, { 'left', 90 } }

local t = {}
local S = { enabled = true, tick = 0, locs = {}, names = nil, order = {}, k = 1, title = '', active = false,
	view = nil, tp = nil, errors = {} }

local function log(msg)
	if S.errors[msg] then
		return
	end
	S.errors[msg] = true
	local f = io.open(DIR .. '\\scout_overlay.log', 'a')
	if f then
		f:write(os.date('%Y-%m-%d %H:%M:%S ') .. msg .. '\n')
		f:close()
	end
end

local function call(ns, name, ...)
	local ok, res = pcall(native.call, ns, name, ...)
	if not ok then
		log(ns .. '::' .. name .. ': ' .. tostring(res))
		return nil
	end
	return res
end

local function split(s, sep)
	local out = {}
	for part in (s .. sep):gmatch('(.-)' .. sep:gsub('%p', '%%%0')) do
		out[#out + 1] = part
	end
	return out
end

local function read_lines(path)
	local f = io.open(path, 'r')
	if not f then
		return nil
	end
	local lines = {}
	for line in f:lines() do
		if line ~= '' then
			lines[#lines + 1] = line
		end
	end
	f:close()
	return lines
end

local function load_names()
	local lines = read_lines(DIR .. '\\scout\\zone_names.txt')
	if not lines then
		return
	end
	S.names = {}
	for _, line in ipairs(lines) do
		local p = split(line, '|')
		S.names[tonumber(p[1])] = p[2]
	end
end

local function load_locations()
	local lines = read_lines(DIR .. '\\scout\\locations.txt') or {}
	local locs = {}
	for _, line in ipairs(lines) do
		local p = split(line, '|')
		if #p >= 6 then
			locs[#locs + 1] = { id = p[1], title = p[2], x = tonumber(p[3]), y = tonumber(p[4]), z = tonumber(p[5]),
				facing = tonumber(p[6]) }
		end
	end
	S.locs = locs
end

local function unsigned(h)
	h = tonumber(h) or 0
	if h < 0 then
		h = h + 4294967296
	end
	return h
end

local function place_title(x, y, z)
	if not S.names then
		return ''
	end
	local parts, seen = {}, {}
	for _, ty in ipairs({ 12, 11, 1, 'water', 10, 0 }) do
		local h
		if ty == 'water' then
			h = call('ZONE', '_GET_WATER_MAP_ZONE_AT_COORDS', x, y, z)
		else
			h = call('ZONE', '_GET_MAP_ZONE_AT_COORDS', x, y, z, ty)
		end
		local name = h and S.names[unsigned(h)]
		if name and not seen[name] and #parts < 3 then
			parts[#parts + 1] = name
			seen[name] = true
		end
	end
	return table.concat(parts, ' / ')
end

local function session_active()
	local f = io.open(DIR .. '\\session_active.txt', 'r')
	if not f then
		return false
	end
	local stamp = tonumber(f:read('*a')) or 0
	f:close()
	return os.time() - stamp < 60
end

-- Text: _BG_DISPLAY_TEXT wants a game string; build one with VAR_STRING if that works here.
local use_varstr = nil
local function text(s, x, y, scale, r, g, b)
	call('UIDEBUG', '_BG_SET_TEXT_SCALE', scale, scale)
	call('UIDEBUG', '_BG_SET_TEXT_COLOR', r, g, b, 235)
	if use_varstr ~= false then
		local ok, vs = pcall(native.call, 'MISC', 'VAR_STRING', 10, 'LITERAL_STRING', s)
		if ok and vs then
			use_varstr = true
			call('UIDEBUG', '_BG_DISPLAY_TEXT', vs, x, y)
			return
		end
		use_varstr = false
		log('VAR_STRING unavailable, drawing plain strings')
	end
	call('UIDEBUG', '_BG_DISPLAY_TEXT', s, x, y)
end

local function player()
	local ped = call('PLAYER', 'PLAYER_PED_ID')
	local p = ped and call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
	return ped, p
end

local function target()
	return S.order[S.k]
end

local function dist(a, x, y, z)
	return math.sqrt((a.x - x) ^ 2 + (a.y - y) ^ 2 + (a.z - z) ^ 2)
end

local function end_view()
	if S.view then
		call('CAM', 'RENDER_SCRIPT_CAMS', false, false, 0, true, false, 0)
		call('CAM', 'SET_CAM_ACTIVE', S.view.cam, false)
		call('CAM', 'DESTROY_CAM', S.view.cam, false)
		call('STREAMING', 'CLEAR_FOCUS')
		S.view = nil
	end
end

local function view_next()
	local loc = target()
	if not loc then
		return
	end
	local i = S.view and S.view.dir + 1 or 1
	if S.view and S.view.id ~= loc.id then
		i = 1
	end
	if i > #VIEW_DIRS then
		end_view()
		return
	end
	if not S.view then
		local cam = call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
		if not cam then
			return
		end
		S.view = { cam = cam }
		call('CAM', 'SET_CAM_ACTIVE', cam, true)
		call('CAM', 'RENDER_SCRIPT_CAMS', true, false, 0, true, false, 0)
	end
	S.view.id, S.view.dir = loc.id, i
	call('STREAMING', 'SET_FOCUS_POS_AND_VEL', loc.x, loc.y, loc.z, 0.0, 0.0, 0.0)
	call('CAM', 'SET_CAM_COORD', S.view.cam, loc.x, loc.y, loc.z + EYE_HEIGHT)
	call('CAM', 'SET_CAM_ROT', S.view.cam, 0.0, 0.0, loc.facing + VIEW_DIRS[i][2], 2)
	call('CAM', 'SET_CAM_FOV', S.view.cam, VIEW_FOV)
end

local function start_tp()
	local loc = target()
	local ped = player()
	if not loc or not ped then
		return
	end
	end_view()
	call('ENTITY', 'FREEZE_ENTITY_POSITION', ped, true)
	call('ENTITY', 'SET_ENTITY_COORDS', ped, loc.x, loc.y, loc.z + 1.0, false, false, false, false)
	call('ENTITY', 'SET_ENTITY_HEADING', ped, loc.facing)
	call('STREAMING', 'LOAD_SCENE_START', loc.x, loc.y, loc.z, 0.0, 0.0, 0.0, 200.0, 0)
	S.tp = { loc = loc, ticks = 0, ped = ped }
end

local function step_tp()
	local tp = S.tp
	local loc = tp.loc
	call('STREAMING', 'REQUEST_COLLISION_AT_COORD', loc.x, loc.y, loc.z)
	tp.ticks = tp.ticks + 1
	local coll = call('ENTITY', 'HAS_COLLISION_LOADED_AROUND_ENTITY', tp.ped)
	local scene = call('STREAMING', 'IS_LOAD_SCENE_LOADED')
	if not (tp.ticks >= 30 and coll and (scene or tp.ticks > 600)) and tp.ticks < 900 then
		return
	end
	call('STREAMING', 'LOAD_SCENE_STOP')
	local gz = native.new('float', 1)
	call('ENTITY', 'SET_ENTITY_COLLISION', tp.ped, false, false) -- the probe would hit the player
	if call('MISC', 'GET_GROUND_Z_FOR_3D_COORD', loc.x, loc.y, loc.z + 2.0, gz, false) then
		-- a ped set to z stands with its feet at z (it reads back at z + 1)
		call('ENTITY', 'SET_ENTITY_COORDS', tp.ped, loc.x, loc.y, gz[0], false, false, false, false)
	end
	call('ENTITY', 'SET_ENTITY_COLLISION', tp.ped, true, true)
	call('ENTITY', 'SET_ENTITY_HEADING', tp.ped, loc.facing)
	call('TASK', 'CLEAR_PED_TASKS_IMMEDIATELY', tp.ped, false, true)
	call('ENTITY', 'FREEZE_ENTITY_POSITION', tp.ped, false)
	S.tp = nil
end

local function fmt(x, y, z)
	return string.format('%.1f, %.1f, %.1f', x, y, z)
end

local function draw(p, heading)
	local x0, y, dy, sc = 0.012, 0.16, 0.032, 0.40
	-- dark panel behind the text (DRAW_RECT takes the centre)
	call('GRAPHICS', 'DRAW_RECT', 0.215, y + 3 * dy, 0.42, 6.5 * dy, 0, 0, 0, 150, false, false)
	local function line(s, r, g, b)
		text(s, x0, y, sc, r or 235, g or 235, b or 235)
		y = y + dy
	end
	line('CAPTURE SCOUT  (F11 hide)', 200, 200, 120)
	line(string.format('You  %s   heading %.0f', fmt(p.x, p.y, p.z), heading or 0))
	line('     ' .. (S.title ~= '' and S.title or '(no place name)'), 200, 200, 200)
	local loc = target()
	if not loc then
		line('No saved locations (run: capture locations --publish)', 200, 200, 200)
		return
	end
	local d = dist(loc, p.x, p.y, p.z)
	local r, g, b = 235, 235, 235
	if d < NEAR_WARN_M then
		r, g, b = 255, 90, 90
	elseif d < 100 then
		r, g, b = 255, 210, 90
	end
	line(string.format('%s %d/%d  %s   %.1f m', S.k == 1 and 'Nearest' or 'Saved', S.k, #S.order, loc.id, d), r, g, b)
	line('     ' .. (loc.title ~= '' and loc.title or '(untitled)') .. '   ' .. fmt(loc.x, loc.y, loc.z), 200, 200, 200)
	if S.view then
		line(string.format('Viewing %s: %s   (F9 next, F10 teleport)', S.view.id, VIEW_DIRS[S.view.dir][1]), 140, 200, 255)
	elseif S.tp then
		line('Teleporting...', 140, 200, 255)
	else
		line('F8 next   F9 view   F10 teleport', 170, 170, 170)
	end
end

function t.OnLoad()
	load_names()
	load_locations()
end

function t.OnTick()
	local ok, err = pcall(function()
		S.tick = S.tick + 1
		if S.tick % 30 == 0 then
			S.active = session_active()
		end
		if S.active then
			end_view()
			return
		end
		if S.tp then
			step_tp()
		end
		if misc.iskeyjustup(KEY_TOGGLE, true) then
			S.enabled = not S.enabled
			if not S.enabled then
				end_view()
			end
		end
		if not S.enabled then
			return
		end
		if S.tick % 120 == 1 then
			load_locations()
			if not S.names then
				load_names()
			end
		end
		local ped, p = player()
		if not p then
			return
		end
		if S.tick % 15 == 1 then
			local order = {}
			for _, loc in ipairs(S.locs) do
				order[#order + 1] = loc
			end
			table.sort(order, function(a, b) return dist(a, p.x, p.y, p.z) < dist(b, p.x, p.y, p.z) end)
			local keep = target() and target().id
			S.order = order
			if S.k ~= 1 and keep then
				S.k = 1
				for i, loc in ipairs(order) do
					if loc.id == keep then
						S.k = i
					end
				end
			end
		end
		if S.tick % 30 == 1 then
			S.title = place_title(p.x, p.y, p.z)
		end
		if misc.iskeyjustup(KEY_NEXT, true) and #S.order > 0 then
			S.k = S.k % #S.order + 1
			if S.view then
				S.view.dir = 0
				view_next()
			end
		end
		if misc.iskeyjustup(KEY_VIEW, true) then
			view_next()
		end
		if misc.iskeyjustup(KEY_TP, true) and not S.tp then
			start_tp()
		end
		draw(p, call('ENTITY', 'GET_ENTITY_HEADING', ped))
	end)
	if not ok then
		log('OnTick: ' .. tostring(err))
	end
end

function t.OnStop()
	end_view()
end

function t.OnReload()
	end_view()
end

return t
