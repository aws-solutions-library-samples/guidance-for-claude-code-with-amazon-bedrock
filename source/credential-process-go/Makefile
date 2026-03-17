VERSION ?= 1.0.0-beta
LDFLAGS := -ldflags="-s -w -X main.version=$(VERSION)"
CRED_BINARY := credential-process
OTEL_BINARY := otel-helper-go

.PHONY: build build-all clean test \
	build-cred build-otel \
	build-cred-macos-arm64 build-cred-macos-intel build-cred-linux-x64 build-cred-linux-arm64 build-cred-windows \
	build-otel-macos-arm64 build-otel-macos-intel build-otel-linux-x64 build-otel-linux-arm64 build-otel-windows

# Default: build both for current platform
build: build-cred build-otel

build-cred:
	go build $(LDFLAGS) -o $(CRED_BINARY) ./cmd/credential-process

build-otel:
	go build $(LDFLAGS) -o $(OTEL_BINARY) ./cmd/otel-helper

# Build all platforms
build-all: build-all-cred build-all-otel

build-all-cred: build-cred-macos-arm64 build-cred-macos-intel build-cred-linux-x64 build-cred-linux-arm64 build-cred-windows
build-all-otel: build-otel-macos-arm64 build-otel-macos-intel build-otel-linux-x64 build-otel-linux-arm64 build-otel-windows

# Credential process cross-compile targets
build-cred-macos-arm64:
	GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o $(CRED_BINARY)-macos-arm64 ./cmd/credential-process

build-cred-macos-intel:
	GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o $(CRED_BINARY)-macos-intel ./cmd/credential-process

build-cred-linux-x64:
	GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o $(CRED_BINARY)-linux-x64 ./cmd/credential-process

build-cred-linux-arm64:
	GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o $(CRED_BINARY)-linux-arm64 ./cmd/credential-process

build-cred-windows:
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o $(CRED_BINARY)-windows.exe ./cmd/credential-process

# OTEL helper cross-compile targets
build-otel-macos-arm64:
	GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o $(OTEL_BINARY)-macos-arm64 ./cmd/otel-helper

build-otel-macos-intel:
	GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o $(OTEL_BINARY)-macos-intel ./cmd/otel-helper

build-otel-linux-x64:
	GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o $(OTEL_BINARY)-linux-x64 ./cmd/otel-helper

build-otel-linux-arm64:
	GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o $(OTEL_BINARY)-linux-arm64 ./cmd/otel-helper

build-otel-windows:
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o $(OTEL_BINARY)-windows.exe ./cmd/otel-helper

clean:
	rm -f $(CRED_BINARY) $(CRED_BINARY)-* $(OTEL_BINARY) $(OTEL_BINARY)-*

test:
	go test ./...
