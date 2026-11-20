-- capture_orbit.lua
-- RedLua script: freezes the game, steps a script camera around the player,
-- and asks the ReShade add-on (capture_mod.addon64) to save one image per pose.
--
-- F9  = start a capture session around the player (needs the add-on)
-- F8  = preview: step through the same poses in a loop, no add-on, nothing saved
-- F10 = stop either one and restore the game camera (F8 also stops a preview)
--
-- Handshake with the add-on (both sides use CFG.out_dir):
--   this script writes  request.txt : id=<id>, name=<session>/<image stem>
--   the add-on saves    <name>.bmp, deletes request.txt, then writes
--                       ack.txt     : id, status, message, file, width, height
-- A pose only advances after the matching ack arrives.

local CFG = {
	-- Must match OutputDir in ReShade.ini [CAPTURE_MOD]. Created on load if missing.
	out_dir = (os.getenv('USERPROFILE') or 'C:') .. '\\Documents\\RDR2Modding\\captures',

	key_start = VK_F9,
	key_preview = VK_F8 or 0x77,
	key_abort = VK_F10,

	-- Ticks to hold each pose in preview mode.
	preview_hold_frames = 20,

	-- Camera rings around the player. height is relative to the ped origin.
	rings = {
		{ radius = 6.0, height = 0.5, count = 16 },
		{ radius = 6.0, height = 3.0, count = 16 },
	},
	target_height = 0.0, -- look-at point, relative to the ped origin
	fov = 50.0,          -- degrees

	-- Ticks to hold each pose before capturing (TAA history, streaming, LODs).
	settle_frames = 8,
	-- Seconds to wait for the add-on before giving up.
	ack_timeout_s = 10,

	-- Time steps. Each sweep visits every pose once; between sweeps the game
	-- runs for advance_frames ticks at normal speed, then freezes again.
	sweeps = 1,
	advance_frames = 1,

	freeze_time = true,
	frozen_time_scale = 0.0,
	set_streaming_focus = true,
	hide_hud = true,
}

local REQUIRED_NATIVES = {
	{ 'CAM', 'CREATE_CAM' },
	{ 'CAM', 'SET_CAM_ACTIVE' },
	{ 'CAM', 'RENDER_SCRIPT_CAMS' },
	{ 'CAM', 'SET_CAM_COORD' },
	{ 'CAM', 'POINT_CAM_AT_COORD' },
	{ 'CAM', 'SET_CAM_FOV' },
	{ 'CAM', 'DESTROY_CAM' },
	{ 'CAM', 'GET_FINAL_RENDERED_CAM_COORD' },
	{ 'CAM', 'GET_FINAL_RENDERED_CAM_ROT' },
	{ 'CAM', 'GET_FINAL_RENDERED_CAM_FOV' },
}

-- All of these exist in RedLua's natives.json. The script still runs if one
-- fails in game and logs it once.
local OPTIONAL_NATIVES = {
	{ 'PLAYER', 'PLAYER_ID' },
	{ 'PLAYER', 'GET_PLAYER_PED' },
	{ 'ENTITY', 'GET_ENTITY_COORDS' },
	{ 'MISC', 'SET_TIME_SCALE' },
	{ 'CLOCK', 'PAUSE_CLOCK' },
	{ 'STREAMING', 'SET_FOCUS_POS_AND_VEL' },
	{ 'STREAMING', 'CLEAR_FOCUS' },
	{ 'HUD', 'HIDE_HUD_AND_RADAR_THIS_FRAME' },
}

local ROTATION_ORDER = 2

local t = {}
local S = { state = 'idle' }
local warned = {}
local req_counter = 0

local function log(fmt, ...)
	local msg = string.format(fmt, ...)
	print('[capture_orbit] ' .. msg)
	local f = io.open(CFG.out_dir .. '\\capture_orbit.log', 'a')
	if f then
		f:write(os.date('%Y-%m-%d %H:%M:%S '), msg, '\n')
		f:close()
	end
