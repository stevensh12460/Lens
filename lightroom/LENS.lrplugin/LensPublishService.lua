--[[
    LensPublishService.lua — publishes photos from Lightroom to
    stevenhowardphotography.com.

    Drag photos into a "LENS Website" published collection named after a gallery
    section, hit Publish, and they are live in about a minute. Lightroom renders
    the JPEG with Steven's develop settings applied; LENS places the file,
    rewrites the fenced gallery block, commits and pushes; Cloudflare deploys.

    AUTHORITY RULE: Steven's stars are ground truth. This writes only the
    published-photo bookkeeping Lightroom itself owns, plus plugin custom
    metadata. It never writes rating, pickStatus or colorNameForLabel.

    HARD-WON LIGHTROOM CONSTRAINTS (each cost a debug cycle, keep them):

      1. A withWriteAccessDo callback must NOT yield. Progress updates yield, so
         they happen BETWEEN chunks, never inside a write block. Violating this
         throws a bare "assertion failed".

      2. Never wrap a yielding SDK call in plain pcall — Lightroom is Lua 5.1 and
         cannot yield across a C-call boundary. Use LrTasks.pcall. Violating this
         throws "Yielding is not allowed within a C or metamethod call".

      3. Lua 5.1 only: no // floor division, no goto, no bitwise ops, no utf8.
         A syntax error surfaces as the very misleading "No script by the name
         <file>.lua". Run lightroom/check_plugin.sh before loading.

      4. Lightroom indexes plugin script FILENAMES when the plugin loads. A NEW
         file needs a full Lightroom RESTART, not a Reload.

      5. The rendered temp file is deleted when the export session ends. It must
         be moved to staging inside the rendition loop, not after it.
--]]

local LrDialogs         = import "LrDialogs"
local LrFileUtils       = import "LrFileUtils"
local LrPathUtils       = import "LrPathUtils"
local LrTasks           = import "LrTasks"
local LensAPI           = require "LensAPI"

-- Must stay in sync with SECTIONS in services/web_publisher.py.
local SECTIONS = { landscape = true, portraits = true, weddings = true, food = true }

local function sectionList()
    local names = {}
    for name in pairs(SECTIONS) do table.insert(names, name) end
    table.sort(names)
    return table.concat(names, ", ")
end

local function stagingDir()
    local base = LrPathUtils.child(LrPathUtils.getStandardFilePath("temp"), "lens-web-staging")
    LrFileUtils.createAllDirectories(base)
    return base
end

local publishServiceProvider = {}

-- 'only' rather than true: true would ALSO list this in the plain Export
-- dialog, where exportContext.publishedCollection is nil and there is no way to
-- know which gallery section a photo belongs to.
publishServiceProvider.supportsIncrementalPublish = "only"

publishServiceProvider.small_icon         = nil
publishServiceProvider.canExportVideo     = false
publishServiceProvider.allowFileFormats   = { "JPEG" }
publishServiceProvider.allowColorSpaces   = { "sRGB" }
publishServiceProvider.exportPresetFields = {}

-- Hiding exportLocation is what routes the render into Lightroom's own temp
-- directory. Leaving it visible lets a stray edit redirect output, and the
-- default collision handling silently renames files, which would break the
-- slug-to-filename contract with no error.
publishServiceProvider.hideSections = { "exportLocation", "fileNaming", "video", "watermarking" }

function publishServiceProvider.updateExportSettings(exportSettings)
    exportSettings.LR_format                 = "JPEG"
    exportSettings.LR_export_colorSpace      = "sRGB"
    exportSettings.LR_jpeg_quality           = 0.82
    exportSettings.LR_size_doConstrain       = true
    exportSettings.LR_size_resizeType        = "longEdge"
    exportSettings.LR_size_maxWidth          = 2400
    exportSettings.LR_size_maxHeight         = 2400
    exportSettings.LR_outputSharpeningOn     = true
    exportSettings.LR_outputSharpeningMedia  = "screen"
    exportSettings.LR_outputSharpeningLevel  = 2
    -- His masters carry GPS. Stripping it here keeps home coordinates off a
    -- public CDN; LENS refuses any staged file still carrying a GPS IFD too,
    -- because export presets drift.
    exportSettings.LR_removeLocationMetadata = true
    exportSettings.LR_embeddedMetadataOption = "copyrightOnly"
