VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LDFLAGS := -s -w -X github.com/bluedoors/ccwb-binaries/internal/version.Version=$(VERSION)
OUT ?= bin

.PHONY: all test clean fmt vet macos-arm64 macos-intel linux-x64 linux-arm64 windows

all: macos-arm64 macos-intel linux-x64 linux-arm64 windows

test:
	go test ./... -v

fmt:
	go fmt ./...

vet:
	go vet ./...

clean:
	rm -rf $(OUT)

macos-arm64:
	@mkdir -p $(OUT)
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/credential-process-macos-arm64 ./cmd/credential-process/
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/otel-helper-macos-arm64 ./cmd/otel-helper/

macos-intel:
	@mkdir -p $(OUT)
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/credential-process-macos-intel ./cmd/credential-process/
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/otel-helper-macos-intel ./cmd/otel-helper/

linux-x64:
	@mkdir -p $(OUT)
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/credential-process-linux-x64 ./cmd/credential-process/
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/otel-helper-linux-x64 ./cmd/otel-helper/

linux-arm64:
	@mkdir -p $(OUT)
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/credential-process-linux-arm64 ./cmd/credential-process/
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/otel-helper-linux-arm64 ./cmd/otel-helper/

windows:
	@mkdir -p $(OUT)
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/credential-process-windows.exe ./cmd/credential-process/
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o $(OUT)/otel-helper-windows.exe ./cmd/otel-helper/
