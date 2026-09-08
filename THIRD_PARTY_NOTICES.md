# License notices

The retained license in LICENSE.txt applies to the adapted calculator lineage.
The four inherited formula image assets have been removed from this version.
The collection service, observation database, and learned volatility model were
added specifically for Options Analysis Engine. Dependency licenses remain with
their respective packages.

## Market data in docs/results/

The files `docs/results/*/observations-with-exclusions.csv.gz` are derived
from the public DoltHub databases `post-no-preference/options` (head commit
66gs0ag3jlqu4ckm6vlgq1kgp511vqk3 at export) and `post-no-preference/stocks`
(head commit rf9dcnjl1ouulr92j9u3d38nr4lnpvi4), both published under the
Creative Commons Attribution-ShareAlike 4.0 International license
(https://creativecommons.org/licenses/by-sa/4.0/). Those derived data files,
and the fold tables computed from them, are provided under the same CC BY-SA
4.0 terms; the MIT license above covers the code, not this data. The
databases' own license text is stored in their `dolt_docs` table.
