module chromium.googlesource.com/chromiumos/infra/recipes/support/gerrit-fetch-changes

require (
	chromium.googlesource.com/chromiumos/infra/recipes/support/internal/cli v0.0.0
	github.com/golang/mock v1.2.0 // indirect
	github.com/golang/protobuf v1.2.1-0.20190109072247-347cf4a86c1c // indirect
	github.com/gopherjs/gopherjs v0.0.0-20181103185306-d547d1d9531e // indirect
	github.com/jtolds/gls v4.2.1+incompatible // indirect
	github.com/julienschmidt/httprouter v1.2.0 // indirect
	github.com/smartystreets/assertions v0.0.0-20180927180507-b2de0cb4f26d // indirect
	github.com/smartystreets/goconvey v0.0.0-20181108003508-044398e4856c // indirect
	go.chromium.org/luci v0.0.0-20190114200033-fb39777d1b49
)

replace chromium.googlesource.com/chromiumos/infra/recipes/support/internal/cli => ../internal/cli
