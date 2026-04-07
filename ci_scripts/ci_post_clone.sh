#!/bin/sh
set -e

echo "=== ci_post_clone (repo root): Installing Flutter and CocoaPods ==="
echo "CI_PRIMARY_REPOSITORY_PATH=$CI_PRIMARY_REPOSITORY_PATH"
echo "PWD=$(pwd)"

# Flutter SDK — Xcode Cloud doesn't include it
if ! command -v flutter > /dev/null 2>&1; then
    echo "Installing Flutter SDK..."
    git clone --depth 1 --branch stable https://github.com/flutter/flutter.git "$HOME/flutter"
    export PATH="$HOME/flutter/bin:$PATH"
fi

export PATH="$HOME/flutter/bin:$PATH"
flutter --version

cd "$CI_PRIMARY_REPOSITORY_PATH/mobile"
echo "Running flutter pub get in $(pwd)..."
flutter pub get

echo "Running pod install..."
cd ios
pod install --repo-update

echo "Verifying xcfilelist generation..."
ls -la Pods/Target\ Support\ Files/Pods-Runner/Pods-Runner-*-input-files.xcfilelist 2>/dev/null && echo "xcfilelists OK" || echo "WARNING: xcfilelists not found"

echo "=== ci_post_clone complete ==="
