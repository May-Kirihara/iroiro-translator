# xTranslator XML Translation NG Guide

For coding agents implementing translation support for xTranslator-style XML files used by Bethesda games.

Target games:

- The Elder Scrolls V: Skyrim / Skyrim Special Edition
- Fallout 4
- Starfield

This guide defines records and fields that should usually **not** be translated, records that should be translated, and ambiguous records that should be marked for human review.

---

## 1. Core Principle

Do not translate strings that are likely to be:

- internal identifiers
- editor-only names
- classification labels
- script / condition / AI / form-link reference names
- names used mainly by Creation Kit, xEdit, or mod tooling
- implementation details not intended for player-facing UI

Translate strings that are likely to be:

- player-facing names
- dialogue text
- quest text
- item names
- location names
- book / note / terminal / message text
- menu-facing descriptions

When in doubt, prefer **review-needed** instead of automatic translation.

---

## 2. Absolute NG: Never Translate

These should be excluded globally.

```text
EDID
```

### Why

`EDID` is the Editor ID / internal identifier.  
It is used by tools, scripts, references, and mod authors as a stable internal name.

Examples:

```text
BanditFaction
DLC03_co_Weapon_Template
MS01QuestMarker
mod_Weapon_PipeGun_Receiver_Auto
```

These are not player-facing strings.

### Implementation Rule

```pseudo
if field == "EDID":
    action = "skip"
    reason = "internal_editor_id"
```

---

## 3. Common Skip List

These record/field pairs are generally not worth translating and may be unsafe.

```text
FACT:FULL   Faction name
CLAS:FULL   Class name
RACE:FULL   Race name
MGEF:FULL   Magic Effect / Effect name
FURN:FULL   Furniture name
TREE:FULL   Tree name
DOOR:FULL   Door name
EXPL:FULL   Explosion name
HAZD:FULL   Hazard name
CLFM:FULL   Color Form name
HDPT:FULL   Head Part name
BPTD:BPTN   Body Part Data name
FLST:FULL   Form List name
KYWD:FULL   Keyword name
```

### Notes

#### `FACT:FULL`

Usually skip.

Faction names are often internal grouping names used for AI, relations, ownership, conditions, and membership logic.

Some faction names can appear in UI in specific mods, but automatic translation is usually not worth the risk.

Recommended action:

```text
FACT:FULL -> skip
```

#### `MGEF:FULL`

Usually skip.

Magic Effect names are often internal/effect-definition names.  
The player-facing text is more often found in spell names, perk names, descriptions, or effect descriptions.

Recommended action:

```text
MGEF:FULL -> skip
```

#### `KYWD:FULL`

Usually skip.

Keywords are commonly used for classification and condition matching.

Recommended action:

```text
KYWD:FULL -> skip
```

#### `DOOR:FULL`, `FURN:FULL`, `TREE:FULL`

Usually skip.

These often represent object definitions rather than meaningful player-facing labels.  
If a specific mod uses them visibly, mark for review rather than translating automatically.

---

## 4. Usually Safe Translation Targets

These are commonly player-facing and should normally be translation candidates.

```text
INFO:NAM1   Dialogue line text
INFO:NAM2   Additional dialogue text, if present
DIAL:FULL   Dialogue topic / prompt
BOOK:FULL   Book / note / holotape title
BOOK:DESC   Book / note / terminal body text
MESG:FULL   Message title, if present
MESG:DESC   Message body
QUST:FULL   Quest name
QUST:CNAM   Quest objective text
QUST:NNAM   Quest log / journal text
NPC_:FULL   NPC name
WEAP:FULL   Weapon name
ARMO:FULL   Armor / outfit / spacesuit name
AMMO:FULL   Ammo name
ALCH:FULL   Potion / aid / food / chem name
MISC:FULL   Misc item name
CELL:FULL   Cell / place name
LCTN:FULL   Location name
WRLD:FULL   Worldspace name
SPEL:FULL   Spell / power name
SPEL:DESC   Spell description
PERK:FULL   Perk name
PERK:DESC   Perk description
AVIF:FULL   Actor value name, if UI-facing
```

### Implementation Rule

These should be default translation candidates unless they match internal-name heuristics.

```pseudo
if record_field in safe_translation_targets:
    if looks_internal_name(text):
        action = "review-needed"
    else:
        action = "translate"
```

---

## 5. Review-Needed List

These records are not always safe.  
They may be player-facing in some games or mods, but internal in others.

```text
OMOD:FULL   Object Mod / weapon mod / armor mod name
COBJ:*      Constructible Object / recipe-related strings
PACK:FULL   AI Package name
SCEN:FULL   Scene name
GLOB:FULL   Global variable name
AVIF:FULL   Actor Value name
PERK:FULL   Perk name
PERK:DESC   Perk description
GMST:*      Game setting strings
LSCR:*      Loading screen text
TERM:*      Terminal-related strings
```

### `OMOD:FULL`

