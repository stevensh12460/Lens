return {
    LrSdkVersion        = 6.0,
    LrSdkMinimumVersion = 6.0,
    LrToolkitIdentifier = "com.lens.lrplugin",
    LrPluginName        = "LENS",
    LrPluginInfoUrl     = "http://localhost:8600",

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
    },

    VERSION = { major=1, minor=2, revision=0 },
}
