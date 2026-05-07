-- Hello.lua — zero-dependency test to confirm plugin menu wiring works
local LrDialogs = import "LrDialogs"
local LrTasks   = import "LrTasks"

LrTasks.startAsyncTask(function()
    LrDialogs.message("LENS Test", "Plugin menu item is working!")
end)
