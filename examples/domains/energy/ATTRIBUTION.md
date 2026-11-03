# Attribution: home energy data

I use the dataset "Appliances Energy Prediction" from the UCI Machine
Learning Repository, created by Luis Candanedo and donated on 2017-02-14.

- DOI: https://doi.org/10.24432/C5VC8G
- Page: https://archive.ics.uci.edu/dataset/374/appliances+energy+prediction
- License: Creative Commons Attribution 4.0 International (CC BY 4.0,
  https://creativecommons.org/licenses/by/4.0/)

Recommended citation: Candanedo, L. (2017). Appliances Energy Prediction
[Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C5VC8G.

Introductory paper: L. Candanedo, V. Feldheim, D. Deramaix (2017), "Data
driven prediction models of energy use of appliances in a low-energy
house", Energy and Buildings, volume 140.

The energy data was logged every 10 minutes for about 4.5 months in one
house; the dataset page names the nearest weather station as Chievres
Airport, Belgium. `Appliances` is the appliances' energy use in Wh and
`lights` the light fixtures' energy use in Wh, per logged interval.

I downloaded the data on 2026-11-03 from
https://archive.ics.uci.edu/static/public/374/appliances+energy+prediction.zip
(zip sha256
`2fccf354445d886e7917620b0195db1f3e3e34d5a067a93b844694a4c561255a`),
which holds `energydata_complete.csv` (sha256
`2820bf712ad0275cb18b85a05250926100d8e65ebb9f4d2d016ca91ea152a25d`,
19,736 lines).

Change: I kept its first three columns with
`cut -d, -f1-3 energydata_complete.csv > energydata_extract.csv`
(date, Appliances, lights), values unchanged, giving the extract's sha256
`879d806a06bfcba3e3fa38d86112030d4033b74d3d4e487745329dbb4b9a8b40`;
anyone can rerun that line on the original file and compare.

This pack counts intervals and never states Wh, because my checker's
units do not include Wh; it is historical public data used to test my
checker, not a deployment and not a user.
