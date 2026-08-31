# CoApis C2A Server Build Makefile

.PHONY: build-server install-server-dev clean-server build-all-server

build-server:
	@echo "Building server packages..."
	pip install --upgrade build
	cd server/c2a_protocol && python -m build
	cd server/c2a_adapters && python -m build
	@echo "Server protocol and adapters built successfully in server/*/dist/"

build-all-server:
	@echo "Building all server packages including gateway and plugins..."
	pip install --upgrade build
	cd server/c2a_protocol && python -m build
	cd server/c2a_adapters && python -m build
	cd server/c2a-gateway-fastapi && python -m build
	cd server/c2a-langchain-plugin && python -m build
	cd server/c2a-autogen-plugin && python -m build
	@echo "All server packages built successfully in server/*/dist/"

install-server-dev:
	@echo "Installing server packages in development mode..."
	pip install -e ./server/c2a_protocol
	pip install -e ./server/c2a_adapters
	@echo "Server protocol and adapters installed successfully."

clean-server:
	@echo "Cleaning server build artifacts..."
	rm -rf server/c2a_protocol/dist/ server/c2a_protocol/build/ server/c2a_protocol/*.egg-info/
	rm -rf server/c2a_adapters/dist/ server/c2a_adapters/build/ server/c2a_adapters/*.egg-info/
	rm -rf server/c2a-gateway-fastapi/dist/ server/c2a-gateway-fastapi/build/ server/c2a-gateway-fastapi/*.egg-info/
	rm -rf server/c2a-langchain-plugin/dist/ server/c2a-langchain-plugin/build/ server/c2a-langchain-plugin/*.egg-info/
	rm -rf server/c2a-autogen-plugin/dist/ server/c2a-autogen-plugin/build/ server/c2a-autogen-plugin/*.egg-info/
	@echo "Server build artifacts cleaned."
