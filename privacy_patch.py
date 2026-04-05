#!/usr/bin/env python3
"""Patch privacy policy to add xAI (Grok) as a named AI processor."""

with open("/var/www/sovereignsanctuary-web/privacy.html", "r") as f:
    content = f.read()

# 1. Update section 13 header to mention both providers
content = content.replace(
    "Data is processed via Azure OpenAI (Microsoft) under enterprise data protection agreements — your data is NOT used to train OpenAI's general models.",
    "Data is processed via <strong>xAI (Grok)</strong> and <strong>Microsoft Azure OpenAI</strong> under enterprise-grade data protection agreements — your data is NOT used to train any third-party AI models."
)

# 2. Update 13a intro
content = content.replace(
    "Sovereign Sanctuary uses <strong>Microsoft Azure OpenAI Service</strong> as a third-party AI provider. The following data is transmitted to this service during your use of the AI companion (Little Nate):",
    "Sovereign Sanctuary uses <strong>xAI (Grok)</strong> as the primary AI inference provider and <strong>Microsoft Azure OpenAI Service</strong> as a secondary/fallback provider. The following data is transmitted to these services during your use of the AI companion (Little Nate):"
)

# 3. Update text messages bullet
content = content.replace(
    "Your typed or voice-transcribed messages are sent to Azure OpenAI to generate Little Nate's conversational responses.",
    "Your typed or voice-transcribed messages are sent to xAI (Grok) or Azure OpenAI to generate Little Nate's conversational responses."
)

# 4. Update protections header
content = content.replace(
    "<p><strong>Protections provided by Microsoft Azure OpenAI:</strong></p>",
    "<p><strong>Protections provided by our AI service providers:</strong></p>"
)

# 5. Update specific protection bullets
old_bullets = """<li>Your data is NOT used to train, retrain, or improve Azure OpenAI foundation models</li>
                    <li>Your prompts and completions are NOT available to other customers or to OpenAI</li>
                    <li>Data is processed within Microsoft Azure's SOC 2 Type II and ISO 27001 certified infrastructure</li>
                    <li>Enterprise-level data processing agreements (DPA) are in place</li>"""

new_bullets = """<li>Your data is NOT used to train, retrain, or improve any third-party AI models (neither xAI's nor Microsoft's)</li>
                    <li>Your prompts and completions are NOT available to other customers, to xAI, or to OpenAI</li>
                    <li><strong>xAI (Grok):</strong> Processes text messages for real-time AI responses. xAI does not retain your data after processing.</li>
                    <li><strong>Microsoft Azure OpenAI:</strong> Data is processed within SOC 2 Type II and ISO 27001 certified infrastructure</li>
                    <li>Enterprise-level data processing agreements (DPA) are in place with both providers</li>"""

content = content.replace(old_bullets, new_bullets)

# 6. Update enterprise agreements in storage section
content = content.replace(
    "We use Microsoft Azure OpenAI under enterprise data protection terms that prohibit use of your data for model training.",
    "We use xAI (Grok) and Microsoft Azure OpenAI under enterprise data protection terms that prohibit use of your data for model training."
)

# 7. Update data sharing section
content = content.replace(
    "shared only with: <strong>Microsoft Azure OpenAI</strong> (conversation text for AI response generation",
    "shared only with: <strong>xAI (Grok)</strong> and <strong>Microsoft Azure OpenAI</strong> (conversation text for AI response generation"
)

with open("/var/www/sovereignsanctuary-web/privacy.html", "w") as f:
    f.write(content)

print("Privacy policy updated — xAI (Grok) added as named AI processor")
