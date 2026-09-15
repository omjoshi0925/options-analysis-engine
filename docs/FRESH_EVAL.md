# Fresh evaluation log (Design D, locked)

Sample rule status (2026-09-15): 0 of 60 sessions scored; no inference before the rule is met. XNYS holds 135 sessions from 2026-09-16 to 2027-03-31. At the source's whole-span rate of 0.64 sessions per XNYS session (1,177 of 1,841 over 2019-05-10 to 2026-09-04), the 60th session is expected around 2027-01-29 and about 86 sessions by the cutoff; at the rate of the last twelve months (0.99, 249 of 252), around 2026-12-10 and about 133. Sixty sessions become unreachable by the cutoff at 0.64 per session if none has been scored by 2026-11-12, and in that case the 2027-03-31 cutoff governs with whatever count has arrived (60 needs a rate of at least 0.44). This line is updated by hand; the table below is written only by `score-locked`.

One line per scored session, appended by `score-locked`; nothing here is edited by hand. Losses are session means of the
squared spot-normalized pricing error against the session's mids over the scored contracts (the plan's RV baseline plus the
three methods of Amendment 7). No inference is drawn until the sample rule in docs/LOCK.md is met: the first 60 available
sessions after the lock, or all sessions available by 2027-03-31, whichever comes first, with no interim stopping on results.

| Session | Prior session | Contracts predicted | Contracts scored | L_RV | L_B1 | L_M(RV) | L_M(B1) |
|---|---|---:|---:|---:|---:|---:|---:|
