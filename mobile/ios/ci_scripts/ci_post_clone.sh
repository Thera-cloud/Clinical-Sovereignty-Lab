#!/bin/sh
set -e

echo "=== ci_post_clone: Installing Flutter and CocoaPods ==="

# Flutter SDK — Xcode Cloud doesn't include it
if ! command -v flutter &> /dev/null; then
    echo "Installing Flutter SDK..."
    git clone --depth 1 --branch stable https://github.com/flutter/flutter.git "$HOME/flutter"
    export PATH="$HOME/flutter/bin:$PATH"
fi

echo "Flutter version: $(flutter --version --machine | head -1)"

cd "$CI_PRIMARY_REPOSITORY_PATH/mobile"

echo "Running flutter pub get..."
flutter pub get

echo "Running pod install..."
cd ios
pod install --repo-update

echo "=== ci_post_clone complete ==="
