# AMR Controller — development / verification entry points.
#
#   make analyze       static analysis
#   make test          unit + real-client integration tests (real sockets,
#                      real production RobotApiService/RobotProvider, against
#                      MockRobot — a loopback re-creation of the robot HTTP API)
#   make test-e2e      the full on-host client verification (analyze + test)
#   make build-web     production web release
#   make build-apk     Android APK + AAB
#
# The mock robot is in-process (test/helpers/mock_robot.dart), so there is no
# external process to start or clean up — the suite starts and stops it itself
# and returns non-zero on any failure.

SHELL := /bin/bash
FLUTTER ?= flutter

.PHONY: all analyze test test-e2e test-integration build-web build-apk clean

all: analyze test

analyze:
	$(FLUTTER) analyze

# Real-client integration + model + shell tests. No fake — the client classes
# here are the production lib/services/robot_api_service.dart and
# lib/providers/robot_provider.dart, opening real TCP sockets to MockRobot.
test:
	$(FLUTTER) test

# The on-host integration test runs real widgets + real sockets under the
# integration_test binding. It needs a native desktop/device target (no Xcode,
# no web, no emulator on this host), so it is run in CI on Linux with a virtual
# display; here it is gated on a target being available.
test-integration:
	@if [ "$$CI" = "true" ] || command -v xvfb-run >/dev/null 2>&1; then \
		$(FLUTTER) test integration_test/connection_test.dart -d linux; \
	else \
		echo "test-integration: requires a Linux desktop runner with a display (run in CI)"; \
		exit 0; \
	fi

# One command to reproduce the complete client verification locally.
test-e2e: analyze test
	@echo "E2E client verification passed (analyze + real-client integration tests)."

build-web:
	$(FLUTTER) build web --release

build-apk:
	$(FLUTTER) build apk --release
	$(FLUTTER) build appbundle --release

clean:
	$(FLUTTER) clean