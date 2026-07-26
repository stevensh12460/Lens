--[[
LensCalendarYear.lua — create the twelve month collections for a year, in one go.

Twelve published collections, named exactly the way the calendar sync requires
("January 2026" ... "December 2026"), inside a set named for the year. Doing it by
hand is twelve right-clicks and twelve chances to typo a name that the sync then
silently refuses.

Idempotent: a month that already exists is left alone, so running this twice, or
running it after making a couple by hand, adds only what is missing. Nothing is
ever renamed or deleted, and no photo is touched.

Two SDK constraints shape this:

  1. A withWriteAccessDo callback must NOT yield. Creating collections is a write,
     so the loop that creates them does no dialogs, no progress updates and no HTTP
     inside the block — everything is gathered first and reported after.
  2. maxCollectionSetDepth is 1 on the calendar publish service, so a year SET
     holding month collections is exactly one level and is allowed. Nesting the year
     inside another set would exceed it.
]]

local LrApplication     = import "LrApplication"
local LrDialogs         = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrTasks           = import "LrTasks"

local MONTHS = {
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
}

-- Which year to build. Read from the clock so this needs no dialog; change here if
-- you want next year instead.
local YEAR = tonumber(os.date("%Y"))

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("LensCalendarYear", function(context)

        local catalog  = LrApplication.activeCatalog()
        local services = catalog:getPublishServices(_PLUGIN.id)

        if not services or #services == 0 then
            LrDialogs.message("LENS Calendar",
                "No LENS publish service found.\n\nAdd the \"LENS Calendar\" publish " ..
                "service in the Library module first, then run this again.", "info")
            return
        end

        -- The plugin can register more than one service; take the calendar one.
        local service
        for _, s in ipairs(services) do
            local name = s:getName() or ""
            if name:find("Calendar") then service = s break end
        end
        service = service or services[1]

        -- What already exists, so we only add what is missing. Names are compared
        -- exactly, because the sync matches them exactly.
        local existing = {}
        local function note(node)
            for _, c in ipairs(node:getChildCollections()) do
                existing[c:getName()] = true
            end
            local ok, sets = LrTasks.pcall(function() return node:getChildCollectionSets() end)
            if ok and sets then
                for _, s in ipairs(sets) do note(s) end
            end
        end
        note(service)

        local created, skipped, failed = {}, {}, {}

        -- One write block, no yielding inside it.
        catalog:withWriteAccessDo("LENS Calendar " .. YEAR, function()
            -- The year set. getChildCollectionSets is guarded the same way the
            -- order-push does, since not every node type exposes it.
            local yearSet
            local ok, sets = LrTasks.pcall(function() return service:getChildCollectionSets() end)
            if ok and sets then
                for _, s in ipairs(sets) do
                    if s:getName() == tostring(YEAR) then yearSet = s break end
                end
            end
            if not yearSet then
                local okSet, res = LrTasks.pcall(function()
                    return service:createPublishedCollectionSet(tostring(YEAR), nil, true)
                end)
                if okSet then yearSet = res end
            end

            for _, m in ipairs(MONTHS) do
                local name = m .. " " .. YEAR
                if existing[name] then
                    table.insert(skipped, name)
                else
                    local okCol, err = LrTasks.pcall(function()
                        -- (name, parent, canBeDeleted). Parent nil puts it at the
                        -- service root, which still syncs fine.
                        service:createPublishedCollection(name, yearSet, true)
                    end)
                    if okCol then
                        table.insert(created, name)
                    else
                        table.insert(failed, name .. ": " .. tostring(err):sub(1, 60))
                    end
                end
            end
        end)

        local msg = string.format("Year: %d\n\nCreated: %d\nAlready there: %d",
                                  YEAR, #created, #skipped)
        if #failed > 0 then
            msg = msg .. "\n\nFailed:\n" .. table.concat(failed, "\n")
        end
        msg = msg .. "\n\nDrag photos into a month, set the grid to User Order, " ..
                     "then Publish. Position N becomes day N."
        LrDialogs.message("LENS Calendar — " .. YEAR, msg, #failed > 0 and "warning" or "info")
    end)
end)
