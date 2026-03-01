REGISTRY = ghcr.io/mvslovers
TAG      = latest

# --- Image: mvsce-builder ---

.PHONY: mvsce-builder publish-mvsce-builder test-mvsce-builder clean-mvsce-builder

mvsce-builder:
	docker build -t $(REGISTRY)/mvsce-builder:$(TAG) mvsce-builder/

publish-mvsce-builder: mvsce-builder
	docker push $(REGISTRY)/mvsce-builder:$(TAG)

test-mvsce-builder:
	docker run -d --name mvsce-test \
	  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 1080:1080 -p 8888:8888 \
	  $(REGISTRY)/mvsce-builder:$(TAG)
	@echo "Waiting for MVS IPL..."
	@sleep 15
	curl -sf -u IBMUSER:SYS1 http://localhost:1080/zosmf/info
	docker stop mvsce-test && docker rm mvsce-test

clean-mvsce-builder:
	docker rmi $(REGISTRY)/mvsce-builder:$(TAG) || true

# --- Convenience aliases ---

.PHONY: all publish clean
all: mvsce-builder
publish: publish-mvsce-builder
clean: clean-mvsce-builder