Important for Fallout 4 and Starfield.

Often player-facing:

```text
Standard Receiver
Hardened Receiver
Long Barrel
Reflex Sight
Suppressor
```

Often internal:

```text
mod_Weapon_PipeGun_Receiver_Auto_Template
DLC03_mod_Armor_Internal
co_Weapon_Template_Receiver
```

Recommended action:

```pseudo
if record_field == "OMOD:FULL":
    if looks_internal_name(text):
        action = "skip" or "review-needed"
    else:
        action = "translate"
```

### `COBJ`

Usually recipe / crafting related.  
May not contain direct player-facing text depending on exported XML structure.

Recommended action:

```text
COBJ:* -> review-needed
```

### `PERK`

Perk names and descriptions are player-facing in many cases.  
However, some perk records are invisible technical perks.

Recommended action:

```pseudo
if record == "PERK":
    if looks_internal_name(text):
        action = "review-needed"
    else:
        action = "translate"
```

---

## 6. Game-Specific Notes

## 6.1 Skyrim

Skyrim generally follows the classic Bethesda record layout.

Strong skip candidates:

```text
FACT:FULL
MGEF:FULL
RACE:FULL
CLAS:FULL
HDPT:FULL
FURN:FULL
TREE:FULL
DOOR:FULL
EXPL:FULL
HAZD:FULL
BPTD:BPTN
```

Strong translation candidates:

```text
INFO:NAM1
DIAL:FULL
BOOK:FULL
BOOK:DESC
MESG:DESC
QUST:FULL
QUST:CNAM
NPC_:FULL
WEAP:FULL
ARMO:FULL
ALCH:FULL
CELL:FULL
LCTN:FULL
WRLD:FULL
SPEL:FULL
SPEL:DESC
PERK:FULL
PERK:DESC
```

---

## 6.2 Fallout 4

Fallout 4 has many weapon mod, armor mod, workshop, and crafting records.

Keep the common skip list, especially:

```text
EDID
FACT:FULL
KYWD:FULL
RACE:FULL
CLAS:FULL
MGEF:FULL
```

Be careful with:

```text
OMOD:FULL
COBJ:*
AVIF:FULL
PERK:FULL
PERK:DESC
```

Common translation targets:

```text
WEAP:FULL
ARMO:FULL
AMMO:FULL
ALCH:FULL
MISC:FULL
BOOK:FULL
BOOK:DESC
MESG:DESC
INFO:NAM1
DIAL:FULL
QUST:FULL
QUST:CNAM
CELL:FULL
LCTN:FULL
```

### Fallout 4 OMOD Heuristic

Translate if it looks like a user-facing attachment name:

```text
Long Barrel
Short Scope
Reflex Sight
Calibrated Receiver
Large Magazine
```

Review or skip if it looks like an internal template:

```text
mod_*
co_*
DLC*_mod_*
*_Template
*_Internal
```

---

## 6.3 Starfield

Starfield has more player-facing module, research, crafting, outpost, and spaceship-related text.

Keep the common skip list:

```text
EDID
FACT:FULL
KYWD:FULL
RACE:FULL
CLAS:FULL
MGEF:FULL
FLST:FULL
```

But avoid excluding too many `FULL` records globally.  
Starfield uses many `FULL` fields for visible item, module, ship, outpost, and research names.

Common translation targets:

```text
WEAP:FULL
ARMO:FULL
AMMO:FULL
ALCH:FULL
MISC:FULL
BOOK:FULL
BOOK:DESC
MESG:DESC
INFO:NAM1
DIAL:FULL
QUST:FULL
QUST:CNAM
CELL:FULL
LCTN:FULL
PERK:FULL
PERK:DESC
```

Review-needed:

```text
OMOD:FULL
COBJ:*
research-related FULL fields
ship-module-related FULL fields
outpost-module-related FULL fields
crafting-module-related FULL fields
```

Recommended Starfield policy:

```text
Do not apply broad FULL-field exclusion.
Use record-specific allow/deny/review lists.
```

---

## 7. Internal-Name Heuristics

Use these heuristics to detect strings that are likely internal even if their field is normally translatable.

### Strong Internal Patterns

```regex
^[A-Za-z0-9_]+$
^DLC[0-9]+_
^cc[A-Za-z0-9]+_
^mod_
^co_
^MQ[0-9]+
^MS[0-9]+
^RE_
^Enc
^Lvl
_Template$
_Internal$
_Dummy$
_DEBUG$
_Test$
```

### Suspicious Features

Mark as review-needed if the string:

- contains many underscores
- uses camel-case with no spaces
- starts with `DLC`, `cc`, `mod`, `co`, `MQ`, `MS`, `RE`, `Enc`, `Lvl`
- ends with `Template`, `Internal`, `Dummy`, `Test`, `DEBUG`
- contains technical words such as `Marker`, `Activator`, `Trigger`, `Scene`, `Package`, `Sandbox`, `Furniture`
- looks like a form/editor label rather than a natural UI label

