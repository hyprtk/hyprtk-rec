.PHONY: test run install version qa lint

test:
	PYTHONPATH=. python3 -m unittest discover -s tests -v

run:
	./bin/hyprtk-rec

install:
	./install.sh

version:
	PYTHONPATH=. python3 -m hyprtk_rec --version

qa:
	./scripts/qa.sh

lint:
	python3 -m compileall -q hyprtk_rec tests scripts