end

function publishServiceProvider.getCollectionBehaviorInfo()
    return {
        defaultCollectionName         = "landscape",
        defaultCollectionCanBeDeleted = false,
        canAddCollection              = true,
        -- Flat: one collection per gallery page, no sets. The collection NAME
        -- is the section slug, so nesting would make it ambiguous.
        maxCollectionSetDepth         = 0,
    }
end

-- Without this, editing a caption never re-lights the Publish button and the
-- whole "type it in Lightroom, then publish" loop silently does nothing.
function publishServiceProvider.metadataThatTriggersRepublish()
    return {
        default                  = false,
        title                    = true,
        caption                  = true,
        ["com.lens.lrplugin.lensWebLayout"] = true,
    }
end

function publishServiceProvider.shouldReverseSequenceForPublishedCollection()
    return false
end

-- Renaming a published collection would silently retarget a different gallery
-- page, so refuse it. The name IS the section.
function publishServiceProvider.renamePublishedCollection(publishSettings, info)
    LrDialogs.message("LENS",
        "A LENS Website collection is named after the gallery page it publishes to " ..
        "(" .. sectionList() .. "). Renaming it would point it at a different page.",
        "info")
end

-- ---------------------------------------------------------------------------
-- The engine.
-- ---------------------------------------------------------------------------
function publishServiceProvider.processRenderedPhotos(functionContext, exportContext)

    local exportSession = exportContext.exportSession
    local pubCollection = exportContext.publishedCollection
    local pubInfo       = exportContext.publishedCollectionInfo
    local section       = pubInfo and pubInfo.name or ""

    if not SECTIONS[section] then
        LrDialogs.message("LENS — cannot publish",
            "This collection is named \"" .. tostring(section) .. "\", which is not a " ..
            "gallery page on the site.\n\nRename it to one of: " .. sectionList(),
            "critical")
        return
    end

    local total    = exportSession:countRenditions()
    local progress = exportContext:configureProgress {
        title = string.format("Publishing %d photo(s) to %s", total, section),
    }

    local staging  = stagingDir()
    local payload  = {}       -- what we send to LENS
    local byUuid   = {}       -- uuid -> rendition, for recording results
    local failed   = 0

    -- 1. Render, and take ownership of each temp file INSIDE the loop
    --    (constraint 5: it is deleted when the session ends).
    for i, rendition in exportSession:renditions { stopIfCanceled = true } do
        progress:setPortionComplete(i - 1, total)

        local ok, pathOrMessage = rendition:waitForRender()
        if not ok then
            rendition:uploadFailed(tostring(pathOrMessage))
            failed = failed + 1
        else
            local photo = rendition.photo
            local uuid  = photo:getRawMetadata("uuid")
            local dest  = LrPathUtils.child(staging, uuid .. ".jpg")

            if LrFileUtils.exists(dest) then LrFileUtils.delete(dest) end
            local moved, moveErr = LrTasks.pcall(function()
                LrFileUtils.move(pathOrMessage, dest)
            end)

            if not moved then
                rendition:uploadFailed("could not stage render: " .. tostring(moveErr))
                failed = failed + 1
            else
                byUuid[uuid] = rendition
                table.insert(payload, {
                    lr_photo_uuid = uuid,
                    staged_path   = dest,
                    title         = photo:getFormattedMetadata("title")   or "",
                    caption       = photo:getFormattedMetadata("caption") or "",
                    layout        = photo:getPropertyForPlugin(_PLUGIN, "lensWebLayout") or "",
                    source_path   = photo:getRawMetadata("path") or "",
                })
            end
        end
    end

    if #payload == 0 then
        if failed > 0 then
            LrDialogs.message("LENS", failed .. " photo(s) failed to render. Nothing published.", "critical")
        end
        return
    end

    -- 2. ONE request for the whole batch. LrHttp has no timeout parameter and
    --    blocks the publish task, so one hung call per publish is far better
    --    than one per photo.
    progress:setCaption("Sending " .. #payload .. " photo(s) to LENS...")
    local rows, err = LensAPI.postTSV("/web/publish", { section = section, photos = payload })

    if not rows then
        for _, rendition in pairs(byUuid) do rendition:uploadFailed(tostring(err)) end
        LrDialogs.message("LENS — publish failed", tostring(err), "critical")
        return
    end

    -- 3. Record what LENS allocated. Doing this unconditionally, including for
    --    photos already published, self-heals any drift between the two sides.
    local published = 0
    for _, row in ipairs(rows) do
        local rendition = byUuid[row.lr_photo_uuid]
        if rendition then
            rendition:recordPublishedPhotoId(row.slug)
            rendition:recordPublishedPhotoUrl(row.url)
            published = published + 1
        end
    end

    -- 4. Order, read from the collection itself rather than waiting for
    --    imposeSortOrderOnPublishedCollection — that callback only fires when
    --    the collection is set to User Order AND only after a publish, so a
    --    reorder with nothing new to publish would be unpublishable.
    progress:setCaption("Applying order...")
    local orderOk, orderErr = LrTasks.pcall(function()
        local slugs = {}
        if pubCollection then
            for _, entry in ipairs(pubCollection:getPublishedPhotos()) do
                local id = entry:getRemoteId()
                if id then table.insert(slugs, id) end
            end
        end
        if #slugs > 0 then
            LensAPI.post("/web/order", { section = section, slugs = slugs })
        end
    end)

    -- 5. One commit for the whole batch, so a publish of eight photos is one
    --    Cloudflare deploy rather than eight.
    progress:setCaption("Publishing to the live site...")
    local result = LensAPI.post("/web/commit", { section = section, dry_run = false })

    progress:done()

    local msg = string.format("%d photo(s) published to the %s page.\n", published, section)
    if failed > 0 then msg = msg .. failed .. " failed to render.\n" end
    if not orderOk then msg = msg .. "\nOrder was not applied: " .. tostring(orderErr) .. "\n" end

    if result and result.status then
        msg = msg .. "\nSite: " .. tostring(result.status)
        if result.commit then msg = msg .. " (" .. tostring(result.commit) .. ")" end
        if result.status == "pushed" then
            msg = msg .. "\nCloudflare will deploy in about a minute."
        elseif result.status == "unchanged" then
            msg = msg .. "\nNothing changed — the site already matches."
        elseif result.detail then
            msg = msg .. "\n" .. tostring(result.detail)
        end
    else
        msg = msg .. "\n\nCould not confirm the site update. Check LENS on port 8600."
    end

    msg = msg .. "\n\nYour star ratings, flags and colour labels were not touched."
    LrDialogs.message("LENS — Publish", msg, "info")
end

-- ---------------------------------------------------------------------------
-- Removal. Confirms in Lightroom, at publish time.
--
-- Not calling deletedCallback is the CORRECT representation of "asked for, not
-- done": Lightroom keeps the photos pending and re-presents them on the next
-- publish, which is exactly the deferred state we want.
-- ---------------------------------------------------------------------------
function publishServiceProvider.deletePhotosFromPublishedCollection(
        publishSettings, arrayOfPhotoIds, deletedCallback, localCollectionId)

    local names = table.concat(arrayOfPhotoIds, "\n  ")
    local answer = LrDialogs.confirm(
        "Remove from the live website?",
        "These will come off the site the next time it deploys:\n\n  " .. names ..
        "\n\nThe image files stay in the repository, so this is reversible.",
        "Remove them", "Keep them")

    if answer ~= "ok" then
        -- Deliberately no deletedCallback: they stay pending, the Publish
        -- button stays lit, and nothing on the site changes.
        return
    end

    for _, photoId in ipairs(arrayOfPhotoIds) do
        local res = LensAPI.post("/web/removals/stage",
            { slug = photoId, confirmed = true })
        if res then
            deletedCallback(photoId)
        end
    end
end

-- Secondary order path. Kept as a safety net; /web/order is idempotent so a
-- double-fire costs nothing.
function publishServiceProvider.imposeSortOrderOnPublishedCollection(
        publishSettings, info, remoteIdSequence)

    local section = info and info.name or ""
    if not SECTIONS[section] then return end

    local slugs = {}
    for _, remoteId in ipairs(remoteIdSequence) do
        if remoteId then table.insert(slugs, remoteId) end
    end
    if #slugs == 0 then return end

    LrTasks.pcall(function()
        LensAPI.post("/web/order", { section = section, slugs = slugs })
        LensAPI.post("/web/commit", { section = section, dry_run = false })
    end)
end

return publishServiceProvider
