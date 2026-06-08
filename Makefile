.PHONY: setup all prepare gold agent eval convert help

help:
	@echo "Targets:"
	@echo "  make setup    Bootstrap venv, install deps, create config templates"
	@echo "  make all        Run full pipeline (prepare → gold → agent → eval)"
	@echo "  make prepare    Build Docker instance images"
	@echo "  make gold       Gold-patch sanity check"
	@echo "  make agent      Convert tasks + run agent trials"
	@echo "  make eval       Grade preds.json per trial"

setup:
	bash setup.sh

all prepare gold agent eval convert:
	bash run_pipeline.sh $@
