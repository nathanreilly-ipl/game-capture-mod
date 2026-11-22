-- From the main menu: load the most recent save, as the menu's CONTINUE does.
-- adapters/cyberpunk/launch.py runs this while the heartbeat says world=0. LoadLastCheckpoint
-- works from the main menu (2026-11-21); asked during the intro before it, nothing happens.
return function(ctx)
	local handler = Game.GetSystemRequestsHandler()
	ctx.result.pregame = tostring(handler:IsPreGame())
	if not handler:IsPreGame() then
		ctx.finish('ok', 'a game is already loaded')
		return
	end
	local tried = {}
	for _, name in ipairs({ 'LoadLastCheckpoint' }) do
		local ok, err = pcall(function() handler[name](handler, false) end)
		tried[#tried + 1] = name .. (ok and ':called' or (':' .. tostring(err)))
		if ok then
			break
		end
	end
	ctx.result.tried = table.concat(tried, ' ; ')
	-- the load takes a while; the launcher watches the heartbeat for ingame=1
	ctx.after(120, function() ctx.finish('ok', '') end)
end
