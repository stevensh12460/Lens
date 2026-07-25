--[[
    LensWebOrder.lua — push the current order of a LENS Website collection to
    the live site, without publishing anything new.

    Why this exists: Lightroom only offers Publish when something has actually
    changed. Drag photos into a new order with nothing new to upload and the
    Publish button stays greyed out, so a reorder-only change would be
    unpublishable. This gives it a way out.

    Constraints (see LensPublishService.lua header for the full list):
      * Lua 5.1 only — run lightroom/check_plugin.sh before loading.
      * A NEW plugin file needs a full Lightroom RESTART, not a Reload.
--]]

local LrApplication     = import "LrApplication"
local LrDialogs         = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrTasks           = import "LrTasks"
local LensAPI           = require "LensAPI"

local SECTIONS = { landscape = true, portraits = true, weddings = true, food = true }

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("LensWebOrder", function(context)

        local catalog  = LrApplication.activeCatalog()
        local services = catalog:getPublishServices(_PLUGIN.id)

        if not services or #services == 0 then
            LrDialogs.message("LENS",
                "No LENS Website publish service found.\n\nCreate one in the " ..
                "Library module: right-click in the Publish Services panel, " ..
                "then add a collection named after a gallery page.", "info")
            return
        end

        local report, pushed = {}, 0

        for _, service in ipairs(services) do
            for _, collection in ipairs(service:getChildCollections()) do
                local section = collection:getName()
                if SECTIONS[section] then

                    local slugs = {}
                    for _, entry in ipairs(collection:getPublishedPhotos()) do
                        local id = entry:getRemoteId()
                        if id then table.insert(slugs, id) end
                    end

                    if #slugs == 0 then
                        table.insert(report, section .. ": nothing published yet")
                    else
                        local ok, err = LrTasks.pcall(function()
                            local res = LensAPI.post("/web/order",
                                { section = section, slugs = slugs })
                            if not res then error("LENS did not accept the order") end

                            local commit = LensAPI.post("/web/commit",
                                { section = section, dry_run = false })
                            local status = commit and commit.status or "unknown"
                            table.insert(report, string.format("%s: %d photo(s), %s",
                                section, #slugs, status))
                            if status == "pushed" then pushed = pushed + 1 end
                        end)
                        if not ok then
                            table.insert(report, section .. ": FAILED — " .. tostring(err))
                        end
                    end
                end
            end
        end

        if #report == 0 then
            LrDialogs.message("LENS",
                "No collections named after a gallery page were found.\n\n" ..
                "Name them: landscape, portraits, weddings, food.", "info")
            return
        end

        local msg = table.concat(report, "\n")
        if pushed > 0 then
            msg = msg .. "\n\nCloudflare will deploy in about a minute."
        end
        LrDialogs.message("LENS — Push Website Order", msg, "info")
    end)
end)
