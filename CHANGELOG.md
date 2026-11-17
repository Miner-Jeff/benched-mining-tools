# Changelog

Experimental software, provided without warranty (GPL-2.0-or-later). Use at your own risk.

## 2.8.1
* Repository, tracker and homepage links added to the plugin metadata.

## 2.8.0
* Roads are built **bottom up** by default: the spiral starts at the pit floor (or dump base) and climbs. New "Spiral build order" option (bottom up / top down). Digitized roads default to "ascends from the first vertex".
* Spiral direction now states which way loaded trucks climb (clockwise by default).
* The log reports the road's impact on cut/fill volume, on the pit floor / dump crest area, and the area reshaped by the road works. Returned volumes include the road.

## 2.7.0
* Bench crest and toe **strings at constant elevation**, traced from the finished surface so they are adjusted around the ramp.
* The log notes where the road meets the lowest (or top) string; equipment access there is edited by hand.

## 2.6.0
* The modified DEM output is optional and off by default. Main outputs are contours, bench strings and road designs.

## 2.5.2
* Contact email removed from the plugin metadata.

## 2.5.1
* GPL-2.0-or-later licence, use-at-your-own-risk disclaimers, bug-report template and support policy (no guarantee of replies or fixes).

## 2.5.0
* Validation checks (warnings only): outline validity and overlap, inter-ramp and overall slope, face angle, last bench, floor size, contour interval, road self-intersection, overlap, connection and sight distance.

## 2.4.0
* Automatic spiral haul road for pits and dumps; drawing outputs (bench lines, road centreline/edge lines, road polygons).

## 2.3.0
* Pit roads are cut-only: no fill above the original ground; the ramp is left as unexcavated rock.

## 2.2.0
* Road landing, turning-radius-based minimum radius, and inside-edge gradient check.

## 2.1.0
* Haul road design for both tools, based on the Deswik open-pit design guidance.

## 2.0.x
* Processing plugin with the open pit and waste rock pile tools, 1 m grid, UTM handling, contours and volume report.
