#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
DATA_DIR="$SRC_DIR/data"

mkdir -p "$DATA_DIR"

move_json_file() {
  local source_path="$1"
  local target_path="$2"

  if [[ -f "$source_path" ]]; then
    mv -f "$source_path" "$target_path"
    printf 'Moved %s -> %s\n' "$source_path" "$target_path"
  fi
}

rewrite_file() {
  local file_path="$1"
  local search_text="$2"
  local replace_text="$3"

  if [[ -f "$file_path" ]]; then
    local python_bin=""
    if command -v python3 >/dev/null 2>&1; then
      python_bin="python3"
    elif command -v python >/dev/null 2>&1; then
      python_bin="python"
    else
      printf 'Python is required to rewrite %s\n' "$file_path" >&2
      exit 1
    fi

    "$python_bin" - "$file_path" "$search_text" "$replace_text" <<'PY'
import pathlib
import sys

file_path = pathlib.Path(sys.argv[1])
search_text = sys.argv[2]
replace_text = sys.argv[3]

content = file_path.read_text(encoding="utf-8")
content = content.replace(search_text, replace_text)
file_path.write_text(content, encoding="utf-8")
PY
  fi
}

move_json_file "$SRC_DIR/active_trades.json" "$DATA_DIR/active_trades.json"
move_json_file "$SRC_DIR/notify_roles.json" "$DATA_DIR/notify_roles.json"
move_json_file "$SRC_DIR/reaction_role_posts.json" "$DATA_DIR/reaction_role_posts.json"
move_json_file "$SRC_DIR/reaction_roles_config.json" "$DATA_DIR/reaction_roles_config.json"
move_json_file "$SRC_DIR/trading_config.json" "$DATA_DIR/trading_config.json"
move_json_file "$SRC_DIR/voice_owners.json" "$DATA_DIR/voice_owners.json"
move_json_file "$SRC_DIR/warnings.json" "$DATA_DIR/warnings.json"
move_json_file "$SRC_DIR/welcome_config.json" "$DATA_DIR/welcome_config.json"
move_json_file "$SRC_DIR/item_list.json" "$DATA_DIR/item_list.json"

rewrite_file "$SRC_DIR/cogs/trade_system.py" 'Path(__file__).resolve().parent.parent / "item_list.json"' 'Path(__file__).resolve().parent.parent / "data" / "item_list.json"'
rewrite_file "$SRC_DIR/cogs/trade_system.py" 'Path(__file__).resolve().parent.parent / "active_trades.json"' 'Path(__file__).resolve().parent.parent / "data" / "active_trades.json"'
rewrite_file "$SRC_DIR/cogs/notify_role.py" 'Path(__file__).resolve().parent.parent / "notify_roles.json"' 'Path(__file__).resolve().parent.parent / "data" / "notify_roles.json"'
rewrite_file "$SRC_DIR/cogs/reaction_role_post.py" 'Path(__file__).resolve().parent.parent / "reaction_role_posts.json"' 'Path(__file__).resolve().parent.parent / "data" / "reaction_role_posts.json"'
rewrite_file "$SRC_DIR/cogs/trading_access.py" 'Path(__file__).resolve().parent.parent / "trading_config.json"' 'Path(__file__).resolve().parent.parent / "data" / "trading_config.json"'
rewrite_file "$SRC_DIR/cogs/voice_channels.py" 'Path(__file__).resolve().parent.parent / "voice_owners.json"' 'Path(__file__).resolve().parent.parent / "data" / "voice_owners.json"'
rewrite_file "$SRC_DIR/cogs/link_monitor.py" 'Path(__file__).resolve().parent.parent / "warnings.json"' 'Path(__file__).resolve().parent.parent / "data" / "warnings.json"'
rewrite_file "$SRC_DIR/cogs/welcome.py" 'Path(__file__).resolve().parent.parent / "welcome_config.json"' 'Path(__file__).resolve().parent.parent / "data" / "welcome_config.json"'
rewrite_file "$SRC_DIR/scrape_item_list.py" 'Path(__file__).with_name("item_list.json")' 'Path(__file__).resolve().parent / "data" / "item_list.json"'

printf 'JSON migration complete.\n'