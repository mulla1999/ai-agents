# Scheme verification, November 2026

Every scheme record in `backend/data/schemes/` was checked on **2026-11-20** against official
government sources (ministry and department sites, scheme guidelines and rules, PIB releases, Cabinet
decisions, gazette notifications, state government orders). Each eligibility rule, amount, document,
note and link was compared with the source. News sites and aggregators were used only to find official
pages, never as evidence.

The check was AI-assisted research (Claude) at the maintainer's request. `verified_on: 2026-11-20` in a
file means every fact in it was matched to an official source on that date. Admins should still
spot-check before a public launch, and re-verify on the dates below.

**Result:** 20 of 22 schemes verified. 2 stay drafts. **No record was fully correct as first written**;
only Sukanya Samriddhi had no factual errors. All corrections are applied in the YAML files.

## Changes to the profile model

- **New personal field `has_paid_income_tax`.** The existing `is_income_tax_payer` means "anyone in the
  family", which is right for PM-KISAN and PMAY-G. APY, PM-SYM and PM-KMY exclude only the applicant:
  PFRDA's APY FAQ says a taxpayer's spouse who has never paid income tax can join. Those three schemes
  now use the personal field, which family members also have.
- **`applies_to: household`** added for PM-KMY (the farmer's own land) and PM Vishwakarma (one member per
  family).

## Per scheme

| Scheme | Status | Main corrections | Official source |
|---|---|---|---|
| Atal Pension Yojana | verified | Tax bar uses the personal field ("is or has been" a taxpayer); spouse of a taxpayer can join; closure only for tax status on or before applying; mobile optional; eAPY | pfrda.org.in APY page and FAQ; Gazette 10.08.2022 |
| PMJJBY | verified | 30-day exclusion is for death other than by accident; renewal to 55, entry to 50 | jansuraksha.gov.in PMJJBY Rules (1.6.2022); PIB 9 May 2026 |
| PMSBY | verified | Age is now **under 70** (cover ends at 70); benefit wording follows the rules | jansuraksha.gov.in PMSBY Rules (1.6.2022) |
| Sukanya Samriddhi | verified | Withdrawal and marriage-closure wording made precise | SSA Scheme 2019 (G.S.R. 914(E)); nsiindia.gov.in |
| PM-SYM | verified | Personal tax field; farmers allowed; documents; enrol via e-Shram; still open in 2026 | maandhan.in FAQ; PIB 7 Aug 2025; e-Shram backgrounder 25 Aug 2026 |
| PM-KMY | verified | **Government-employee rule removed** (Group D/Class IV/MTS are eligible); land in own name as on 1 Aug 2019; not with PM-SYM/PM-LVM; apply via CSC or State Nodal Officer (the old apply link was 404) | PIB PRID 2309204 (11 Sep 2026); pmkmy.gov.in FAQ |
| PM-KISAN | verified | Full exclusion list (PSU/local-body staff, mayors, MLCs, NRIs); Farmer ID wording | Revised Operational Guidelines; PIB 5 Aug 2025 |
| PMAY-G | verified | **Exclusion list replaced with the 2024 revision** (two-wheelers, boats, fridges no longer exclude; professional tax and land thresholds added); Awaas+ survey closed | PIB PRID 2080091 (3 Dec 2024), PRID 2117394 |
| PM SVANidhi | verified | Loan amounts Rs 15,000 / 25,000 / 50,000, lending to 31 Mar 2030; RuPay card; UPI ID required | Scheme Guidelines; Cabinet release Aug 2025 |
| PM Ujjwala | verified | **Removed a rule that wrongly rejected poor OBC/general women**: eligibility is by deprivation declaration; refill subsidy Rs 300 for up to 4 refills in 2026-27 | pmuy.gov.in (Ujjwala 2.0, FAQ); Lok Sabha USQ 3151 (6 Aug 2026) |
| PMMVY | verified | Mother's age 18 to 55 added; instalment split; exclusion for similar benefits; registration up to 270 days after birth | wcd.gov.in scheme page and FAQ; PMMVY Rules 2022; PIB 19 Mar 2025 |
| Post-matric scholarship (SC) | verified | Income limit Rs 2.5 lakh confirmed (Aug 2026); the Rs 4.5 lakh rise is only proposed | PIB PRID 2298357 (12 Aug 2026); SC guidelines |
| Post-matric scholarship (ST) | verified | Allowance Rs 230 to 1,200 a month; Top Class exclusion; documents | PIB PRID 2295355 (6 Aug 2026); ST guidelines |
| Ayushman Vay Vandana (70+) | verified | Private insurance/ESIS holders also eligible; document list trimmed to what is confirmed | PIB PRID 2053883 (Cabinet, 11 Sep 2024), 2110780 |
| PM Vridhavastha Pension (formerly IGNOAPS) | verified | **Renamed by Cabinet, 14 Oct 2026**; BPL-list note | NSAP Guidelines 2014; PIB PRID 2323264 |
| PM Vidhawa Pension (formerly IGNWPS) | verified | Renamed (as above) | NSAP Guidelines 2014; PIB PRID 2323264 |
| PM Divyangjan Pension (formerly IGNDPS) | verified | **Upper age limit removed** (Rs 500 from age 80); renamed; approved 40%/no-minimum-age revision noted | NSAP Guidelines 2014; PIB PRID 2323264 |
| UP old age pension | verified | **BPL households added as a route**; Aadhaar no longer accepted as age proof (GO 391, Mar 2026); application flow | samajkalyan.up.gov.in; SSPY scheme note; GO 391 |
| UP Divyang pension | verified | Certificate from "competent medical authority"; residence and government-home exclusions | uphwd.gov.in |
| UP Kanya Sumangala | verified | **Age rule replaced with the six official stage age bands** (order of 26 Dec 2025); stage amounts; payment to the mother's account; family photo no longer required; family may have at most two children | mksy.up.gov.in and its government orders |
| PM Vishwakarma | **draft** | Fully repaid Mudra/SVANidhi loans do not disqualify; one per family | pmvishwakarma.gov.in guidelines. **Unconfirmed:** whether new registrations are open since the target was reached (Sept 2025) |
| UP widow pension | **draft** | Department is Women Welfare (not WCD); documents; residence | UP widow pension guidelines (2017). **Unconfirmed:** no official text states the current Rs 1,000 rate (only the official payout dashboard implies it) |

