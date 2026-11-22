-- Run with probes/repl.py --file: the script-visible functions of the systems the adapter uses,
-- as Cyber Engine Tweaks sees them in this game version.
local types = {
	'gameTimeSystem', 'gameCameraSystem', 'gameTeleportationFacility', 'gameFPPCameraComponent',
	'entCameraComponent', 'gameSpatialQueriesSystem', 'inkISystemRequestsHandler', 'gameWeatherSystem',
	'gameTargetingSystem', 'gameSaveLocksManager', 'gameAutoSaveSystem', 'gamePhotoModeSystem',
	'gameDebugCheatsSharedState', 'entEntity', 'gameObject', 'PlayerPuppet',
}
for _, t in ipairs(types) do
	out('=== ' .. t)
	local ok, text = pcall(DumpType, t, true)
	out(ok and tostring(text) or ('  (no dump: ' .. tostring(text) .. ')'))
end
