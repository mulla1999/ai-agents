# Scheme batch 1, 23 November 2026: central schemes

Written to [scheme-authoring.md](scheme-authoring.md), with AI-assisted research. Every record has
`evidence` entries (claim, official URL, quote). 18 new records (plus Stand-Up India): 9 verified, 9 draft.
Catalogue now: **40 schemes, 29 verified** (`saathi coverage`).

## Records

| Record | Status | Why / what to check |
|---|---|---|
| `mgnrega` | verified | **MGNREGA was repealed on 1 July 2026 and replaced by the VB-G RAM G Act, 2025** (125 days a year). Big change: spot-check against the PIB backgrounder of 11 May 2026 and the gazette. States must notify their own schemes by about Jan 2027. |
| `e-shram` | verified | Age 16+, no upper limit. Farmers are included because the FAQ names small and landless farmers; check whether land-owning farmers qualify. |
| `pm-mudra` | verified | The occupation list in the rule is a mapping, not official wording. `mudra.org.in` has a broken certificate chain. |
| `pm-surya-ghar` | verified | Rules use the new `owns_house` and `has_electricity_connection` fields. Runs to 31 Mar 2027. |
| `pmfby` | verified | Tenants and sharecroppers are covered, so there is no land-ownership rule. Some quotes were read from PDF page images; check them word for word. |
| `pm-kusum` | verified | Extended to 31 Mar 2027. Guidelines PDF is hosted on `s3waas.gov.in`; a 28 Sep 2026 amendment may change details. |
| `nfsa-free-ration` | verified | AAY or PHH card. Free to end of 2028. A draft amendment bill (7 kg per AAY person) is noted but not applied. |
| `janani-suraksha-yojana` | verified | Uses the new `is_pregnant` field. Ladakh is left out of the Low Performing States (the list predates 2019). |
| `nfbs` | verified | Renamed Pradhan Mantri Parivar Labh Yojana (Oct 2026). Uses the new `main_earner_died` field. |
| `pm-jay` | draft | Coverage depends on being in the beneficiary list (SECC 2011 and state databases); the rules only say a family *may* be listed. |
| `kisan-credit-card` | draft | Interest subvention for 2026-27 not yet officially continued; Rs 5 lakh limit (Budget 2025-26) not yet in RBI circulars. |
| `pmegp` | draft | Extension beyond 2025-26 not officially approved; KVIC portal unreachable. |
| `stand-up-india` | draft | Cabinet continued it to 31 Mar 2031 (11 Nov 2026); new guidelines not issued. `archived/stand-up-india.yaml` is superseded. |
| `pm-internship` | draft | Still a pilot (Phase III); current age band and exclusions not officially confirmed for 2026. |
| `pre-matric-scholarship-sc`, `-st` | draft | Guidelines run to 2025-26; continuation for 2026-27 not confirmed. |
| `pm-yasasvi` | draft | Same guideline period; the profile cannot tell EBC or DNT students apart from other general-category students. |
| `nmmss` | draft | Class 7 vs class 8 marks condition conflicts between the 2022 guidelines and a 2026 notice; school type (government only) is in notes. |

## Profile changes

- New fields: `current_class` (0 = not in school), `is_pregnant`, `owns_house`, `has_electricity_connection`,
  `main_earner_died` (the last three are household facts shared with family members).
- People aged 21 or over who have not said they are in school are treated as not in school, so adults
  are not asked about school class and school scholarships are ruled out for them.

## Proposed but not added (conditions kept in notes)

School type, last exam percentage, highest qualification, full-time employment, a family member in a
permanent government job, DNT status, orphan status, keeps animals for income, ASHA/Anganwadi worker,
grid electricity for the farm pump, EPF/ESIC membership without NPS. Add them when a batch needs them.
