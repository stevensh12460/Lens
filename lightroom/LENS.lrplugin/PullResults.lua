--[[
    PullResults.lua — pulls LENS scores, tiers and edit notes DOWN into
    Lightroom. Handles BOTH the current selection and the whole catalog; you
    pick the scope when it runs.

    AUTHORITY RULE: Steven's stars are ground truth. This writes ONLY plugin
    custom metadata and the removable "LENS" keyword branch. It never writes
    rating, pickStatus, or colorNameForLabel. Keep it that way.

    HARD-WON LIGHTROOM CONSTRAINTS (all three cost us a debug cycle):

      1. A withWriteAccessDo callback must NOT yield. Progress updates can
         yield, so they happen BETWEEN chunks, never inside a write block.
         Violating this throws a bare "assertion failed".

      2. Never wrap a yielding SDK call in plain pcall. Lightroom is Lua 5.1
         and cannot yield across a C-call boundary. Use LrTasks.pcall.
         Violating this throws "Yielding is not allowed within a C or
         metamethod call".

      3. Lua 5.1 only: no // floor division, no goto, no bitwise ops, no utf8
         library. A syntax error here surfaces as the very misleading
         "No script by the name <file>.lua".

      4. Lightroom indexes plugin script FILENAMES when the plugin loads.
         Reload re-reads known files but will not register a NEW filename —
         that needs a full Lightroom restart. This is why everything lives in
         this one file instead of a second script.
--]]

local LrApplication     = import "LrApplication"
local LrDialogs         = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrProgressScope   = import "LrProgressScope"
local LrTasks           = import "LrTasks"
local LensAPI           = require "LensAPI"

local FETCH_CHUNK = 500   -- paths per HTTP request
local WRITE_CHUNK = 100   -- photos per catalog write transaction
local SAMPLE_SIZE = 1000  -- timing-test size

-- Must stay in sync with _TIER_BANDS / _status_for in api/routes/lightroom.py.
local TIERS    = { "Exceptional", "Strong", "Solid", "Weak", "Low" }
local STATUSES = { "Posted", "Print", "Portfolio", "Ready", "Scored",
                   "Pending", "Burst", "Culled", "Missing",
                   "Corrupt", "Video", "Sidecar" }

