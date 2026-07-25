-- LensAPI.lua — thin HTTP wrapper to talk to LENS FastAPI on port 8600
local LrHttp = import "LrHttp"

local LensAPI = {}
local BASE_URL = "http://localhost:8600"

-- ---------------------------------------------------------------------------
-- Minimal JSON encoder — handles strings, numbers, booleans, nil,
-- flat tables (arrays) and nested tables (objects).
-- LrJSON is not available in all SDK versions so we roll our own.
-- ---------------------------------------------------------------------------
local function jsonEncode(val)
    local t = type(val)
    if val == nil then
        return "null"
    elseif t == "boolean" then
        return val and "true" or "false"
    elseif t == "number" then
        return tostring(val)
    elseif t == "string" then
        -- escape special characters
        val = val:gsub('\\', '\\\\')
        val = val:gsub('"',  '\\"')
        val = val:gsub('\n', '\\n')
        val = val:gsub('\r', '\\r')
        val = val:gsub('\t', '\\t')
        return '"' .. val .. '"'
    elseif t == "table" then
        -- check if array (consecutive integer keys from 1)
        local isArray = true
        local maxN = 0
        for k, _ in pairs(val) do
            if type(k) ~= "number" or k ~= math.floor(k) or k < 1 then
                isArray = false
                break
            end
            if k > maxN then maxN = k end
        end
        if isArray and maxN == #val then
            local parts = {}
            for _, v in ipairs(val) do
                table.insert(parts, jsonEncode(v))
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local parts = {}
            for k, v in pairs(val) do
                table.insert(parts, jsonEncode(tostring(k)) .. ":" .. jsonEncode(v))
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return "null"
end

-- Minimal JSON decoder — handles keys with underscores and hyphens
-- Pattern uses [%w_]+ to match keys like "promoted_to_portfolio"
local function jsonDecode(str)
    if not str or str == "" then return nil end
    local result = {}
    -- numbers (including negatives and floats)
    for key, val in str:gmatch('"([%w_]+)"%s*:%s*(-?%d+%.?%d*)') do
        result[key] = tonumber(val)
    end
    -- strings
    for key, val in str:gmatch('"([%w_]+)"%s*:%s*"([^"]*)"') do
        result[key] = val
    end
    -- booleans
    for key in str:gmatch('"([%w_]+)"%s*:%s*true') do
        result[key] = true
    end
    for key in str:gmatch('"([%w_]+)"%s*:%s*false') do
        result[key] = false
    end
    -- always return something so caller knows the call succeeded
    result._ok = true
    return result
end

-- ---------------------------------------------------------------------------
-- Core HTTP helpers
-- ---------------------------------------------------------------------------
function LensAPI.post(endpoint, body)
    local url       = BASE_URL .. endpoint
    local json_body = jsonEncode(body)
    local result, headers = LrHttp.post(url, json_body, {
        { field = "Content-Type", value = "application/json" },
        { field = "Accept",       value = "application/json" },
    })
    if result then
        -- LrHttp returns the body for 4xx/5xx exactly as for 200, and
        -- jsonDecode sets _ok=true on any input at all — so without this an
        -- error page reads as success. Publishing must never mistake a failure
        -- for a completed publish.
        local status = headers and tonumber(headers.status) or nil
        if status ~= nil and status ~= 200 then
            return nil, string.format("HTTP %d from %s: %s",
                status, endpoint, tostring(result):sub(1, 200))
        end
        local decoded = jsonDecode(result)
        return decoded
    else
        -- Show debug dialog so we can see what went wrong
        local LrDialogs = import "LrDialogs"
        LrDialogs.message("LENS Debug", "POST to " .. url .. " returned no response. Headers: " .. tostring(headers))
        return nil
    end
end

function LensAPI.get(endpoint)
    local url       = BASE_URL .. endpoint
    local result, _ = LrHttp.get(url, {
        { field = "Accept", value = "application/json" },
    })
    if result then
        return jsonDecode(result)
    end
    return nil
end

-- ---------------------------------------------------------------------------
-- Status-aware POST.
--
-- LrHttp.post returns the response BODY for 4xx and 5xx just as it does for
-- 200, and jsonDecode above sets `_ok = true` on literally any input — so a
-- FastAPI 422 validation body or a 500 HTML error page both read as success.
-- For the read-only sync paths that was cosmetic. For publishing it is not:
-- Lightroom would record a slug LENS never allocated and permanently believe a
-- photo is live on a site that has never seen it.
--
-- Returns (body, status). status is a number, or nil if the request never
-- completed at all (LENS down). Callers must check it.
-- ---------------------------------------------------------------------------
function LensAPI.postRaw(endpoint, body, accept)
    local url = BASE_URL .. endpoint
    local result, hdrs = LrHttp.post(url, jsonEncode(body), {
        { field = "Content-Type", value = "application/json" },
        { field = "Accept",       value = accept or "application/json" },
    })
    if not result then return nil, nil end
    local status = hdrs and tonumber(hdrs.status) or nil
    return result, status
end

-- LensAPI.postTSV is defined further down, immediately after parseTSV.
-- It cannot live here: parseTSV is a `local` declared later in the file, so a
-- closure created at this point would capture the global (nil) instead.

-- ---------------------------------------------------------------------------
-- Build helpers
-- ---------------------------------------------------------------------------
local function pickString(pick)
    if pick == 1 then return "pick"
    elseif pick == -1 then return "reject"
    else return "unflagged" end
end

