#!/bin/bash
# wget -q -O - https://raw.githubusercontent.com/FaintGhost/ha-xiaobiu/main/install.sh | bash -
# wget -q -O - https://raw.githubusercontent.com/FaintGhost/ha-xiaobiu/main/install.sh | ARCHIVE_TAG=v0.1.6 bash -
set -e

[ -z "$DOMAIN" ] && DOMAIN="xiaobiu"
[ -z "$REPO_PATH" ] && REPO_PATH="FaintGhost/ha-xiaobiu"
REPO_NAME=$(basename "$REPO_PATH")

[ -z "$ARCHIVE_TAG" ] && ARCHIVE_TAG="$1"
[ -z "$ARCHIVE_TAG" ] && ARCHIVE_TAG="main"
[ -z "$HUB_DOMAIN" ] && HUB_DOMAIN="github.com"
ARCHIVE_URL="https://$HUB_DOMAIN/$REPO_PATH/archive/$ARCHIVE_TAG.zip"

RED_COLOR='\033[0;31m'
GREEN_COLOR='\033[0;32m'
GREEN_YELLOW='\033[1;33m'
NO_COLOR='\033[0m'

declare haPath
declare ccPath
declare -a paths=(
    "$PWD"
    "$PWD/config"
    "/config"
    "$HOME/.homeassistant"
    "/usr/share/hassio/homeassistant"
)

function info ()  { echo -e "${GREEN_COLOR}INFO: $1${NO_COLOR}"; }
function warn ()  { echo -e "${GREEN_YELLOW}WARN: $1${NO_COLOR}"; }
function error () { echo -e "${RED_COLOR}ERROR: $1${NO_COLOR}"; if [ "$2" != "false" ]; then exit 1; fi; }

function checkRequirement () {
    if [ -z "$(command -v "$1")" ]; then
        error "'$1' is not installed"
    fi
}

checkRequirement "wget"
checkRequirement "unzip"

info "Archive URL: $ARCHIVE_URL"
info "Trying to find the correct directory..."
for path in "${paths[@]}"; do
    if [ -n "$haPath" ]; then
        break
    fi
    if [ -f "$path/home-assistant.log" ]; then
        haPath="$path"
    elif [ -d "$path/.storage" ] && [ -f "$path/configuration.yaml" ]; then
        haPath="$path"
    fi
done

if [ -n "$haPath" ]; then
    info "Found Home Assistant configuration directory at '$haPath'"
    cd "$haPath" || error "Could not change path to $haPath"
    ccPath="$haPath/custom_components"
    if [ ! -d "$ccPath" ]; then
        info "Creating custom_components directory..."
        mkdir "$ccPath"
    fi

    cd "$ccPath" || error "Could not change path to $ccPath"

    info "Downloading..."
    wget -t 2 -O "$ccPath/$ARCHIVE_TAG.zip" "$ARCHIVE_URL"

    if [ -d "$ccPath/$DOMAIN" ]; then
        warn "custom_components/$DOMAIN already exists, cleaning up..."
        rm -rf "$ccPath/$DOMAIN"
    fi

    ver=${ARCHIVE_TAG/#v/}

    info "Unpacking..."
    unzip -o "$ccPath/$ARCHIVE_TAG.zip" -d "$ccPath" >/dev/null 2>&1

    extracted_dir="$ccPath/$REPO_NAME-$ver"
    if [ ! -d "$extracted_dir" ]; then
        error "Could not find extracted directory: $extracted_dir"
    fi

    cp -rf "$extracted_dir/custom_components/$DOMAIN" "$ccPath"

    info "Removing temp files..."
    rm -rf "$ccPath/$ARCHIVE_TAG.zip"
    rm -rf "$extracted_dir"

    info "Installation complete."
    info "安装成功！"
    echo
    info "Remember to restart Home Assistant before you configure it."
    info "请重启 Home Assistant，然后在集成页面搜索 Xiaobiu 进行配置。"
else
    echo
    error "Could not find the Home Assistant configuration directory." false
    error "找不到 Home Assistant 根目录" false
    echo "请手动进入 Home Assistant 根目录后再次执行此脚本"
    exit 1
fi