local function fmtDuration(sec)
    if sec < 60 then return string.format("%d sec", sec) end
    if sec < 3600 then
        return string.format("%d min %d sec", math.floor(sec / 60), sec % 60)
    end
    return string.format("%.1f hours", sec / 3600)
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("PullLensResults", function(context)

        local catalog  = LrApplication.activeCatalog()
        local selected = catalog:getTargetPhotos()
        local allPhotos = catalog:getAllPhotos()
        local total    = #allPhotos

        -- ------------------------------------------------------------------
        -- Choose scope.
        -- ------------------------------------------------------------------
        local photos
        local choice = LrDialogs.confirm(
            "Pull LENS Results",
            string.format(
                "Process the %d selected photo(s), or run across the whole " ..
                "catalog (%d photos)?\n\n" ..
                "Whole-catalog starts with a %d-photo timing test so you can " ..
                "see the projected total before committing.\n\n" ..
                "You can cancel at any time; anything already written stays.",
                #selected, total, SAMPLE_SIZE),
            "Selected (" .. #selected .. ")",  -- "ok"
            "Cancel",                          -- "cancel"
            "Whole Catalog")                   -- "other"

        if choice == "ok" then
            if #selected == 0 then
                LrDialogs.message("LENS", "No photos selected in Library.")
                return
            end
            photos = selected
        elseif choice == "other" then
            local scope = LrDialogs.confirm(
                "Whole Catalog",
                string.format("Time a %d-photo sample first, or process all %d now?",
                    SAMPLE_SIZE, total),
                "Test " .. SAMPLE_SIZE,   -- "ok"
                "Cancel",                 -- "cancel"
                "Process All")            -- "other"
            if scope == "ok" then
                photos = {}
                for i = 1, math.min(SAMPLE_SIZE, total) do
                    table.insert(photos, allPhotos[i])
                end
            elseif scope == "other" then
                photos = allPhotos
            else
                return
            end
        else
            return
        end

        local limit = #photos
        if limit == 0 then
            LrDialogs.message("LENS", "Nothing to process.")
            return
        end

        local startTime = os.time()
        local progress = LrProgressScope({
            title           = string.format("LENS: processing %d photos...", limit),
            functionContext = context,
        })

        -- ------------------------------------------------------------------
        -- Keyword hierarchy, created once. Non-fatal if it fails.
        -- ------------------------------------------------------------------
        local tierKw, statusKw = {}, {}
        local tierRoot, statusRoot   -- hoisted: needed to identify stale labels
        local keywordsOk, keywordErr = LrTasks.pcall(function()
            catalog:withWriteAccessDo("LENS keywords", function()
                local lensRoot = catalog:createKeyword("LENS",   {}, false, nil,      true)
                tierRoot       = catalog:createKeyword("Tier",   {}, false, lensRoot, true)
                statusRoot     = catalog:createKeyword("Status", {}, false, lensRoot, true)
                for _, t in ipairs(TIERS)    do tierKw[t]   = catalog:createKeyword(t, {}, false, tierRoot,   true) end
                for _, s in ipairs(STATUSES) do statusKw[s] = catalog:createKeyword(s, {}, false, statusRoot, true) end
            end)
        end)

        -- ------------------------------------------------------------------
        -- Fetch a chunk, write it, advance. Progress BETWEEN chunks only.
        -- ------------------------------------------------------------------
        local written, noScore, missing, unreachable = 0, 0, 0, 0
        local stamp     = os.date("%Y-%m-%d %H:%M")
        local lastError = nil
        local index     = 1

        while index <= limit do
            if progress:isCanceled() then break end
            progress:setPortionComplete(index, limit)

            local fetchStop   = math.min(index + FETCH_CHUNK - 1, limit)
            local chunkPhotos = {}
            for j = index, fetchStop do
                table.insert(chunkPhotos, photos[j])
            end

            local okFetch, results = LrTasks.pcall(function()
                return LensAPI.getResultsForPhotos(chunkPhotos)
            end)

            if not okFetch then
                lastError = tostring(results)
                break
            end

            if results == nil then
                unreachable = unreachable + #chunkPhotos
            else
                local byPath = {}
                for _, r in ipairs(results) do byPath[r.file_path] = r end

                local w = 1
                while w <= #chunkPhotos do
                    local wStop = math.min(w + WRITE_CHUNK - 1, #chunkPhotos)

                    local okWrite, err = LrTasks.pcall(function()
                        catalog:withWriteAccessDo("Pull LENS Results", function()
                            for k = w, wStop do
                                local photo = chunkPhotos[k]
                                local path  = photo:getRawMetadata("path")
                                local r     = path and byPath[path] or nil

                                if r then
                                    photo:setPropertyForPlugin(_PLUGIN, "lensScore",    r.lens_score or "")
                                    photo:setPropertyForPlugin(_PLUGIN, "lensTier",     r.tier       or "")
                                    photo:setPropertyForPlugin(_PLUGIN, "lensStatus",   r.status     or "")
                                    photo:setPropertyForPlugin(_PLUGIN, "lensNote",     r.note       or "")
                                    photo:setPropertyForPlugin(_PLUGIN, "lensWeakness", r.weakness or "")
                                    photo:setPropertyForPlugin(_PLUGIN, "lensSyncedAt", stamp)
                                    written = written + 1
                                    if (r.lens_score or "") == "" then noScore = noScore + 1 end

                                    if keywordsOk then
                                        -- Clear stale LENS labels first. addKeyword only
                                        -- adds, so without this a re-run leaves a photo
                                        -- carrying two contradictory tiers. Only touches
                                        -- keywords parented to OUR Tier/Status roots, so
                                        -- a user keyword named "Print" is never harmed.
                                        local existing = photo:getRawMetadata("keywords")
                                        if existing then
                                            for _, kw in ipairs(existing) do
                                                local parent = kw:getParent()
                                                if parent and (parent == tierRoot or parent == statusRoot) then
                                                    photo:removeKeyword(kw)
                                                end
                                            end
                                        end

                                        local tk = r.tier   and tierKw[r.tier]
                                        local sk = r.status and statusKw[r.status]
                                        if tk then photo:addKeyword(tk) end
                                        if sk then photo:addKeyword(sk) end
                                    end
                                else
                                    missing = missing + 1
                                end
                            end
                        end)
                    end)

                    if not okWrite then
                        lastError = tostring(err)
                        break
                    end
                    w = wStop + 1
                end
            end

            if lastError then break end
            index = fetchStop + 1
        end

        progress:done()

        -- ------------------------------------------------------------------
        -- Report, with a projection for the full catalog.
        -- ------------------------------------------------------------------
        local elapsed   = math.max(os.time() - startTime, 1)
        local processed = index - 1
        if processed > limit then processed = limit end
        local rate = processed / elapsed

        local msg = string.format(
            "Processed %d photos in %s  (%.1f photos/sec)\n\n" ..
            "%d written\n%d unscored (duplicates/culled)\n%d not known to LENS\n",
            processed, fmtDuration(elapsed), rate, written, noScore, missing)

        if unreachable > 0 then
            msg = msg .. string.format("%d skipped, LENS API unreachable\n", unreachable)
        end

        if processed < total and rate > 0 then
            msg = msg .. string.format(
                "\nProjected for all %d photos: about %s.",
                total, fmtDuration(math.floor(total / rate)))
        end

        if not keywordsOk then
            msg = msg .. "\n\nKeywords skipped: " .. tostring(keywordErr)
        end

        if lastError then
            msg = msg .. "\n\nStopped early on error:\n" .. lastError
        end

        msg = msg .. "\n\nYour star ratings, pick flags and color labels were not touched."

        LrDialogs.message("LENS — Pull Results", msg)
    end)
end)