## Known gaps in matching (documented in each scheme's notes)

- `is_government_employee` also covers retired employees and pensioners; PMMVY and PMAY-G exclude only
  serving staff, PM Vishwakarma only "government service".
- PM-KMY needs land in the farmer's own name; the profile records family land.
- Kanya Sumangala's final stage: at 16-17 only a diploma counts, not class 11-12.
- PMMVY's age limit is at childbirth; the profile has the current age in whole years.

## Recheck

| When | What |
|---|---|
| **January 2027** | Disability pension: once revised NSAP guidelines are issued, change to 40% disability, no minimum age, Rs 375 (Rs 625 from 80) |
| January 2027 | UP pensions: a rise to Rs 1,500 a month is reported as approved in principle; apply only when a government order is issued |
| April 2027 (new financial year) | Ujjwala refill subsidy and number of refills; post-matric SC income limit (Rs 4.5 lakh proposal) |
| Every 6 months | All other schemes |

## Site problems found

`sspy-up.gov.in` has an expired TLS certificate (since 25 Mar 2026), and `pmkmy.gov.in` presents a
certificate for another host; browsers show a warning on both. `pmkisan.gov.in`, `jansuraksha.gov.in`,
`nsiindia.gov.in`, `wcd.gov.in` and `tribal.nic.in` send incomplete certificate chains (browsers usually
cope, automated checkers fail). Linked pages were chosen to avoid these where an alternative existed.

## Applying the corrections to an existing database

`saathi seed` never overwrites records, so a database seeded before this check still has the old data:

```bash
saathi sync-schemes            # dry run: lists what would change
# back up the database, then:
saathi sync-schemes --apply    # updates like an admin edit: version + 1, revision kept
```

Archived schemes are skipped. With 20 schemes verified, `SAATHI_INCLUDE_DRAFT_SCHEMES=false` now hides
only PM Vishwakarma and the UP widow pension.
