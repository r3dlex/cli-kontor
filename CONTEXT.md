# Kontor Mailbox

Domain language for kontor-cli, the autonomous email manager for the work
mailbox. The pipeline reads mail through himalaya (over DavMail), classifies
each email, and moves it to its place in the folder taxonomy. Decisions are
recorded; emails are never deleted (ADR-0001).

## Language

**Folder taxonomy**:
The closed set of valid mailbox folders defined in `folders.py`: 0_Action,
1_Management/MGT_*, 2_Projects/PRJ_*, 3_External/EXT_*, 4_Info, 9_System,
and the Archive mirror of each. `validate_folder` rejects anything outside
the set (`FolderInvariantError`).
_Avoid_: folder structure, directory layout

**Classification**:
The answer to "which taxonomy folder does this email belong in", produced by
the rules engine first (YAML DSL, then Python rules) and the LLM second (with
NL rules as prompt context). A classification may be None when nothing
matches.
_Avoid_: categorization, labeling, sorting

**Folder policy**:
The single folder decision in `folders.py` (`FolderPolicy.target_for`): given
an email's date and its classification, return the final target folder. Owns
the taxonomy default (unclassified emails land in 4_Info and are never
archive-enforced) and archive enforcement. All three pipeline phases and the
classify command go through this one call.
_Avoid_: target resolver, folder logic, archive helper

**Archive enforcement**:
The age-based arm of the folder policy: a classified email older than
`archive_age_months` (default 6) is redirected to its Archive mirror path
(`2_Projects/PRJ_X` becomes `Archive/2_Projects/PRJ_X`). Enforcement moves
mail; it never deletes (ADR-0001).
_Avoid_: retention, expiry, cleanup

**Phase**:
One of the three pipeline runs in `pipeline.py`. Rebuild classifies the whole
scan scope from scratch. Realtime processes new INBOX mail. Heal detects
emails sitting in the wrong folder (policy violations) and re-processes them.
_Avoid_: mode, stage, job

**Rule evolution**:
The LLM-proposed adjustments to classification rules, logged to
`rules/evolved/` and guarded by freeze snapshots and dry runs (ADR-0003).
Evolved rules never overwrite the hand-written rule sources.
_Avoid_: rule learning, auto-tuning

## Example dialogue

Dev: An old newsletter ended up in 4_Info instead of Archive/4_Info. Bug?

Domain expert: Only if it had a classification. The folder policy pins that
unclassified emails land in 4_Info and are never archive-enforced. If a rule
or the LLM classified it as 4_Info and it is older than six months, archive
enforcement applies and heal will move it on the next run.

Dev: Can heal just delete obvious spam while it is at it?

Domain expert: No. ADR-0001: emails are only ever moved. Give spam a
taxonomy target instead and let the folder policy place it.
