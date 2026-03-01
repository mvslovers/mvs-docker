REGISTRY    = ghcr.io/mvslovers
TAG         = latest
DOCKER_HOST = mvsdev.lan
REPO_DIR    = repos/mvs-docker

# --- Image: mvsce-builder ---

.PHONY: mvsce-builder publish-mvsce-builder test-mvsce-builder clean-mvsce-builder

mvsce-builder:
	ssh $(DOCKER_HOST) "cd $(REPO_DIR) && docker build -t $(REGISTRY)/mvsce-builder:$(TAG) mvsce-builder/"

publish-mvsce-builder: mvsce-builder
	ssh $(DOCKER_HOST) "docker push $(REGISTRY)/mvsce-builder:$(TAG)"

test-mvsce-builder:
	ssh $(DOCKER_HOST) "docker run -d --name mvsce-test \
	  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 1080:1080 -p 8888:8888 \
	  $(REGISTRY)/mvsce-builder:$(TAG)"
	@echo "Waiting for MVS IPL..."
	@sleep 60
	ssh $(DOCKER_HOST) "curl -sf -u IBMUSER:SYS1 http://localhost:1080/zosmf/info"
	ssh $(DOCKER_HOST) "docker stop mvsce-test && docker rm mvsce-test"

clean-mvsce-builder:
	ssh $(DOCKER_HOST) "docker rmi $(REGISTRY)/mvsce-builder:$(TAG) || true"

# --- Convenience aliases ---

.PHONY: all publish clean
all: mvsce-builder
publish: publish-mvsce-builder
clean: clean-mvsce-builder