end

-- Creates CFG.out_dir and any missing parent folders through the Windows API.
local function ensure_out_dir()
	local ok, ffi = pcall(require, 'ffi')
	if not ok then
		return
	end
	pcall(ffi.cdef, 'int CreateDirectoryA(const char *path, void *security);')
	local path = CFG.out_dir
	local from = 4 -- skip the drive, e.g. "C:\"
	while true do
		local sep = path:find('\\', from, true)
		local prefix = sep and path:sub(1, sep - 1) or path
		-- Fails harmlessly for levels that already exist.
		pcall(function() ffi.C.CreateDirectoryA(prefix, nil) end)
		if not sep then
			break
		end
		from = sep + 1
	end
end

local function out_dir_writable()
	ensure_out_dir()
	local f = io.open(CFG.out_dir .. '\\capture_orbit.log', 'a')
	if f then
		f:close()
		return true
	end
	return false
end

-- Calls a native and returns its result, or nil if the call fails.
-- Each failing native is logged once.
local function call(ns, name, ...)
	local ok, res = pcall(native.call, ns, name, ...)
	if ok then
		return res
	end
	local key = ns .. '::' .. name
	if not warned[key] then
		warned[key] = true
		log('native %s failed: %s', key, tostring(res))
	end
	return nil
end

local function describe_native(ns, name)
	local info = native.info(ns, name)
	if not info then
		return nil
	end
	local params = {}
	for i, p in ipairs(info.params or {}) do
		params[i] = tostring(p.type) .. ' ' .. tostring(p.name)
	end
	return string.format('%s %s::%s(%s)', tostring(info.returns), ns, name, table.concat(params, ', '))
end

local function check_natives()
	local missing_required = 0
	for _, n in ipairs(REQUIRED_NATIVES) do
		local sig = describe_native(n[1], n[2])
		if sig then
			log('native ok: %s', sig)
		else
			missing_required = missing_required + 1
			log('native MISSING (required): %s::%s', n[1], n[2])
		end
	end
	for _, n in ipairs(OPTIONAL_NATIVES) do
		local sig = describe_native(n[1], n[2])
		if sig then
			log('native ok: %s', sig)
		else
			log('native missing (optional): %s::%s', n[1], n[2])
		end
	end
	return missing_required == 0
end

local function vec(v)
	return { x = v.x, y = v.y, z = v.z }
end

