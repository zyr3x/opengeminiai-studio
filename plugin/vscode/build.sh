#!/bin/bash

echo "🚀 Starting Full Build process..."

# Ensure we are in the script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# 1. Clean previous builds
echo "🧹 Cleaning up old artifacts..."
rm -rf out
rm -f *.vsix

# 2. Check & Install Dependencies
if [ ! -d "node_modules" ]; then
    echo "📦 'node_modules' not found. Performing fresh install..."
    npm install
else
    echo "📦 Dependencies found. Ensuring they are up to date..."
    npm install
fi

# 3. Compile TypeScript
echo "🔨 Compiling TypeScript..."
npm run compile

# 4. Package Extension
echo "📦 Packaging Extension (.vsix)..."
# Use npx to run vsce without global installation requirement
npx vsce package --allow-missing-repository

echo "✅ Build Complete!"
ls -lh *.vsix