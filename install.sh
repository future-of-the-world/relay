#!/bin/sh
# Installs what relay needs, from deps.toml (the list `relay doctor` checks against): python3 3.11+, git, jq, uv,
# the pinned gate tools (ruff, mypy, pytest), claude, and bun for the gate's hook tests.
# Official installers come first; Homebrew and apt-get are only the fallback. Plain POSIX sh: it runs before python exists.
#   sh install.sh [--dry-run]
# Safe to run again: what is present at the right version is left alone. Every download is pinned and checked against the
# checksum in deps.toml before it runs, except claude's and bun's own installers, which their publishers do not version. Nothing runs under sudo without a line saying so.
# --dry-run prints what would be done and changes nothing.
set -u

dry=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    -h|--help) sed -n "2,9p" "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
case "$os" in Darwin) plat="darwin" ;; *) plat="linux" ;; esac
plat="${plat}_$(uname -m)"
apt_updated=0

say() { printf '%s\n' "$*"; }
run() {   # run a command, or only print it under --dry-run
  if [ "$dry" = 1 ]; then say "  would run: $*"; return 0; fi
  say "  running: $*"
  "$@"
}

# one "name|command|min|exact|version_arg|brew|apt|uv_tool|uv_python|darwin_run|installer_url|installer_sha256|release_url|release_sha256|official_url|official_shell|manual"
# line per entry; release_* is the one for this machine's os and architecture
entries() {
  awk -v plat="$plat" '
    function flush() { if (name != "") print name "|" command "|" min "|" exact "|" varg "|" brew "|" apt "|" uvt "|" uvp "|" drun "|" url "|" sha "|" rurl "|" rsha "|" ourl "|" oshell "|" manual }
    /^\[\[dep\]\]/ { flush(); name=command=min=exact=varg=brew=apt=uvt=uvp=drun=url=sha=rurl=rsha=ourl=oshell=manual=""; name="?"; next }
    /^[a-z_0-9]+ *=/ {
      key=$1; sub(/^[a-z_0-9]+ *= */, ""); val=$0; gsub(/^"|"$/, "", val)
      if (key=="name") name=val; else if (key=="command") command=val; else if (key=="min") min=val
      else if (key=="exact") exact=val; else if (key=="version_arg") varg=val; else if (key=="brew") brew=val
      else if (key=="apt") apt=val; else if (key=="uv_tool") uvt=val; else if (key=="uv_python") uvp=val
      else if (key=="darwin_run") drun=val; else if (key=="installer_url") url=val
      else if (key=="installer_sha256") sha=val; else if (key=="manual") manual=val
      else if (key=="official_url") ourl=val; else if (key=="official_shell") oshell=val
      else if (key=="release_url_" plat) rurl=val; else if (key=="release_sha256_" plat) rsha=val
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

download_checked() {   # download_checked URL SHA FILE: fetch, refuse unless the sha256 is the pinned one
  if ! curl -fsSL "$1" -o "$3"; then say "  download failed: $1"; return 1; fi
  got="$(sha256_of "$3")"
  if [ -z "$got" ] || [ "$got" != "$2" ]; then
    say "  checksum mismatch for $1 (wanted $2, got ${got:-none}); not run"; return 1
  fi
  say "  checksum ok"
}

apt_install() {   # apt_install PACKAGE: root runs apt-get itself, others use sudo; the lists are refreshed once
  sudo_=""
  if [ "$(id -u)" != 0 ]; then
    command -v sudo >/dev/null 2>&1 || { say "  not root and no sudo: run as root or install sudo"; return 1; }
    sudo_="sudo"; say "  this step uses sudo (apt-get install $1)"
  fi
  if [ "$apt_updated" != 1 ]; then run $sudo_ apt-get update || return 1; apt_updated=1; fi
  run $sudo_ apt-get install -y "$1"
}

# install_one NAME COMMAND BREW APT UVTOOL UVPY DRUN URL SHA RURL RSHA OURL OSHELL
# Routes, official first and Homebrew/apt only as the fallback (the owner's order); returns 0 when it did (or would do)
# the install, 2 when this machine has no route. The same order is relay_setup.install_hint, which doctor prints.
install_one() {
  name="$1"; cmd="$2"; brew="$3"; apt="$4"; uvt="$5"; uvp="$6"; drun="$7"; url="$8"; sha="$9"
  shift 9; rurl="$1"; rsha="$2"; ourl="$3"; oshell="${4:-sh}"
  if [ -n "$uvt" ]; then
    say "  via uv tool install"
    if command -v uv >/dev/null 2>&1 || [ "$dry" = 1 ]; then run uv tool install "$uvt"; return $?; fi
    say "  needs uv first; it was not installed"; return 1
  fi
  if [ -n "$uvp" ]; then
    say "  via uv python install (python3.11 lands in ~/.local/bin; python3 itself is not replaced)"
    if command -v uv >/dev/null 2>&1 || [ "$dry" = 1 ]; then run uv python install "$uvp"; return $?; fi
    say "  needs uv first; it was not installed"; return 1
  fi
  if [ -n "$drun" ] && [ "$os" = Darwin ]; then
    say "  via the macOS installer ($drun)"
    run $drun; rc=$?
    [ "$rc" = 0 ] && [ "$dry" != 1 ] && say "  a macOS window opens: finish it, then run install.sh again"
    return $rc
  fi
  if [ -n "$rurl" ]; then
    say "  via the official release binary (pinned, sha256 $rsha)"
    if [ "$dry" = 1 ]; then say "  would download $rurl, check sha256 $rsha, put it at $HOME/.local/bin/$cmd"; return 0; fi
    tmp="$(mktemp "${TMPDIR:-/tmp}/relay-release.XXXXXX")" || return 1
    if ! download_checked "$rurl" "$rsha" "$tmp"; then rm -f "$tmp"; return 1; fi
    mkdir -p "$HOME/.local/bin" && chmod 755 "$tmp" && mv "$tmp" "$HOME/.local/bin/$cmd"; rc=$?
    [ "$rc" = 0 ] || rm -f "$tmp"
    return $rc
  fi
  if [ -n "$url" ]; then
    say "  via the official installer (pinned, sha256 $sha)"
    if [ "$dry" = 1 ]; then say "  would download $url, check sha256 $sha, run it"; return 0; fi
    tmp="$(mktemp "${TMPDIR:-/tmp}/relay-installer.XXXXXX")" || return 1
    if ! download_checked "$url" "$sha" "$tmp"; then rm -f "$tmp"; return 1; fi
    say "  running the installer"
    sh "$tmp"; rc=$?; rm -f "$tmp"; return $rc
  fi
  if [ -n "$ourl" ]; then
    say "  via the official installer (the publisher does not version it, so there is no checksum)"
    if [ "$dry" = 1 ]; then say "  would download $ourl and run it with $oshell"; return 0; fi
    tmp="$(mktemp "${TMPDIR:-/tmp}/relay-installer.XXXXXX")" || return 1
    if ! curl -fsSL "$ourl" -o "$tmp"; then say "  download failed: $ourl"; rm -f "$tmp"; return 1; fi
    "$oshell" "$tmp"; rc=$?; rm -f "$tmp"; return $rc
  fi
  if [ -n "$apt" ] && [ "$os" = Linux ] && command -v apt-get >/dev/null 2>&1; then
    say "  via apt-get (the system package manager)"
    apt_install "$apt"; return $?
  fi
  if [ -n "$brew" ] && [ "$os" = Darwin ] && command -v brew >/dev/null 2>&1; then
    say "  via Homebrew (fallback)"
    run brew install "$brew"; return $?
  fi
  return 2
}

find_python() {   # the first python that is 3.11+ (python3, then versioned names, then the one uv holds); prints its path
  for c in python3 python3.14 python3.13 python3.12 python3.11; do
    v="$(version_of "$c" --version)"
    if [ -n "$v" ] && at_least "$v" "$pymin"; then command -v "$c"; return 0; fi
  done
  if command -v uv >/dev/null 2>&1; then
    c="$(uv python find "$pymin" 2>/dev/null)"
    if [ -n "$c" ] && [ -x "$c" ]; then
      v="$(version_of "$c" --version)"
      if [ -n "$v" ] && at_least "$v" "$pymin"; then echo "$c"; return 0; fi
    fi
  fi
  return 1
}

say "relay installer ($os), reading $deps"
say "ok = already there, install = missing or too old, installed = done now"
[ "$dry" = 1 ] && say "dry run: nothing will be changed"
# local bin of uv and its tools, so the checks below see what was just installed
PATH="$HOME/.local/bin:$PATH"; export PATH

pymin="$(entries | awk -F'|' '$1=="python3" { print $3 }')"; pymin="${pymin:-3.11}"

entries | while IFS='|' read -r name cmd min exact varg brew apt uvt uvp drun url sha rurl rsha ourl oshell man; do
  found="$(version_of "$cmd" "$varg")"
  state=""
  if ! command -v "$cmd" >/dev/null 2>&1; then state="missing"
  elif [ -z "$found" ]; then
    if [ -n "$min" ]; then state="version not readable"; else state="found but not working (prints no version)"; fi
  elif [ -n "$min" ]; then
    if [ "$exact" = true ] && [ "$found" != "$min" ]; then state="found $found, pinned $min"
    elif [ "$exact" != true ] && ! at_least "$found" "$min"; then state="found $found, needs $min+"
    fi
  fi
  if [ -z "$state" ]; then say "ok       $name ${found:+$found}"; continue; fi
  say "install  $name ($state)"
  install_one "$name" "$cmd" "$brew" "$apt" "$uvt" "$uvp" "$drun" "$url" "$sha" "$rurl" "$rsha" "$ourl" "$oshell"; rc=$?
  if [ "$rc" = 2 ]; then
    say "  by hand: ${man:-no automatic way on this machine; install $name with your package manager}"
  elif [ "$rc" != 0 ]; then
    say "  FAILED: $name"
  elif [ "$dry" != 1 ]; then
    say "  installed $name"
  fi
done

say ""
py="$(find_python)"
pyfound="$(version_of python3 --version)"
if [ "$dry" = 1 ]; then
  if [ -n "$py" ]; then
    say "dry run done: would then run $py $relay_dir/bin/relay doctor"
  else
    say "dry run done: python3 is ${pyfound:-missing}; after the python step the doctor would run under the python3.11 that uv installs in $HOME/.local/bin"
  fi
  exit 0
fi
if [ -z "$py" ]; then
  say "python3 is still ${pyfound:-missing}; relay needs $pymin+: run  uv python install $pymin  and put $HOME/.local/bin first on PATH (or install a newer python3), then run install.sh again"
  exit 1
fi
if [ "$(command -v python3)" != "$py" ]; then
  say "python3 on PATH is ${pyfound:-missing}; the doctor runs under $py. To make python3 itself $pymin+, put its folder first on PATH"
fi
say "checking the result with relay doctor"
exec "$py" "$relay_dir/bin/relay" doctor
