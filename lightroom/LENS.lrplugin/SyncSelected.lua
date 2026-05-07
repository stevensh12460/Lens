-- SyncSelected.lua — syncs currently selected photos to LENS
local LrApplication     = import "LrApplication"
local LrDialogs         = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope   = import "LrProgressScope"
local LrTasks           = import "LrTasks"
local LensAPI           = require "LensAPI"

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("SyncSelected", function(context)
        local catalog  = LrApplication.activeCatalog()
        local selected = catalog:getTargetPhotos()

        if #selected == 0 then
            LrDialogs.message("LENS", "No photos selected in Library.")
            return
        end

        local progress = LrProgressScope({
            title           = string.format("Syncing %d photos to LENS...", #selected),
            functionContext = context,
        })

        local batch = {}
        for i, photo in ipairs(selected) do
            progress:setPortionComplete(i, #selected)
            if progress:isCanceled() then break end

            local path  = photo:getRawMetadata("path")
            local pick  = photo:getRawMetadata("pickStatus") or 0
            local stars = photo:getRawMetadata("rating") or 0
            local label = photo:getRawMetadata("colorNameForLabel") or ""

            local pick_flag = "unflagged"
            if pick == 1  then pick_flag = "pick"
            elseif pick == -1 then pick_flag = "reject" end

            table.insert(batch, {
                file_path      = path,
                lr_rating      = stars,
                lr_pick        = pick_flag,
                lr_color_label = label,
                lr_keywords    = {},
            })
        end

        progress:done()

        local result = LensAPI.post("/lightroom/sync-ratings", { ratings = batch })

        if result then
            LrDialogs.message("LENS — Sync Selected",
                string.format("Updated: %d photos", result.updated or #batch))
        else
            LrDialogs.message("LENS Sync Failed",
                "Could not reach LENS API on port 8600.")
        end
    end)
end)
