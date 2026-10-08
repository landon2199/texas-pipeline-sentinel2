// GEOG 392 Group 10: look at the pipeline zones and the spring imagery in the Earth Engine Code Editor.
//
// 1. Open https://code.earthengine.google.com and pick the Cloud project research-476723 (top right).
// 2. Paste this whole script into a new script and press Run.
// 3. Turn layers on and off in the Layers box (top right of the map). With the Inspector tab, click a zone
//    to see its zone_id: <segment_id>_r<inner>-<outer>, for example 307-000061-27-0-0_r0-50.
//
// Viewing uses a little of the project's monthly compute (online requests count); it starts no batch tasks.

var ROOT = 'projects/research-476723/assets/geog392/';

// The Central Great Plains as Part 2 uses it: the EPA Level III ecoregion, clipped to Texas.
var texas = ee.FeatureCollection('TIGER/2018/States').filter(ee.Filter.eq('NAME', 'Texas')).geometry();
var region = ee.FeatureCollection('EPA/Ecoregions/2013/L3')
  .filter(ee.Filter.eq('us_l3name', 'Central Great Plains'))
  .geometry().intersection(texas, 100);

// Each uploaded zone file is a folder of pieces (part_0000, part_0001, ...). Join the pieces into one collection.
function zones(folder) {
  var parts = ee.data.listAssets(ROOT + folder).assets.map(function (a) {
    return ee.FeatureCollection(a.name);
  });
  return ee.FeatureCollection(parts).flatten();
}
var rings = zones('zones_27_rings');               // 89,290 zones: 5 rings for each of 17,858 measured segments
var spills = zones('zones_27_spills');             // 4,584 zones around 14 spills and their comparison spots
var clean = zones('zones_27_sample200_clean');     // 974 clean rings of the 200-segment test (Oct 6)

// Spring 2025 Sentinel-2 with the masks Part 2 uses: Cloud Score+ (cs_cdf of 0.6 or more is kept) and scene
// classes 1 (saturated), 2 (dark) and 11 (snow).
var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(region)
  .filterDate('2025-03-01', '2025-05-01')
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 60))
  .linkCollection(ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'), ['cs_cdf'])
  .map(function (img) {
    var scl = img.select('SCL');
    var clear = img.select('cs_cdf').gte(0.6).and(scl.neq(1)).and(scl.neq(2)).and(scl.neq(11));
    return img.select(['B2', 'B3', 'B4', 'B8']).divide(10000).updateMask(clear);
  });
var spring = s2.median().clip(region);
var ndvi = spring.normalizedDifference(['B8', 'B4']).rename('NDVI');

Map.centerObject(region, 8);
Map.setOptions('HYBRID');
Map.addLayer(spring, {bands: ['B4', 'B3', 'B2'], min: 0.02, max: 0.25}, 'Spring 2025 Sentinel-2, true color (median)', false);
Map.addLayer(ndvi, {min: 0, max: 0.6, palette: ['a6611a', 'dfc27d', 'f5f5f5', '80cdc1', '018571']},
             'Spring 2025 NDVI (median)', false);
Map.addLayer(ee.Image().byte().paint(ee.FeatureCollection([ee.Feature(region)]), 1, 2), {palette: ['ffff00']},
             'Central Great Plains (Texas part)');

// The five rings of every measured 1 km segment, one layer per distance band (only 0-50 m is on at first).
var BANDS = [['0-50', 'd7191c'], ['50-100', 'fdae61'], ['100-250', 'ffffbf'], ['250-500', 'abd9e9'], ['500-1000', '2c7bb6']];
BANDS.forEach(function (b) {
  var band = rings.filter(ee.Filter.stringEndsWith('zone_id', '_r' + b[0]));
  Map.addLayer(band.style({color: b[1], fillColor: b[1] + '66', width: 0}), {}, 'Rings ' + b[0] + ' m', b[0] === '0-50');
});

// The clean test rings: ground closer to some other pipeline than the ring's inner edge is cut out.
Map.addLayer(clean.style({color: '000000', fillColor: 'ffffff00', width: 1}), {}, 'Clean rings, 200-segment test', false);

// Spill sites, their comparison spots along the same line, and regional spots on similar lines.
Map.addLayer(spills.style({color: 'ff00ff', fillColor: 'ff00ff44', width: 1}), {}, 'Spill zones');

print('Ring zones:', rings.size());
print('Spill zones:', spills.size());
print('Clean test zones:', clean.size());
print('Sentinel-2 images, spring 2025, under 60% cloud:', s2.size());
