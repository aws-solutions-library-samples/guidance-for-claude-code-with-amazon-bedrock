VERSION ?= 1.0.0
LDFLAGS := -ldflags="-s -w -X main.version=$(VERSION)"
BINARY := credential-process

.PHONY: build build-all clean test

build:
	go build $(LDFLAGS) -o $(BINARY) .

build-all: build-macos-arm64 build-macos-intel build-linux-x64 build-linux-arm64 build-windows

build-macos-arm64:
	GOOS=darwin GOARCH=arm64 go build $(LDFLAGS) -o $(BINARY)-macos-arm64 .

build-macos-intel:
	GOOS=darwin GOARCH=amd64 go build $(LDFLAGS) -o $(BINARY)-macos-intel .

build-linux-x64:
	GOOS=linux GOARCH=amd64 go build $(LDFLAGS) -o $(BINARY)-linux-x64 .

build-linux-arm64:
	GOOS=linux GOARCH=arm64 go build $(LDFLAGS) -o $(BINARY)-linux-arm64 .

build-windows:
	GOOS=windows GOARCH=amd64 go build $(LDFLAGS) -o $(BINARY)-windows.exe .

clean:
	rm -f $(BINARY) $(BINARY)-*

test:
	go test ./...
