--[[
    LensCalendarPublishService.lua — turn a Lightroom month collection into a
    LENS Instagram posting schedule.

    Make a collection SET, add one collection per month named "January 2026",
    drag in your photos and arrange them in User Order. Position N in the month
    becomes the post for day N (one post per day, 9 AM ET). Hit Publish and LENS
    creates the planned posts; you then generate captions, review, and approve in
    LENS, and approved days auto-post.

    Why a publish service (and why it renders): a publish service is the only
    Lightroom surface that exposes a collection's manual drag order reliably
    (getPublishedPhotos, in User Order). Publishing renders a JPEG, but we DISCARD
    it — Instagram fetches the image server-side from the master at post time, so
    the sync only needs identity (master path) + order, never an uploaded file.
    The render is kept tiny (see updateExportSettings) so it stays fast.

    HARD-WON LIGHTROOM CONSTRAINTS (shared with LensPublishService.lua, keep them):
      1. A withWriteAccessDo callback must NOT yield. (We do no write blocks here.)
      2. Never wrap a yielding SDK call in plain pcall — use LrTasks.pcall.
      3. Lua 5.1 only: no // floor division, no goto, no bitwise ops, no utf8.
         Run lightroom/check_plugin.sh before loading.
      4. A NEW plugin file needs a full Lightroom RESTART, not a Reload.
--]]

local LrDialogs = import "LrDialogs"
local LrTasks   = import "LrTasks"
local LensAPI   = require "LensAPI"

-- A month collection is named like "January 2026": one or more letters, space,
-- four digits. The LENS server does the authoritative parse; this is a friendly
-- client-side gate so a mis-named collection fails clearly instead of at the API.
local MONTH_PATTERN = "^%a+%s+%d%d%d%d$"

local publishServiceProvider = {}

-- "only": keep this out of the plain Export dialog, where there is no published
-- collection and therefore no month to read.
publishServiceProvider.supportsIncrementalPublish = "only"

publishServiceProvider.small_icon         = nil
publishServiceProvider.canExportVideo     = false
publishServiceProvider.allowFileFormats   = { "JPEG" }
publishServiceProvider.allowColorSpaces   = { "sRGB" }
publishServiceProvider.exportPresetFields = {}
publishServiceProvider.hideSections = {
    "exportLocation", "fileNaming", "video", "watermarking",
    "outputSharpening", "metadata", "postProcessing",
}

-- The rendered JPEG is thrown away, so make it small and fast.
function publishServiceProvider.updateExportSettings(exportSettings)
    exportSettings.LR_format            = "JPEG"
    exportSettings.LR_export_colorSpace = "sRGB"
    exportSettings.LR_jpeg_quality      = 0.3
    exportSettings.LR_size_doConstrain  = true
    exportSettings.LR_size_resizeType   = "longEdge"
    exportSettings.LR_size_maxWidth     = 640
    exportSettings.LR_size_maxHeight    = 640
end

function publishServiceProvider.getCollectionBehaviorInfo()
    return {
        defaultCollectionName         = "January 2026",
        defaultCollectionCanBeDeleted = true,
        canAddCollection              = true,
        -- 1 = allow a Set (your "Instagram" set) containing month collections.
        maxCollectionSetDepth         = 1,
    }
end

function publishServiceProvider.shouldReverseSequenceForPublishedCollection()
    return false
end

-- ---------------------------------------------------------------------------
-- The engine. Render (discarded) to mark photos published, then read the
-- collection's manual order and hand the ordered master paths to LENS.
-- ---------------------------------------------------------------------------
function publishServiceProvider.processRenderedPhotos(functionContext, exportContext)

    local exportSession = exportContext.exportSession
    local pubCollection = exportContext.publishedCollection
    local pubInfo       = exportContext.publishedCollectionInfo
    local month         = (pubInfo and pubInfo.name)
                          or (pubCollection and pubCollection:getName())
                          or ""

    if not month:match(MONTH_PATTERN) then
        LrDialogs.message("LENS Calendar — cannot sync",
            "This collection is named \"" .. tostring(month) .. "\".\n\n" ..
            "Name each month collection like \"January 2026\" " ..
            "(full month name, a space, then the four-digit year).",
            "critical")
        return
    end

    local total    = exportSession:countRenditions()
    local progress = exportContext:configureProgress {
        title = string.format("Syncing %d photo(s) for %s", total, month),
    }

    -- 1. Render (required by the publish pipeline) and mark each photo published
    --    so it appears in getPublishedPhotos(). The rendered file is not used.
    local failed = 0
    for i, rendition in exportSession:renditions { stopIfCanceled = true } do
        progress:setPortionComplete(i - 1, total)
        local ok, msg = rendition:waitForRender()
        if not ok then
            rendition:uploadFailed(tostring(msg))
            failed = failed + 1
        else
            -- remoteId = the photo's Lightroom uuid (globally unique). We read the
            -- master path from the photo itself later, so the id only needs to be
            -- stable and unique, which the uuid is.
            rendition:recordPublishedPhotoId(rendition.photo:getRawMetadata("uuid"))
        end
    end

    -- 2. Read the collection's manual order and collect master paths. Reading
    --    getPublishedPhotos() (not the render order) is what gives User Order,
    --    and covers photos published in earlier sessions too.
    progress:setCaption("Reading order...")
    local paths = {}
    if pubCollection then
        for _, entry in ipairs(pubCollection:getPublishedPhotos()) do
            local photo = entry:getPhoto()
            local path  = photo and photo:getRawMetadata("path")
            if path then table.insert(paths, path) end
        end
    end

    if #paths == 0 then
        progress:done()
        LrDialogs.message("LENS Calendar",
            "Nothing to sync for " .. month .. " yet.", "info")
        return
    end

    -- 3. One request. LENS maps position N -> day N of the month, rebuilds the
    --    month's 'planned' posts, and protects any day already approved/posted.
    progress:setCaption("Sending " .. #paths .. " photo(s) to LENS...")
    local res, err = LensAPI.post("/social/calendar/sync-month",
        { month = month, file_paths = paths })
    progress:done()

    if not res then
        LrDialogs.message("LENS Calendar — sync failed", tostring(err), "critical")
        return
    end

    local created = res.created
    if created == nil then created = "?" end
    local msg = string.format("%s: %s day(s) planned from %d photo(s).",
        month, tostring(created), #paths)
    if failed > 0 then
        msg = msg .. "\n" .. failed .. " photo(s) failed to render."
    end
    msg = msg .. "\n\nNext in LENS: generate captions, review them, then approve. " ..
        "Approved days auto-post at 9 AM ET."
    LrDialogs.message("LENS Calendar — Sync", msg, "info")
end

-- ---------------------------------------------------------------------------
-- Removing a photo from a month collection: accept it locally. The remaining
-- photos re-number to new days on the next Publish (or "Push Calendar Order to
-- LENS"), which re-syncs the whole month from current membership.
-- ---------------------------------------------------------------------------
function publishServiceProvider.deletePhotosFromPublishedCollection(
        publishSettings, arrayOfPhotoIds, deletedCallback, localCollectionId)
    for _, photoId in ipairs(arrayOfPhotoIds) do
        deletedCallback(photoId)
    end
    LrDialogs.message("LENS Calendar",
        "Removed from the month.\n\nPublish the month again (or run " ..
        "\"Push Calendar Order to LENS\") so the remaining photos re-number to " ..
        "the correct days. Days you already approved are never disturbed.", "info")
end

return publishServiceProvider
