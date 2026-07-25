--[[
    LensCalendarOrder.lua — re-sync every LENS Calendar month to LENS without
    republishing.

    Why this exists: Lightroom only lights the Publish button when photos are
    added/changed. Drag photos into a new order (or remove one) with nothing new
    to render and Publish stays greyed out, so a reorder-only change would never
    reach LENS. This menu item reads each month collection's current order and
    pushes it, so the posting days always match what you see in Lightroom.

    Constraints (see LensCalendarPublishService.lua header):
      * Lua 5.1 only — run lightroom/check_plugin.sh before loading.
      * A NEW plugin file needs a full Lightroom RESTART, not a Reload.
--]]

local LrApplication     = import "LrApplication"
local LrDialogs         = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrTasks           = import "LrTasks"
local LensAPI           = require "LensAPI"

-- "January 2026": letters, space, four digits. The server does the real parse.
local MONTH_PATTERN = "^%a+%s+%d%d%d%d$"

-- Collect every published collection under a node (a publish service or a
-- collection set), recursing through nested sets so month collections inside an
-- "Instagram" set are found. getChildCollectionSets is guarded because not every
-- node type exposes it.
local function gatherCollections(node, out)
    for _, c in ipairs(node:getChildCollections()) do
        table.insert(out, c)
    end
    local ok, sets = LrTasks.pcall(function() return node:getChildCollectionSets() end)
    if ok and sets then
        for _, s in ipairs(sets) do
            gatherCollections(s, out)
        end
    end
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("LensCalendarOrder", function(context)

        local catalog  = LrApplication.activeCatalog()
        local services = catalog:getPublishServices(_PLUGIN.id)

        if not services or #services == 0 then
            LrDialogs.message("LENS Calendar",
                "No LENS publish service found.\n\nAdd the \"LENS Calendar\" " ..
                "publish service in the Library module, then a Set with month " ..
                "collections named like \"January 2026\".", "info")
            return
        end

        local collections = {}
        for _, service in ipairs(services) do
            gatherCollections(service, collections)
        end

        local report, synced = {}, 0
        for _, collection in ipairs(collections) do
            local month = collection:getName()
            if month:match(MONTH_PATTERN) then

                local paths = {}
                for _, entry in ipairs(collection:getPublishedPhotos()) do
                    local photo = entry:getPhoto()
                    local path  = photo and photo:getRawMetadata("path")
                    if path then table.insert(paths, path) end
                end

                if #paths == 0 then
                    table.insert(report, month .. ": nothing published yet")
                else
                    local ok, err = LrTasks.pcall(function()
                        local res, e = LensAPI.post("/social/calendar/sync-month",
                            { month = month, file_paths = paths })
                        if not res then error(e or "LENS did not accept the sync") end
                        local created = res.created
                        if created == nil then created = "?" end
                        table.insert(report, string.format("%s: %s day(s) from %d photo(s)",
                            month, tostring(created), #paths))
                        synced = synced + 1
                    end)
                    if not ok then
                        table.insert(report, month .. ": FAILED — " .. tostring(err))
                    end
                end
            end
        end

        if #report == 0 then
            LrDialogs.message("LENS Calendar",
                "No month collections found.\n\nName them like \"January 2026\" " ..
                "and make sure they hold photos.", "info")
            return
        end

        LrDialogs.message("LENS Calendar — Push Order", table.concat(report, "\n"), "info")
    end)
end)
