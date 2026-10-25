# Task 002C-R2 projection convergence correction

## Verdict

The third Darwin return is valid 500-nt resource evidence. It is not an MMseqs2,
schema, or scientific failure. Two planning projections stopped the run:

- conservative full-search time: 12.51 hours versus the 12-hour threshold;
- conservative transient disk: 1,435.16 GiB versus the 20-GiB threshold.

The time result is a genuine, narrow planning exceedance. The disk result is
not job-attributable: the old formula scaled a 26.49-GiB change in free space
across a shared 45-TiB filesystem. The probe's own candidate generation peaked
at 0.828 GiB.

## Bounded correction

1. Preserve the frozen sample, widths, thresholds, MMseqs2 flags, thread count,
   safety factor, and all hard resource floors.
2. Continue to stop immediately on a tool failure, timeout, OOM/cannot-fit,
   malformed or foreign result, lost self-hit, result cap, unavailable live
   measurement, live RAM/disk/swap violation, or output-ceiling violation.
3. Treat projected time/RSS/retained/transient exceedances and block-density
   heterogeneity as planning findings. Record the width as `REVIEW_REQUIRED`,
   complete the remaining safe probe widths, and return one consolidated stop.
4. Project transient disk from the peak size of the job-owned candidate
   generation. Retain shared-filesystem free-space movement as diagnostic and
   absolute-floor evidence only; never scale it as job output.
5. Keep R3 blocked after any projection finding until planning review.

This changes orchestration and attribution, not the biological relation.

## Why this is necessary

Stopping at the first projection-only finding forces repeated 14-minute runs
to reveal one width at a time, even though the small probe remains within all
live safety limits. It also makes shared-storage activity look like this job's
output. The correction yields one complete evidence package without tolerating
unsafe execution or weakening scientific parameters.

## Regression proof

The focused tests verify that:

- projection findings retain accepted per-width records and all three safe
  widths execute before one consolidated `REVIEW_REQUIRED` stop;
- a shared-filesystem free-space change is recorded but not job-attributed;
- job-owned candidate growth still drives the transient projection;
- projected RSS and block-density findings are accumulated;
- hard failures continue to stop immediately; and
- return packaging still reports a non-success outcome and cannot authorize R3.

## Real-evidence interpretation

For 500 nt, the probe observed 61,821 result rows from 10,000 queries, 100%
self-hits, no result-cap saturation, stable ten-block density, 9.30-GiB peak
RSS, and only about 0.23 GiB conservative retained output. The 8.34-hour linear
and 12.51-hour conservative search projections warrant review, but do not make
the already-completed small probe unsafe.

