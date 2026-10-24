#!/bin/sh
# Installs what relay needs, from deps.toml (the list `relay doctor` checks against): python3 3.11+, git, jq, uv,
# the pinned gate tools (ruff, mypy, pytest) and, by hand, claude. Plain POSIX sh: it runs before python exists.
#   sh install.sh [--dry-run]
# Safe to run again: what is present at the right version is left alone. Every download is pinned to a version and
# checked against the checksum written in deps.toml before it runs. Nothing runs under sudo without a line saying so.
# --dry-run prints what would be done and changes nothing.
set -u

dry=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: unknown argument $arg (only --dry-run)" >&2; exit 2 ;;
  esac
done

here="$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)"
home="${RELAY_HOME:-$HOME/relay}"
deps=""
for d in "$here" "$home"; do
  [ -n "$d" ] && [ -f "$d/deps.toml" ] && { deps="$d/deps.toml"; relay_dir="$d"; break; }
done
[ -n "$deps" ] || { echo "install.sh: deps.toml not found next to this script or in $home; put the relay folder at ~/relay first (or set RELAY_HOME)" >&2; exit 1; }

os="$(uname -s)"

say() { printf '%s\n' "$*"; }
run() {   # run a command, or only print it under --dry-run
  if [ "$dry" = 1 ]; then say "  would run: $*"; return 0; fi
  say "  running: $*"
  "$@"
}

# one "name|command|min|exact|version_arg|brew|apt|uv_tool|installer_url|installer_sha256|manual" line per entry
entries() {
  awk '
    function flush() { if (name != "") print name "|" command "|" min "|" exact "|" varg "|" brew "|" apt "|" uvt "|" url "|" sha "|" manual }
    /^\[\[dep\]\]/ { flush(); name=command=min=exact=varg=brew=apt=uvt=url=sha=manual=""; name="?"; next }
    /^[a-z_0-9]+ *=/ {
      key=$1; sub(/^[a-z_0-9]+ *= */, ""); val=$0; gsub(/^"|"$/, "", val)
      if (key=="name") name=val; else if (key=="command") command=val; else if (key=="min") min=val
      else if (key=="exact") exact=val; else if (key=="version_arg") varg=val; else if (key=="brew") brew=val
      else if (key=="apt") apt=val; else if (key=="uv_tool") uvt=val; else if (key=="installer_url") url=val
      else if (key=="installer_sha256") sha=val; else if (key=="manual") manual=val
    }
    END { flush() }
  ' "$deps"
}

version_of() {   # the first dotted number the tool prints, empty when it is missing or prints none
  command -v "$1" >/dev/null 2>&1 || return 0
  "$1" "$2" 2>&1 | head -n 5 | grep -Eo '[0-9]+(\.[0-9]+)+' | head -n 1
}

at_least() {   # at_least FOUND WANT: dotted numbers, FOUND >= WANT
  awk -v a="$1" -v b="$2" 'BEGIN { na=split(a,x,"."); nb=split(b,y,"."); n=(na>nb?na:nb)
    for (i=1;i<=n;i++) { p=x[i]+0; q=y[i]+0; if (p>q) exit 0; if (p<q) exit 1 } exit 0 }'
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else echo ""; fi
}

install_one() {   # install_one NAME BREW APT UVTOOL URL SHA MANUAL; returns 0 when it did (or would do) the install
  name="$1"; brew="$2"; apt="$3"; uvt="$4"; url="$5"; sha="$6"; man="$7"
  if [ -n "$uvt" ]; then
    if command -v uv >/dev/null 2>&1 || [ "$dry" = 1 ]; then run uv tool install "$uvt"; return $?; fi
    say "  needs uv first; it was not installed"; return 1
  fi
  if [ -n "$brew" ] && [ "$os" = Darwin ] && command -v brew >/dev/null 2>&1; then run brew install "$brew"; return $?; fi
  if [ -n "$apt" ] && [ "$os" = Linux ] && command -v apt-get >/dev/null 2>&1; then
    say "  this step uses sudo (apt-get install $apt)"
    run sudo apt-get install -y "$apt"; return $?
  fi
  if [ -n "$url" ]; then
    if [ "$dry" = 1 ]; then say "  would download $url, check sha256 $sha, run it"; return 0; fi
    tmp="$(mktemp "${TMPDIR:-/tmp}/relay-installer.XXXXXX")" || return 1
    if ! curl -fsSL "$url" -o "$tmp"; then say "  download failed: $url"; rm -f "$tmp"; return 1; fi
    got="$(sha256_of "$tmp")"
    if [ -z "$got" ] || [ "$got" != "$sha" ]; then
      say "  checksum mismatch for $url (wanted $sha, got ${got:-none}); not run"; rm -f "$tmp"; return 1
    fi
    say "  checksum ok; running the installer"
    sh "$tmp"; rc=$?; rm -f "$tmp"; return $rc
  fi
  return 2
}

say "relay installer ($os), reading $deps"
say "ok = already there, install = missing or too old, installed = done now"
[ "$dry" = 1 ] && say "dry run: nothing will be changed"
# local bin of uv and its tools, so the checks below see what was just installed
PATH="$HOME/.local/bin:$PATH"; export PATH

entries | while IFS='|' read -r name cmd min exact varg brew apt uvt url sha man; do
  found="$(version_of "$cmd" "$varg")"
  state=""
  if ! command -v "$cmd" >/dev/null 2>&1; then state="missing"
  elif [ -n "$min" ]; then
    if [ -z "$found" ]; then state="version not readable"
    elif [ "$exact" = true ] && [ "$found" != "$min" ]; then state="found $found, pinned $min"
    elif [ "$exact" != true ] && ! at_least "$found" "$min"; then state="found $found, needs $min+"
    fi
  fi
  if [ -z "$state" ]; then say "ok       $name ${found:+$found}"; continue; fi
  say "install  $name ($state)"
  install_one "$name" "$brew" "$apt" "$uvt" "$url" "$sha" "$man"; rc=$?
  if [ "$rc" = 2 ]; then
    say "  by hand: ${man:-no automatic way on this machine (no Homebrew or apt-get); install $name with your package manager}"
  elif [ "$rc" != 0 ]; then
    say "  FAILED: $name"
  elif [ "$dry" != 1 ]; then
    say "  installed $name"
  fi
done

say ""
if [ "$dry" = 1 ]; then
  say "dry run done: would then run $relay_dir/bin/relay doctor"
  exit 0
fi
say "checking the result with relay doctor"
exec "$relay_dir/bin/relay" doctor
