# Adding a scheme

How to write a scheme record so that it is correct, checkable, and safe for the agent to use. Every
new record, by a person or an AI assistant, follows this.

## Where it goes

- Central: `backend/data/schemes/central/<id>.yaml`
- State or UT: `backend/data/schemes/states/<state-folder>/<id>.yaml`, with `level: state` and
  `state:` set to the key from `INDIAN_STATES` in `backend/src/saathi/profile.py` (e.g. `tamil_nadu`).
- District-targeted: a state scheme with a rule `{field: district, op: in, value: [...]}`. District
  names are lowercase.
- `id`: lowercase words joined by `-`, unique across all files. Prefix state schemes with the state
  code where the name is generic (`up-old-age-pension`, `tn-...`).

Copy the shape of an existing verified record, e.g. `central/pm-ujjwala.yaml` or
`states/uttar-pradesh/up-old-age-pension.yaml`.

## Sources

Use only **official** sources as evidence: ministry, department and state government sites (`.gov.in`,
`.nic.in`), scheme guidelines and rules, gazette notifications, government orders, PIB releases,
Cabinet decisions, Lok Sabha or Rajya Sabha answers. News sites, myScheme copies, Wikipedia and
aggregators may help you *find* an official page but are never evidence.

Do **not** scrape or copy from myScheme (its terms forbid it).

Look for the **current** rules: check for revisions, renamings and closures, and prefer the newest
official document. If official sources disagree, follow the gazetted rules or the latest government
order, and say so in `notes`.

## Fields

| Field | Rule |
|---|---|
| `summary`, `benefits` | Plain, short English. Exact amounts only when an official source gives them; otherwise describe without numbers. |
| `eligibility` | Only conditions that profile fields can check. Every rule has a `reason` a citizen understands. Use `any` / `all` groups for "one of" and "both". **Never guess a rule**: if a condition cannot be expressed with existing fields, put it in `notes` and flag it in your report as a possible new profile field. |
| `applies_to` | `household` when there is one benefit per family or the condition is about the applicant's own land, business or similar; otherwise `person`. |
| `documents` | What the official source lists. |
| `notes` | Conditions the rules cannot check, exclusions, one-per-family limits, cut-off dates, known approximations ("the rule here cannot tell ... apart"). |
| `how_to_apply`, `apply_url` | Official channels only. Check that the URL loads. |
| `source_url` | The most specific official page or document for the scheme (not a portal home page). |
| `evidence` | One entry per eligibility rule, per amount, and per important note: `claim`, official `url`, short exact `quote`, `checked_on`. |
| `verified_on` | The date, **only** if every rule and amount is backed by an `evidence` entry from an official source. Otherwise `null`, and say what could not be confirmed. |

YAML: quote any value that contains `: ` or, inside `{...}`, a comma (`reason: "Up to Rs 46,080"`).

## Check before committing

```bash
saathi validate      # schema and rule fields
saathi coverage      # counts, drafts, missing evidence
pytest apps/saathi/backend
```

Then open the scheme in Admin → Schemes on a staging copy, and try a matching profile.

## Re-verifying

`saathi coverage` lists records verified more than six months ago. Re-check them the same way, update
`evidence` and `verified_on`, and apply to existing databases with `saathi sync-schemes --apply`.
