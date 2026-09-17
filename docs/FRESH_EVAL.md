# Fresh evaluation log (Design D, locked)

Sample rule status (2026-09-17): 1 of 60 sessions scored (2026-09-16); no inference before the rule is met. XNYS holds 135 sessions from 2026-09-16 to 2027-03-31. At roughly 0.64 source sessions per weekday (the whole-span rate, 1,177 of 1,841 XNYS sessions) about 86 sessions are expected by the 2027-03-31 cutoff and the 60th around 2027-01-29, so the 60-session limb is expected to close the sample first; at the last twelve months' rate (0.99) about 133 and the 60th around 2026-12-10. Sixty become unreachable by the cutoff at 0.64 per session only if fewer than 60 minus 0.64 times the sessions remaining have arrived. This line is updated by hand; the table below is written only by `score-locked`.

One line per scored session, appended by `score-locked`; nothing here is edited by hand. Losses are session means of the
squared spot-normalized pricing error against the session's mids over the scored contracts (the plan's RV baseline plus the
three methods of Amendment 7). No inference is drawn until the sample rule in docs/LOCK.md is met: the first 60 available
sessions after the lock, or all sessions available by 2027-03-31, whichever comes first, with no interim stopping on results.

| Session | Prior session | Contracts predicted | Contracts scored | L_RV | L_B1 | L_M(RV) | L_M(B1) |
|---|---|---:|---:|---:|---:|---:|---:|
| 2026-09-16 | 2026-09-04 | 281 | 47 | 3.028e-05 | 1.646e-05 | 5.821e-06 | 1.111e-05 |
