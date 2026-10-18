REGISTRY = ghcr.io/mvslovers
TAG      = latest

# --- Image: mvsce ---

.PHONY: mvsce publish-mvsce test-mvsce clean-mvsce

mvsce:
	DOCKER_BUILDKIT=1 docker build -t $(REGISTRY)/mvsce:$(TAG) mvsce/

publish-mvsce: mvsce
	docker push $(REGISTRY)/mvsce:$(TAG)

# --rm: the image declares six VOLUMEs, and a plain `docker rm` leaves
# them behind as anonymous volumes on every run.
test-mvsce:
	docker run -d --rm --name mvsce-test \
	  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 8080:8080 -p 8888:8888 \
	  $(REGISTRY)/mvsce:$(TAG)
	@echo "Waiting for MVS IPL and HTTPD..."
	@rc=1; for i in $$(seq 1 60); do \
	  if curl -sf -u IBMUSER:SYS1 'http://localhost:8080/zosmf/test?fn=version'; then rc=0; break; fi; \
	  sleep 5; \
	done; \
	[ $$rc -eq 0 ] || docker logs --tail 50 mvsce-test; \
	docker stop mvsce-test >/dev/null; \
	exit $$rc

clean-mvsce:
	docker rmi $(REGISTRY)/mvsce:$(TAG) || true

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
all: mvsce mvs-dev
publish: publish-mvsce publish-mvs-dev
clean: clean-mvsce clean-mvs-dev
