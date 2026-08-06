#!/usr/bin/env bash

set -euo pipefail

start_redis_port() {
	local port="$1"
	if redis-cli -p "$port" ping >/dev/null 2>&1; then
		return
	fi
	redis-server --daemonize yes --port "$port" --save "" --appendonly no --dir /tmp
	for _ in {1..20}; do
		redis-cli -p "$port" ping >/dev/null 2>&1 && return
		sleep 1
	done
	echo "Redis did not start on port $port" >&2
	exit 1
}

sudo apt-get update
sudo apt-get install -y libcups2-dev libmariadb-dev mariadb-client pkg-config redis-server
python -m pip install frappe-bench

bench init --skip-assets --python "$(command -v python)" --frappe-branch "$FRAPPE_BRANCH" /home/runner/frappe-bench
cd /home/runner/frappe-bench

bench get-app erpnext https://github.com/frappe/erpnext --branch "$ERPNEXT_BRANCH" --resolve-deps
bench get-app --overwrite "$APP_NAME" "$GITHUB_WORKSPACE"
bench setup requirements --dev

start_redis_port 11000
start_redis_port 13000

CI=Yes bench build --apps "frappe,erpnext,$APP_NAME"

bench new-site test_site \
	--db-host 127.0.0.1 \
	--db-port 3306 \
	--mariadb-root-password root \
	--admin-password admin \
	--no-mariadb-socket

bench --site test_site install-app erpnext
bench --site test_site install-app "$APP_NAME"
bench --site test_site migrate
