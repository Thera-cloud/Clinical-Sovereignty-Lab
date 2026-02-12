#!/bin/bash

# This will update the_eye.html navigation tabs to link to sub-pages
# We need to find the sub-nav items and add onclick handlers

echo "Updating the_eye.html navigation..."

# The tabs should be around line 33-40 based on your structure
# Let's find them and add onclick handlers

sed -i.bak '
    s|<div class="sub-nav-item active">.*Overview.*</div>|<div class="sub-nav-item active">📊 Overview</div>|;
    s|<div class="sub-nav-item">.*Coach Performance.*</div>|<div class="sub-nav-item" onclick="window.location.href='"'"'the_eye_coaches.html'"'"'">👨‍⚕️ Coach Performance</div>|;
    s|<div class="sub-nav-item">.*Token Economics.*</div>|<div class="sub-nav-item" onclick="window.location.href='"'"'the_eye_tokens.html'"'"'">💰 Token Economics</div>|;
    s|<div class="sub-nav-item">.*Live Monitor.*</div>|<div class="sub-nav-item" onclick="window.location.href='"'"'the_eye_monitor.html'"'"'">🔴 Live Monitor</div>|;
    s|<div class="sub-nav-iteed.*</div>|<div class="sub-nav-item" onclick="window.location.href='"'"'the_eye_crisis.html'"'"'">🚨 Crisis Feed</div>|;
    s|<div class="sub-nav-item">.*Community Health.*</div>|<div class="sub-nav-item" onclick="window.location.href='"'"'the_eye_community.html'"'"'">💚 Community Health</div>|;
' the_eye.html

echo "✅ Updated the_eye.html navigation"
