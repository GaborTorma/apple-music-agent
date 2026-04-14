REMOTE_HOST := $(shell sed -n 's/^DEFAULT_REMOTE_HOST="\(.*\)"/\1/p' scripts/config.sh)
SERVICE_LABEL := $(shell sed -n 's/^SERVICE_LABEL="\(.*\)"/\1/p' scripts/config.sh)
INSTALL_DIR := $(shell sed -n 's|^INSTALL_DIR="$$HOME/\(.*\)"|\1|p' scripts/config.sh)

.PHONY: deploy install logs logs-stdout status restart stop tail ssh env

## First-time setup (asks local/remote)
install:
	./scripts/install.sh

## Pull latest code and restart service (asks local/remote)
deploy:
	./scripts/deploy.sh

## Tail stderr logs on remote
logs:
	ssh $(REMOTE_HOST) 'tail -f ~/Library/Logs/apple-music-agent/stderr.log'

## Tail stdout logs on remote
logs-stdout:
	ssh $(REMOTE_HOST) 'tail -f ~/Library/Logs/apple-music-agent/stdout.log'

## Show remote service status
status:
	ssh $(REMOTE_HOST) 'launchctl print gui/$$(id -u)/$(SERVICE_LABEL) 2>&1 | head -20'

## Restart remote service
restart:
	ssh $(REMOTE_HOST) 'launchctl kickstart -k gui/$$(id -u)/$(SERVICE_LABEL)'

## Stop remote service
stop:
	ssh $(REMOTE_HOST) 'launchctl kill SIGTERM gui/$$(id -u)/$(SERVICE_LABEL)'

## Show last N lines of remote logs (default: 50)
N ?= 50
tail:
	ssh $(REMOTE_HOST) 'tail -$(N) ~/Library/Logs/apple-music-agent/stderr.log'

## Open SSH session to remote
ssh:
	ssh $(REMOTE_HOST)

## Edit .env on remote
env:
	ssh -t $(REMOTE_HOST) '$${EDITOR:-nano} ~/$(INSTALL_DIR)/.env'

# Optional local overrides (gitignored)
-include Makefile.local
