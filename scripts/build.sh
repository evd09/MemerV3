#!/bin/bash
# Build script for V3.3.1 - Asset Minification
# Minifies JavaScript files using Terser

set -e  # Exit on error

echo "================================================"
echo "Building MemerV3 Assets - V3.3.1"
echo "================================================"

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Installing..."
    apt-get update && apt-get install -y nodejs npm
fi

# Install Terser if not present
if ! command -v terser &> /dev/null; then
    echo "📦 Installing Terser..."
    npm install -g terser
fi

echo ""
echo "🔨 Minifying JavaScript..."
echo ""

# Minify app.js
APP_JS="memer/cogs/web/static/js/app.js"
APP_MIN="memer/cogs/web/static/js/app.min.js"

if [ -f "$APP_JS" ]; then
    ORIGINAL_SIZE=$(wc -c < "$APP_JS")
    echo "  app.js: $(numfmt --to=iec-i --suffix=B $ORIGINAL_SIZE)"
    
    terser "$APP_JS" \
        --compress \
        --mangle \
        --output "$APP_MIN"
    
    MINIFIED_SIZE=$(wc -c < "$APP_MIN")
    REDUCTION=$(echo "scale=1; 100 - ($MINIFIED_SIZE * 100 / $ORIGINAL_SIZE)" | bc)
    
    echo "  → app.min.js: $(numfmt --to=iec-i --suffix=B $MINIFIED_SIZE) (-${REDUCTION}%)"
else
    echo "  ❌ $APP_JS not found"
    exit 1
fi

# Minify sw.js
SW_JS="memer/cogs/web/static/sw.js"
SW_MIN="memer/cogs/web/static/sw.min.js"

if [ -f "$SW_JS" ]; then
    ORIGINAL_SIZE=$(wc -c < "$SW_JS")
    echo "  sw.js: $(numfmt --to=iec-i --suffix=B $ORIGINAL_SIZE)"
    
    terser "$SW_JS" \
        --compress \
        --mangle \
        --output "$SW_MIN"
    
    MINIFIED_SIZE=$(wc -c < "$SW_MIN")
    REDUCTION=$(echo "scale=1; 100 - ($MINIFIED_SIZE * 100 / $ORIGINAL_SIZE)" | bc)
    
    echo "  → sw.min.js: $(numfmt --to=iec-i --suffix=B $MINIFIED_SIZE) (-${REDUCTION}%)"
else
    echo "  ❌ $SW_JS not found"
    exit 1
fi

echo ""
echo "================================================"
echo "✅ Build Complete!"
echo "================================================"
echo ""
echo "Minified files created:"
echo "  - $APP_MIN"
echo "  - $SW_MIN"
echo ""
