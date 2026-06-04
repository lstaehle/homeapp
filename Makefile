.PHONY: test test-unit test-system

test-unit:
	pytest tests/unit/ -v

test-system:
	pytest tests/system/ -v

test: test-unit test-system
