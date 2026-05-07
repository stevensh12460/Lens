--[[
    LensPlugin.lua — LENS Lightroom Classic Plugin
    Menu items are wired via Info.lua LrLibraryMenuItems.
    Each id in Info.lua must match a key in the returned table.
--]]

local LrApplication  = import "LrApplication"
local LrDialogs      = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope   = import "LrProgressScope"
local LrTasks        = import "LrTasks"
local LensAPI        = require "LensAPI"

-- ---------------------------------------------------------------------------
-- Helper: build a batch payload from a list of photo objects
-- ---------------------------------------------------------------------------
local function buildBatch(photos)
    local batch = {}
    for _, photo in ipairs(photos) do
        local path  = photo:getRawMetadata("path")
        local pick  = photo:getRawMetadata("pickStatus")
        local stars = photo:getRawMetadata("rating") or 0
        local label = photo:getRawMetadata("colorNameForLabel") or ""

        local pick_flag = "unflagged"
        if pick == 1  then pick_flag = "pick"
        elseif pick == -1 then pick_flag = "reject" end

        table.insert(batch, {
            file_path   = path,
            lr_rating   = stars,
            lr_pick     = pick_flag,
            lr_color_label = label,
            lr_keywords = {},
        })
    end
    return batch
end

-- ---------------------------------------------------------------------------
-- id = "syncAllRatings"  →  Library ▸ Plug-in Extras ▸ Sync All Ratings to LENS
-- ---------------------------------------------------------------------------
local function syncAllRatings()
    LrTasks.startAsyncTask(function()
        LrFunctionContext.callWithContext("syncAllRatings", function(context)
            local catalog   = LrApplication.activeCatalog()
            local allPhotos = catalog:getAllPhotos()

            if #allPhotos == 0 then
                LrDialogs.message("LENS", "No photos in catalog.")
                return
            end

            local progress = LrProgressScope({
                title           = "Syncing all ratings to LENS…",
                functionContext = context,
            })

            local batch = {}
            for i, photo in ipairs(allPhotos) do
                progress:setPortionComplete(i, #allPhotos)
                if progress:isCanceled() then break end
                local path  = photo:getRawMetadata("path")
                local pick  = photo:getRawMetadata("pickStatus")
                local stars = photo:getRawMetadata("rating") or 0
                local label = photo:getRawMetadata("colorNameForLabel") or ""
                local pick_flag = "unflagged"
                if pick == 1 then pick_flag = "pick"
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

            -- Debug: show how many photos we collected before sending
            LrDialogs.message("LENS Debug", string.format("Collected %d photos. Sending to API now...", #batch))

            local result = LensAPI.post("/lightroom/sync-ratings", { ratings = batch })

            if result then
                LrDialogs.message("LENS — Sync Complete",
                    string.format(
                        "Updated:            %d photos\nPromoted to portfolio: %d\nRejected:           %d",
                        result.updated             or 0,
                        result.promoted_to_portfolio or 0,
                        result.rejected            or 0
                    ))
            else
                LrDialogs.message("LENS Sync Failed",
                    "Could not reach LENS API on port 8600.\nMake sure LENS is running.")
            end
        end)
    end)
end

-- ---------------------------------------------------------------------------
-- id = "syncSelected"  →  Library ▸ Plug-in Extras ▸ Sync Selected to LENS
-- ---------------------------------------------------------------------------
local function syncSelected()
    LrTasks.startAsyncTask(function()
        LrFunctionContext.callWithContext("syncSelected", function(context)
            local catalog  = LrApplication.activeCatalog()
            local selected = catalog:getTargetPhotos()

            if #selected == 0 then
                LrDialogs.message("LENS", "No photos selected in Library.")
                return
            end

            local progress = LrProgressScope({
                title           = "Syncing selected photos to LENS…",
                functionContext = context,
            })

            local batch = buildBatch(selected)
            progress:done()

            local result = LensAPI.post("/lightroom/sync-ratings", { ratings = batch })

            if result then
                LrDialogs.message("LENS — Sync Selected",
                    string.format("Updated %d photos.", result.updated or #batch))
            else
                LrDialogs.message("LENS Sync Failed",
                    "Could not reach LENS API on port 8600.")
            end
        end)
    end)
end

-- ---------------------------------------------------------------------------
-- id = "syncPicks"  →  Library ▸ Plug-in Extras ▸ Sync Picks to LENS
-- ---------------------------------------------------------------------------
local function syncPicks()
    LrTasks.startAsyncTask(function()
        LrFunctionContext.callWithContext("syncPicks", function(context)
            local catalog   = LrApplication.activeCatalog()
            local allPhotos = catalog:getAllPhotos()
            local picks     = {}

            for _, photo in ipairs(allPhotos) do
                if photo:getRawMetadata("pickStatus") == 1 then
                    table.insert(picks, photo)
                end
            end

            if #picks == 0 then
                LrDialogs.message("LENS", "No flagged picks found in catalog.")
                return
            end

            local progress = LrProgressScope({
                title           = string.format("Syncing %d picks to LENS…", #picks),
                functionContext = context,
            })

            local batch = buildBatch(picks)
            progress:done()

            local result = LensAPI.post("/lightroom/sync-ratings", { ratings = batch })

            if result then
                LrDialogs.message("LENS — Sync Picks",
                    string.format("Synced %d picked photos.\n%d promoted to portfolio.",
                        result.updated or #picks,
                        result.promoted_to_portfolio or 0))
            else
                LrDialogs.message("LENS Sync Failed",
                    "Could not reach LENS API on port 8600.")
            end
        end)
    end)
end

-- ---------------------------------------------------------------------------
-- Return table — keys must match the id values in Info.lua exactly
-- ---------------------------------------------------------------------------
return {
    syncAllRatings = syncAllRatings,
    syncSelected   = syncSelected,
    syncPicks      = syncPicks,
}