local function extractKeywords(photo)
    local kw_list = {}
    local keywords = photo:getRawMetadata("keywords") or {}
    for _, kwObj in ipairs(keywords) do
        local name = kwObj:getName()
        if name then table.insert(kw_list, name) end
    end
    return kw_list
end

-- ---------------------------------------------------------------------------
-- Sync functions
-- ---------------------------------------------------------------------------
function LensAPI.syncRatings(photos)
    local ratings = {}
    for _, photo in ipairs(photos) do
        local path     = photo:getRawMetadata("path")
        local rating   = photo:getRawMetadata("rating") or 0
        local pick     = photo:getRawMetadata("pickStatus") or 0
        local label    = photo:getRawMetadata("colorNameForLabel") or ""
        local keywords = extractKeywords(photo)
        table.insert(ratings, {
            file_path      = path,
            lr_rating      = rating,
            lr_pick        = pickString(pick),
            lr_color_label = label,
            lr_keywords    = keywords,
        })
    end
    return LensAPI.post("/lightroom/sync-ratings", { ratings = ratings })
end

function LensAPI.syncSingle(photo)
    local path   = photo:getRawMetadata("path")
    local rating = photo:getRawMetadata("rating") or 0
    local pick   = photo:getRawMetadata("pickStatus") or 0
    local label  = photo:getRawMetadata("colorNameForLabel") or ""
    return LensAPI.post("/lightroom/sync-single", {
        file_path      = path,
        lr_rating      = rating,
        lr_pick        = pickString(pick),
        lr_color_label = label,
    })
end

function LensAPI.getUnsynced()
    return LensAPI.get("/lightroom/unsynced")
end

-- ---------------------------------------------------------------------------
-- Results: LENS -> Lightroom
--
-- These use the API's tab-separated representation rather than JSON. The
-- jsonDecode above is a flat key/value scraper: it cannot represent an array
-- of objects, so an array response would silently collapse into one row and we
-- would write the same values onto every photo. Parsing TSV is a few lines we
-- can fully reason about. (The API still serves JSON for other clients.)
-- ---------------------------------------------------------------------------
local function splitTabs(line)
    local cols, start = {}, 1
    while true do
        local tabPos = line:find("\t", start, true)
        if tabPos then
            table.insert(cols, line:sub(start, tabPos - 1))
            start = tabPos + 1
        else
            table.insert(cols, line:sub(start))
            break
        end
    end
    return cols
end

local function parseTSV(text)
    local rows = {}
    if not text or text == "" then return rows end
    local isHeader = true
    for line in text:gmatch("[^\r\n]+") do
        if isHeader then
            isHeader = false
        else
            local cols = splitTabs(line)
            if cols[1] and cols[1] ~= "" then
                table.insert(rows, {
                    file_path  = cols[1],
                    lens_score = cols[2] or "",
                    tier       = cols[3] or "",
                    status     = cols[4] or "",
                    note       = cols[5] or "",
                    weakness   = cols[6] or "",
                })
            end
        end
    end
    return rows
end

-- POST expecting a TSV body whose FIRST line is the literal sentinel "#OK".
-- Requiring the sentinel means a proxy error page, an HTML 500, or a truncated
-- response can never be mistaken for a valid empty result set.
-- Returns (rows, nil) on success, or (nil, errorMessage) on any failure.
-- Used by the publish service; the older results endpoints predate the
-- sentinel and are status-checked without it.
function LensAPI.postTSV(endpoint, body)
    local result, status = LensAPI.postRaw(endpoint, body, "text/plain")
    if result == nil then
        return nil, "LENS unreachable on port 8600 (is it running?)"
    end
    -- status may be nil if this SDK build does not surface it on the header
    -- table; in that case the #OK sentinel below is the guard that matters, so
    -- treat only an explicit non-200 as fatal here.
    if status ~= nil and status ~= 200 then
        return nil, string.format("LENS returned HTTP %s: %s",
            tostring(status), tostring(result):sub(1, 300))
    end
    local firstLine = result:match("^[^\r\n]*") or ""
    if firstLine ~= "#OK" then
        return nil, "LENS response missing #OK sentinel: " ..
            tostring(result):sub(1, 300)
    end
    -- Drop the sentinel line; parseTSV then skips the column header as usual.
    local rest = result:gsub("^[^\r\n]*\r?\n", "", 1)
    return parseTSV(rest), nil
end

-- Returns an array of result rows for the given photos, or nil if LENS is
-- unreachable (nil and empty-table mean different things to the caller).
function LensAPI.getResultsForPhotos(photos)
    local paths = {}
    for _, photo in ipairs(photos) do
        local p = photo:getRawMetadata("path")
        if p then table.insert(paths, p) end
    end
    if #paths == 0 then return {} end

    local url          = BASE_URL .. "/lightroom/results/by-paths?format=tsv"
    local body         = jsonEncode({ paths = paths })
    local result, hdrs = LrHttp.post(url, body, {
        { field = "Content-Type", value = "application/json" },
        { field = "Accept",       value = "text/plain" },
    })
    if not result then return nil end
    -- A 4xx/5xx still returns a body. Without this check an error page would be
    -- fed to parseTSV, yield zero rows, and be reported to the user as "these
    -- photos are not known to LENS" — a wrong answer that looks like a real one.
    local status = hdrs and tonumber(hdrs.status) or nil
    if status ~= nil and status ~= 200 then return nil end
    return parseTSV(result)
end

return LensAPI
