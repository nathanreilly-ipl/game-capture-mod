-- Run with probes/repl.py --file. Two questions in one go:
--   1. Does the player's first-person camera component follow SetLocalPosition/SetLocalOrientation,
--      and in which frame are they?
--   2. With the world's time dilation near zero: does simulation time stand still, and does the
--      rendered camera still follow a moved camera component?
local p = Game.GetPlayer()
local cam = p:GetFPPCameraComponent()
local cs = Game.GetCameraSystem()
local ts = Game.GetTimeSystem()

local function v(x) return string.format('%.4f %.4f %.4f', x.x, x.y, x.z) end
local function q(x) return string.format('%.5f %.5f %.5f %.5f', x.i, x.j, x.k, x.r) end
local function sim() return EngineTime.ToDouble(ts:GetSimTime()) end
local function show(label)
	local tr = Transform.new()   -- filled in place
	local ok = cs:GetActiveCameraWorldTransform(tr)
	out(string.format('%-22s cam_world=%s  fwd=%s  up=%s  fov=%.3f', label, ok and v(tr.position) or '?',
		v(cs:GetActiveCameraForward()), v(cs:GetActiveCameraUp()), cs:GetActiveCameraFOV()))
	out(string.format('%-22s local_pos=%s  local_rot=%s  player=%s  yaw=%.3f  sim=%.6f  dil=%s', '',
		v(cam:GetLocalPosition()), q(cam:GetLocalOrientation()), v(p:GetWorldPosition()), p:GetWorldYaw(), sim(),
		tostring(ts:GetActiveTimeDilation())))
end

show('start')
local pos0, rot0 = cam:GetLocalPosition(), cam:GetLocalOrientation()
cam:SetLocalPosition(Vector4.new(0.0, -3.0, 1.0, 1.0))
after(10, function()
	show('local (0,-3,1)')
	cam:SetLocalPosition(Vector4.new(2.0, 0.0, 0.0, 1.0))
	after(10, function()
		show('local (2,0,0)')
		ts:SetTimeDilation('capture_probe', 0.0000001)
		after(30, function()
			show('dilation 1e-7, +30f')
			local s0 = sim()
			cam:SetLocalPosition(Vector4.new(0.0, -5.0, 2.0, 1.0))
			after(60, function()
				show('frozen, local (0,-5,2)')
				out(string.format('sim advanced %.9f s over 60 frames while frozen', sim() - s0))
				ts:UnsetTimeDilation('capture_probe')
				cam:SetLocalPosition(pos0)
				cam:SetLocalOrientation(rot0)
				after(10, function()
					show('restored')
					done()
				end)
			end)
		end)
	end)
end)
return ASYNC
