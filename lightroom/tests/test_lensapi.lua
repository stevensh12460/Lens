-- test_lensapi.lua — runs LensAPI.lua OUTSIDE Lightroom by stubbing the SDK.
--
-- Run:  cd ~/lens/lightroom/LENS.lrplugin && luajit ../tests/test_lensapi.lua
--
-- Covers the failure that made this necessary: LrHttp.post returns a body for
-- 4xx/5xx exactly as it does for 200, and jsonDecode sets _ok=true on any
-- input, so a LENS 500 used to read as a successful publish. In a publish
-- service that means Lightroom records a slug LENS never allocated and
-- permanently believes a photo is live on a site that never received it.

-- Stub the Lightroom SDK so LensAPI can be loaded outside Lightroom.
local stubResponse, stubStatus
_G.import = function(mod)
  if mod == "LrHttp" then
    return { post = function() return stubResponse, stubStatus and {status=stubStatus} or nil end,
             get  = function() return stubResponse end }
  end
  if mod == "LrDialogs" then return { message = function() end } end
  return {}
end
package.path = "./?.lua;" .. package.path
local API = require "LensAPI"

local pass, fail = 0, 0
local function check(name, cond, detail)
  if cond then pass = pass + 1; print(("  PASS  %s"):format(name))
  else fail = fail + 1; print(("  FAIL  %s  %s"):format(name, detail or "")) end
end

-- 1. happy path: 200 + #OK sentinel
stubStatus, stubResponse = 200, "#OK\nfile_path\tslug\nfoo.jpg\tlandscape-08\n"
local rows, err = API.postTSV("/web/publish", {})
check("200 + #OK parses rows", rows ~= nil and #rows == 1 and err == nil,
      "rows="..tostring(rows and #rows).." err="..tostring(err))

-- 2. THE BUG: a 500 with an HTML error page must NOT read as success
stubStatus, stubResponse = 500, "<html><body>Internal Server Error</body></html>"
rows, err = API.postTSV("/web/publish", {})
check("HTTP 500 is rejected", rows == nil and err ~= nil, "err="..tostring(err))

-- 3. FastAPI 422 validation body must not read as success
stubStatus, stubResponse = 422, '{"detail":[{"loc":["body"],"msg":"field required"}]}'
rows, err = API.postTSV("/web/publish", {})
check("HTTP 422 is rejected", rows == nil and err ~= nil, "err="..tostring(err))

-- 4. 200 but missing sentinel (proxy page, truncation) must be rejected
stubStatus, stubResponse = 200, "file_path\tslug\nfoo.jpg\tlandscape-08\n"
rows, err = API.postTSV("/web/publish", {})
check("200 without #OK is rejected", rows == nil and err ~= nil, "err="..tostring(err))

-- 5. LENS down entirely
stubStatus, stubResponse = nil, nil
rows, err = API.postTSV("/web/publish", {})
check("unreachable is rejected", rows == nil and err ~= nil, "err="..tostring(err))

-- 6. nil status (SDK doesn't surface it) still works via sentinel
stubStatus, stubResponse = nil, "#OK\nfile_path\tslug\nfoo.jpg\tlandscape-08\n"
rows, err = API.postTSV("/web/publish", {})
check("nil status falls back to sentinel", rows ~= nil and #rows == 1, "err="..tostring(err))

-- 7. empty result set is distinguishable from an error
stubStatus, stubResponse = 200, "#OK\nfile_path\tslug\n"
rows, err = API.postTSV("/web/publish", {})
check("empty set != error", rows ~= nil and #rows == 0 and err == nil, "err="..tostring(err))

print(("\n%d passed, %d failed"):format(pass, fail))
os.exit(fail == 0 and 0 or 1)
