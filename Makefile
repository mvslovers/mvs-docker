REGISTRY = ghcr.io/mvslovers
TAG      = latest

# --- Image: mvsce-builder ---

.PHONY: mvsce-builder publish-mvsce-builder test-mvsce-builder clean-mvsce-builder

mvsce-builder:
	DOCKER_BUILDKIT=1 docker build -t $(REGISTRY)/mvsce-builder:$(TAG) mvsce-builder/

publish-mvsce-builder: mvsce-builder
	docker push $(REGISTRY)/mvsce-builder:$(TAG)

test-mvsce-builder:
	docker run -d --name mvsce-test \
	  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 8080:8080 -p 8888:8888 \
	  $(REGISTRY)/mvsce-builder:$(TAG)
	@echo "Waiting for MVS IPL..."
	@sleep 15
	curl -sf -u IBMUSER:SYS1 http://localhost:8080/zosmf/info
	docker stop mvsce-test && docker rm mvsce-test

clean-mvsce-builder:
	docker rmi $(REGISTRY)/mvsce-builder:$(TAG) || true

# --- Image: mvs-dev ---

.PHONY: mvs-dev publish-mvs-dev test-mvs-dev clean-mvs-dev

mvs-dev:
	docker build -t $(REGISTRY)/mvs-dev:$(TAG) mvs-dev/

publish-mvs-dev: mvs-dev
	docker push $(REGISTRY)/mvs-dev:$(TAG)

test-mvs-dev:
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) c2asm370 --version
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) nvim --version | head -1
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) node --version
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) zowe --version
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) gh --version | head -1
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) fzf --version
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) rg --version | head -1
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) fd --version
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) lazygit --version
	docker run --rm $(REGISTRY)/mvs-dev:$(TAG) tree-sitter --version

clean-mvs-dev:
	docker rmi $(REGISTRY)/mvs-dev:$(TAG) || true

# --- Convenience aliases ---

.PHONY: all publish clean
all: mvsce-builder mvs-dev
publish: publish-mvsce-builder publish-mvs-dev
clean: clean-mvsce-builder clean-mvs-dev
