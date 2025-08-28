.PHONY: lint type test run

lint:
	ruff check .
	black --check .

type:
	mypy .

test:
	pytest -q

run:
	python ibkr_etf_rebalancer/app.py $(ARGS)

