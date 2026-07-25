--[[
    LensMetadata.lua — custom metadata fields that LENS writes into Lightroom.

    Registered via LrMetadataProvider in Info.lua. These fields show up in the
    Library Metadata panel, and because they are searchable they can drive
    Smart Collections — which is the whole point. The library sorts itself by
    LENS's judgement using Lightroom's own furniture, instead of us trying to
    render a report inside a panel that was never built for it.

    Note: Lightroom custom metadata is text. lensScore is stored as a string
    like "7.29" for display; use lensTier for exact-match Smart Collections.
--]]

return {

    metadataFieldsForPhotos = {

        {
            id         = "lensScore",
            title      = "LENS Score",
            dataType   = "string",
            searchable = true,
            browsable  = true,
        },

        {
            id         = "lensTier",
            title      = "LENS Tier",
            dataType   = "string",
            searchable = true,
            browsable  = true,
        },

        {
            id         = "lensStatus",
            title      = "LENS Status",
            dataType   = "string",
            searchable = true,
            browsable  = true,
        },

        {
            id         = "lensWeakness",
            title      = "LENS Weakness",
            dataType   = "string",
            searchable = true,
            browsable  = true,
        },


        {
            id         = "lensNote",
            title      = "LENS Note",
            dataType   = "string",
            searchable = true,
            browsable  = false,
        },

        {
            id         = "lensSyncedAt",
            title      = "LENS Synced",
            dataType   = "string",
            searchable = false,
            browsable  = false,
        },

    },

    schemaVersion = 2,

    -- Supplying this is what tells Lightroom the version bump is intentional
    -- and existing values should be carried forward. A no-op body is enough:
    -- every field added so far is additive, so nothing needs converting.
    -- Cheap insurance for 135,444 photos already carrying LENS metadata.
    updateFromEarlierSchemaVersion = function(catalog, previousSchemaVersion, progressScope)
        -- Additive changes only; nothing to migrate.
    end,
}