local function orbit_center()
	local player = call('PLAYER', 'PLAYER_ID')
	local ped = player and call('PLAYER', 'GET_PLAYER_PED', player)
	local coords = ped and call('ENTITY', 'GET_ENTITY_COORDS', ped, true, true)
	if coords then
		return vec(coords)
	end
	log('could not read the player position; orbiting the current camera position instead')
	return vec(native.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD'))
end

local function build_poses(center)
	local poses = {}
	for _, ring in ipairs(CFG.rings) do
		for i = 0, ring.count - 1 do
			local a = (i / ring.count) * 2 * math.pi
			poses[#poses + 1] = {
				x = center.x + ring.radius * math.cos(a),
				y = center.y + ring.radius * math.sin(a),
				z = center.z + ring.height,
			}
		end
	end
	return poses
end

local function freeze(on)
	if not CFG.freeze_time then
		return
	end
	call('MISC', 'SET_TIME_SCALE', on and CFG.frozen_time_scale or 1.0)
	call('CLOCK', 'PAUSE_CLOCK', on, 0)
end

local function place_camera()
	local p = S.poses[S.cam_index]
	local tg = S.target
	native.call('CAM', 'SET_CAM_COORD', S.cam, p.x, p.y, p.z)
	native.call('CAM', 'POINT_CAM_AT_COORD', S.cam, tg.x, tg.y, tg.z)
	native.call('CAM', 'SET_CAM_FOV', S.cam, CFG.fov)
	if CFG.set_streaming_focus then
		call('STREAMING', 'SET_FOCUS_POS_AND_VEL', tg.x, tg.y, tg.z, 0.0, 0.0, 0.0)
	end
	S.wait = S.preview and CFG.preview_hold_frames or CFG.settle_frames
	S.state = 'settle'
end

local function image_stem()
	return string.format('t%04d_c%03d', S.sweep - 1, S.cam_index - 1)
end

local function send_request()
	req_counter = req_counter + 1
	S.req_id = string.format('%s_%d', S.session, req_counter)
	local tmp = CFG.out_dir .. '\\request.tmp'
	local dst = CFG.out_dir .. '\\request.txt'
	local f, err = io.open(tmp, 'w')
	if not f then
		error('cannot write ' .. tmp .. ': ' .. tostring(err))
	end
	f:write('id=', S.req_id, '\n', 'name=', S.session, '/', image_stem(), '\n')
	f:close()
	os.remove(dst)
	local ok, rerr = os.rename(tmp, dst)
	if not ok then
		error('cannot publish request.txt: ' .. tostring(rerr))
	end
	S.deadline = os.time() + CFG.ack_timeout_s
	S.state = 'wait_ack'
end

local function read_ack()
	local f = io.open(CFG.out_dir .. '\\ack.txt', 'r')
	if not f then
		return nil
	end
	local text = f:read('*a')
	f:close()
	local ack = {}
	for k, v in text:gmatch('([%w_]+)=([^\r\n]*)') do
		ack[k] = v
	end
	return ack
end

local function record_pose(ack)
	local pos = vec(native.call('CAM', 'GET_FINAL_RENDERED_CAM_COORD'))
	local rot = vec(native.call('CAM', 'GET_FINAL_RENDERED_CAM_ROT', ROTATION_ORDER))
	local fov = native.call('CAM', 'GET_FINAL_RENDERED_CAM_FOV')
	local req = S.poses[S.cam_index]
	local line = string.format(
		'{"image":"%s.bmp","t":%d,"cam":%d,' ..
		'"pos":[%.6f,%.6f,%.6f],"rot_deg":[%.6f,%.6f,%.6f],"rot_order":%d,"fov_deg":%.6f,' ..
		'"requested_pos":[%.6f,%.6f,%.6f],"target":[%.6f,%.6f,%.6f],' ..
		'"width":%d,"height":%d}\n',
		image_stem(), S.sweep - 1, S.cam_index - 1,
		pos.x, pos.y, pos.z, rot.x, rot.y, rot.z, ROTATION_ORDER, tonumber(fov) or CFG.fov,
		req.x, req.y, req.z, S.target.x, S.target.y, S.target.z,
		tonumber(ack.width) or 0, tonumber(ack.height) or 0)
	-- The add-on created the session folder when it saved the image.
	local path = CFG.out_dir .. '\\' .. S.session .. '\\poses.jsonl'
	local f, err = io.open(path, 'a')
	if not f then
		error('cannot write ' .. path .. ': ' .. tostring(err))
	end
	f:write(line)
	f:close()
	S.saved = S.saved + 1
end

local function end_session(reason)
	if S.state == 'idle' then
		return
	end
	if S.cam then
		call('CAM', 'RENDER_SCRIPT_CAMS', false, false, 0, true, false, 0)
		call('CAM', 'SET_CAM_ACTIVE', S.cam, false)
		call('CAM', 'DESTROY_CAM', S.cam, false)
	end
	if CFG.set_streaming_focus then
		call('STREAMING', 'CLEAR_FOCUS')
	end
	freeze(false)
	os.remove(CFG.out_dir .. '\\request.txt')
	log('%s ended (%s): %d images saved', tostring(S.session), reason, S.saved or 0)
	S = { state = 'idle' }
end

local function begin_session(preview)
	if not preview and not out_dir_writable() then
		error('output folder ' .. CFG.out_dir .. ' is missing and could not be created')
	end
	S.preview = preview
	S.session = os.date(preview and 'preview_%Y%m%d_%H%M%S' or 'session_%Y%m%d_%H%M%S')
	S.saved = 0
	S.sweep = 1
	S.cam_index = 1
	S.state = 'starting'

	local center = orbit_center()
	S.target = { x = center.x, y = center.y, z = center.z + CFG.target_height }
	S.poses = build_poses(center)

	S.cam = native.call('CAM', 'CREATE_CAM', 'DEFAULT_SCRIPTED_CAMERA', true)
	if not S.cam then
		error('CREATE_CAM returned nothing')
	end
	native.call('CAM', 'SET_CAM_ACTIVE', S.cam, true)
	native.call('CAM', 'RENDER_SCRIPT_CAMS', true, false, 0, true, false, 0)

	freeze(true)
	if preview then
		log('%s: looping %d poses around %.2f, %.2f, %.2f, nothing is saved',
			S.session, #S.poses, center.x, center.y, center.z)
	else
		log('session %s: %d poses x %d sweeps around %.2f, %.2f, %.2f',
			S.session, #S.poses, CFG.sweeps, center.x, center.y, center.z)
	end
	place_camera()
end

local function next_pose()
	if S.cam_index < #S.poses then
		S.cam_index = S.cam_index + 1
		place_camera()
	elseif S.preview then
		S.cam_index = 1
		place_camera()
	elseif S.sweep < CFG.sweeps then
		S.sweep = S.sweep + 1
		S.cam_index = 1
		freeze(false)
		S.wait = CFG.advance_frames
		S.state = 'advance'
	else
		end_session('complete')
	end
end

local function step()
	if CFG.hide_hud then
		call('HUD', 'HIDE_HUD_AND_RADAR_THIS_FRAME')
	end

	if S.state == 'settle' then
		S.wait = S.wait - 1
		if S.wait <= 0 then
			if S.preview then
				next_pose()
			else
				send_request()
			end
		end
	elseif S.state == 'wait_ack' then
		local ack = read_ack()
		if ack and ack.id == S.req_id then
			if ack.status ~= 'ok' then
				error('add-on reported: ' .. tostring(ack.message))
			end
			record_pose(ack)
			next_pose()
		elseif os.time() > S.deadline then
			error('no ack from the add-on; is capture_mod.addon64 loaded and using ' .. CFG.out_dir .. '?')
		end
	elseif S.state == 'advance' then
		S.wait = S.wait - 1
		if S.wait <= 0 then
			freeze(true)
			place_camera()
		end
	end
end

local function guarded(fn)
	local ok, err = xpcall(fn, debug.traceback)
	if not ok then
		log('error: %s', tostring(err))
		end_session('error')
	end
end

function t.OnLoad()
	ensure_out_dir()
	log('loaded; output dir is %s', CFG.out_dir)
	S.natives_ok = check_natives()
	if not S.natives_ok then
		log('required natives are missing; F9 is disabled')
	end
end

function t.OnTick()
	if S.state == 'idle' then
		local start = misc.iskeyjustup(CFG.key_start, true)
		local preview = misc.iskeyjustup(CFG.key_preview, true)
		if start or preview then
			if S.natives_ok == false then
				log('cannot start: required natives are missing')
			else
				guarded(function() begin_session(preview and not start) end)
			end
		end
		return
	end

	local stop = misc.iskeyjustup(CFG.key_abort, true)
	if S.preview and misc.iskeyjustup(CFG.key_preview, true) then
		stop = true
	end
	if stop then
		end_session(S.preview and 'preview stopped' or 'aborted')
		return
	end

	guarded(step)
end

function t.OnStop()
	end_session('script stopped')
end

function t.OnReload()
	end_session('script reloaded')
end

return t
