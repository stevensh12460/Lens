--[[
LensGenreCollections.lua — build the genre smart collections, in a "Genres" set.

One smart collection per genre LENS actually assigns, filtering on the keyword that
"Pull LENS Results" writes under LENS > Genre >. These live in the NORMAL Collections panel, not under a
publish service: they are for finding work, while a month collection under LENS
Calendar is for ordering it. The calendar deliberately refuses smart collections
because its sync maps position N to day N and needs manual drag order.

Genre is written by pass3_tag.py, the vision tagging pass. Its prompt offers
wedding, portrait, boudoir, commercial, events and nature; landscape and concert
also exist in the database from earlier runs, so both are included here.

Idempotent: a collection whose name already exists is skipped, so running this
twice adds nothing. Nothing is renamed, deleted, or emptied, and no photo moves.

A withWriteAccessDo callback must NOT yield, so the create loop holds no dialogs
and everything is reported after the block closes.
]]

local LrApplication     = import "LrApplication"
local LrDialogs         = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrTasks           = import "LrTasks"

local SET_NAME = "Genres"

-- Ordered biggest-first, which is only cosmetic, but it puts the collections you
-- will actually open at the top of the set.
local GENRES = {
    "portrait", "events", "boudoir", "commercial",
    "wedding", "nature", "landscape", "concert",
}

-- Title case for display; the FILTER matches the stored lowercase value.
local function title(s)
    return (s:gsub("^%l", string.upper))
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("LensGenreCollections", function(context)

        local catalog = LrApplication.activeCatalog()

        -- What is already there, by name, so re-running adds only what is missing.
        local existing = {}
        for _, c in ipairs(catalog:getChildCollections()) do
            existing[c:getName()] = true
        end
        local existingSet
        for _, s in ipairs(catalog:getChildCollectionSets()) do
            if s:getName() == SET_NAME then existingSet = s end
            for _, c in ipairs(s:getChildCollections()) do
                existing[c:getName()] = true
            end
        end

        local created, skipped, failed = {}, {}, {}

        catalog:withWriteAccessDo("LENS genre collections", function()
            local set = existingSet
            if not set then
                local ok, res = LrTasks.pcall(function()
                    return catalog:createCollectionSet(SET_NAME, nil, true)
                end)
                if ok then set = res end
            end

            for _, g in ipairs(GENRES) do
                local name = title(g)
                if existing[name] then
                    table.insert(skipped, name)
                else
                    -- Filter on the KEYWORD, not the plugin metadata field.
                    -- "Pull LENS Results" writes a real keyword under LENS > Genre >,
                    -- and Lightroom filters keywords reliably: they show in the Keyword
                    -- List, they are searchable everywhere, and they survive export.
                    -- Custom plugin metadata needs an "sdktext:<plugin>.<field>"
                    -- criteria whose behaviour varies by SDK version, which is a poor
                    -- thing to depend on for the panel Steven browses every day.
                    local searchDesc = {
                        criteria  = "keywords",
                        operation = "words",
                        value     = name,
                    }
                    local ok, err = LrTasks.pcall(function()
                        catalog:createSmartCollection(name, searchDesc, set, true)
                    end)
                    if ok then
                        table.insert(created, name)
                    else
                        table.insert(failed, name .. ": " .. tostring(err):sub(1, 70))
                    end
                end
            end
        end)

        local msg = string.format("Set: %s\n\nCreated: %d\nAlready there: %d",
                                  SET_NAME, #created, #skipped)
        if #created > 0 then
            msg = msg .. "\n  " .. table.concat(created, ", ")
        end
        if #failed > 0 then
            msg = msg .. "\n\nFailed:\n" .. table.concat(failed, "\n")
        end
        msg = msg .. "\n\nThese filter on the LENS > Genre > keywords, so run " ..
                     "\"Pull LENS Results\" on photos first or they will look empty. " ..
                     "Genre is set on roughly 29,600 of the library; the rest have " ..
                     "not been through pass 3 yet."
        LrDialogs.message("LENS Genres", msg, #failed > 0 and "warning" or "info")
    end)
end)