### Example

```pseudo
function looks_internal_name(text):
    if text contains "_":
        return true
    if text matches "^[A-Za-z0-9]+$" and hasCamelCase(text):
        return true
    if text startsWith any ["DLC", "cc", "mod_", "co_", "MQ", "MS", "RE_", "Enc", "Lvl"]:
        return true
    if text endsWith any ["Template", "Internal", "Dummy", "Test", "DEBUG"]:
        return true
    return false
```

---

## 8. Recommended Classification Model

Each extracted string should receive one of these actions:

```text
translate       Safe automatic translation candidate
skip            Do not translate
review-needed   Show to human reviewer / optional translation
```

### Suggested Decision Order

```pseudo
function classify(record, field, text, game):
    record_field = record + ":" + field

    if field == "EDID":
        return skip("internal_editor_id")

    if record_field in GLOBAL_SKIP_LIST:
        return skip("known_non_player_facing_field")

    if record_field in GAME_SPECIFIC_SKIP_LIST[game]:
        return skip("game_specific_skip_field")

    if record_field in REVIEW_LIST:
        if looks_internal_name(text):
            return skip_or_review("looks_internal")
        return review_needed("ambiguous_record_field")

    if record_field in TRANSLATE_LIST:
        if looks_internal_name(text):
            return review_needed("translatable_field_but_internal_name")
        return translate("known_player_facing_field")

    if looks_internal_name(text):
        return skip_or_review("unknown_field_internal_name")

    return review_needed("unknown_record_field")
```

---

## 9. Suggested Default Presets

## 9.1 Conservative Preset

Recommended for automatic batch translation.

```text
skip:
  - EDID
  - FACT:FULL
  - CLAS:FULL
  - RACE:FULL
  - MGEF:FULL
  - FURN:FULL
  - TREE:FULL
  - DOOR:FULL
  - EXPL:FULL
  - HAZD:FULL
  - CLFM:FULL
  - HDPT:FULL
  - BPTD:BPTN
  - FLST:FULL
  - KYWD:FULL

review-needed:
  - OMOD:FULL
  - COBJ:*
  - PACK:FULL
  - SCEN:FULL
  - GLOB:FULL
  - AVIF:FULL
  - GMST:*
```

## 9.2 Translation-Friendly Preset

Recommended when the user wants more complete UI localization.

```text
skip:
  - EDID
  - FACT:FULL
  - CLAS:FULL
  - RACE:FULL
  - KYWD:FULL
  - FLST:FULL

review-needed:
  - MGEF:FULL
  - FURN:FULL
  - DOOR:FULL
  - OMOD:FULL
  - COBJ:*
  - PACK:FULL
  - SCEN:FULL
  - GLOB:FULL
```

## 9.3 Starfield-Friendly Preset

Recommended for Starfield, where many module-related names may be visible.

```text
skip:
  - EDID
  - FACT:FULL
  - CLAS:FULL
  - RACE:FULL
  - KYWD:FULL
  - FLST:FULL

review-needed:
  - MGEF:FULL
  - OMOD:FULL
  - COBJ:*
  - ship-module-related FULL fields
  - outpost-module-related FULL fields
  - research-related FULL fields
```

---

## 10. Output Metadata Recommendation

For each skipped or reviewed string, store the reason.

Example JSON-like metadata:

```json
{
  "record": "FACT",
  "field": "FULL",
  "source": "BanditFaction",
  "action": "skip",
  "reason": "known_non_player_facing_field"
}
```

For review-needed:

```json
{
  "record": "OMOD",
  "field": "FULL",
  "source": "Hardened Receiver",
  "action": "review-needed",
  "reason": "ambiguous_record_field"
}
```

This makes debugging much easier when users ask why a string was not translated.

---

## 11. UI Recommendation

Expose three user-facing categories:

```text
翻訳する
翻訳しない
要確認
```

Suggested labels:

```text
Translate
Skip
Review Needed
```

For Japanese UI:

```text
翻訳候補
翻訳除外
要レビュー
```

Also expose preset names:

```text
Conservative
Translation-Friendly
Starfield-Friendly
```

Japanese names:

```text
安全重視
翻訳範囲広め
Starfield向け
```

---

## 12. Practical Summary

Use this as the default rule:

```text
EDID is never translated.

FACT:FULL, KYWD:FULL, RACE:FULL, CLAS:FULL, MGEF:FULL are generally skipped.

Dialogue, quest text, item names, book text, message text, and location names are translated.

OMOD, COBJ, PERK, AVIF, GMST, ship/outpost/research/crafting-related fields are review-needed unless known safe.

Starfield should not use broad FULL exclusion because many FULL fields are player-facing.
```

Most important traps:

```text
FACT:FULL  -> usually skip
MGEF:FULL  -> usually skip
KYWD:FULL  -> usually skip
EDID       -> always skip
OMOD:FULL  -> review-needed, especially in Fallout 4 and Starfield
```
