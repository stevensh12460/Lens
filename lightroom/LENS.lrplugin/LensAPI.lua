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

return LensAPI
