-- SyncAllRatings.lua — called directly by Lightroom menu item
local LrApplication     = import "LrApplication"
local LrDialogs         = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope   = import "LrProgressScope"
local LrTasks           = import "LrTasks"
local LensAPI           = require "LensAPI"

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("SyncAllRatings", function(context)
        local catalog   = LrApplication.activeCatalog()
        local allPhotos = catalog:getAllPhotos()

        LrDialogs.message("LENS", string.format("Found %d photos. Starting sync...", #allPhotos))

        if #allPhotos == 0 then
            LrDialogs.message("LENS", "No photos in catalog.")
            return
        end

        local progress = LrProgressScope({
            title           = "Syncing all ratings to LENS...",
            functionContext = context,
        })

        local batch = {}
        for i, photo in ipairs(allPhotos) do
            progress:setPortionComplete(i, #allPhotos)
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
            LrDialogs.message("LENS — Sync Complete",
                string.format(
                    "Updated: %d photos\nPromoted to portfolio: %d\nRejected: %d",
                    result.updated              or 0,
                    result.promoted_to_portfolio or 0,
                    result.rejected             or 0
                ))
        else
            LrDialogs.message("LENS Sync Failed",
                "Could not reach LENS API on port 8600.\nMake sure LENS is running.")
        end
    end)
end)
