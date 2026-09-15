# Fresh evaluation log (Design D, locked)

One line per scored session, appended by `score-locked`; nothing here is edited by hand. Losses are session means of the
squared spot-normalized pricing error against the session's mids over the scored contracts (the plan's RV baseline plus the
three methods of Amendment 7). No inference is drawn until the sample rule in docs/LOCK.md is met: the first 60 available
sessions after the lock, or all sessions available by 2027-03-31, whichever comes first, with no interim stopping on results.

| Session | Prior session | Contracts predicted | Contracts scored | L_RV | L_B1 | L_M(RV) | L_M(B1) |
|---|---|---:|---:|---:|---:|---:|---:|
