return {
    LrSdkVersion        = 6.0,
    LrSdkMinimumVersion = 6.0,
    LrToolkitIdentifier = "com.lens.lrplugin",
    LrPluginName        = "LENS",
    LrPluginInfoUrl     = "http://localhost:8600",

    -- Custom metadata fields (LENS Score / Tier / Status / Note). These appear
    -- in the Library Metadata panel and are searchable, so Smart Collections
    -- can filter on them.
    LrMetadataProvider = "LensMetadata.lua",

    -- "LENS Calendar" publish service: month collections -> Instagram schedule.
    -- (The website publish service, LensPublishService.lua, is intentionally NOT
    -- registered here — activating it would push to the live public site.)
    LrExportServiceProvider = {
        title = "LENS Calendar",
        file  = "LensCalendarPublishService.lua",
    },

    LrLibraryMenuItems = {
        {
            title = "LENS Test",
            file  = "Hello.lua",
        },
        {
            title = "Sync All Ratings to LENS",
            file  = "SyncAllRatings.lua",
        },
        {
            title = "Sync Selected to LENS",
            file  = "SyncSelected.lua",
        },
        {
            title = "Pull LENS Results...",
            file  = "PullResults.lua",
        },
        {
            title = "Push Calendar Order to LENS",
            file  = "LensCalendarOrder.lua",
        },
        {
            title = "Create This Year's Month Collections",
            file  = "LensCalendarYear.lua",
        },
        {
            title = "Create Genre Smart Collections",
            file  = "LensGenreCollections.lua",
        },
    },

    VERSION = { major=1, minor=13, revision=0 },
}
