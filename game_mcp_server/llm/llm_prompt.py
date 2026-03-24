motion_search_rewrite_prompt = """Please analyze the input action asset requirements and process the requirements into appropriate action description text:
1. Action Description Text Filtering
Retain: Significant body movements (limb movements, posture changes, tactile interactions)
Exclude: Micro-actions (breathing, blinking, trembling), facial expressions (smiling, anger, crying)
2. Action Description Text Types
(1) Idle Actions
Format: prefix modifier + idle or idle + present participle action (can include a tool/object)
Length: 1-5 words
Examples: breathing idle, zombie idle, idle holding gun, idle holding sword, ninja idle, rifle idle, drunk idle, sword and shield idle, ready idle, fight idle, idle aiming with gun, ...
(2) Controller Actions (walk/run/jump)
Format: prefix modifier + action or action + present participle modifier (can include direction/weapon) or action like a + simple persona
Length: 1-5 words
Examples: casual walk, zombie run, ninja walk, rifle run, drunk walk, sword and shield walk, walk aiming with gun, walk holding sword, walk scanning, walk backward, walk sideways, female walk, happy walk, happy run, happy jump, walk like a robot, run like a monkey
(3) Dance Actions
Format: dance style/type or specific move name or music-related keywords
Length: 1-8 words
Search Type: Dance style, popular trends, specific moves, BGM name, artist name, dance name
Examples: breakdance, kpop dance, tiktok trend, gangnam style, moonwalk, ballet，cute dance
(4) Other Actions
Format: A complete description beginning with "The person"
Active: "The person is [verb-ing] [object]"
Passive: "The person is being [verb-ed]"
Key Point: A highly generalized description, emphasizing the dominant action and overall intention of the movement."""
