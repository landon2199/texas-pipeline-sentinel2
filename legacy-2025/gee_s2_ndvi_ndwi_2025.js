// =========================
// CONFIGURATION
// =========================
var LAYERS = [
  {name: 'DesertsEco', path: 'projects/research-476723/assets/hydrocarbon250m_deserts_eco', run: true},
  {name: 'PlainsEco', path: 'projects/research-476723/assets/hydrocarbon250m_plains_eco', run: true},
  {name: 'SemiAridPlainsEco', path: 'projects/research-476723/assets/hydrocarbon250m_semiaridplains_eco', run: false},
  {name: 'SemiAridPrairiesEco', path: 'projects/research-476723/assets/hydrocarbon250m_semiaridprairies_eco', run: false}
];

var START_DATE = '2025-03-01';
var END_DATE = '2025-05-01';
var S2_COLLECTION = 'COPERNICUS/S2_SR_HARMONIZED';
var PIPELINE_ECO_PROPERTY = 'PipelineEc'; // Source column
var CLEAN_PIPELINE_ECO_PROPERTY = 'PipelineEcoID'; // Desired column name
var SPATIAL_RESOLUTION = 10; // High accuracy
var CLOUD_FILTER_MAX = 60;

// =========================
// FUNCTIONS
// =========================

// Cloud masking using ESA SCL recommendations
function maskClouds(image) {
  var scl = image.select('SCL');
  var mask = scl.neq(3) // vegetation
    .and(scl.neq(8)) // clouds
    .and(scl.neq(9)) // cirrus
    .and(scl.neq(10)) // snow
    .and(scl.neq(11)); // water
  return image.updateMask(mask);
}

// Add NDVI and NDWI bands
function addIndices(image) {
  var ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI');
  var ndwi = image.normalizedDifference(['B3', 'B11']).rename('NDWI');
  return image.addBands(ndvi).addBands(ndwi);
}

// Process a single layer
function processLayer(layer) {
  print('Processing layer:', layer.name);

  var studyArea = ee.FeatureCollection(layer.path);
  var studyBounds = studyArea.geometry().bounds();

  var s2_collection = ee.ImageCollection(S2_COLLECTION)
    .filterBounds(studyBounds)
    .filterDate(START_DATE, END_DATE)
    .filter(ee.Filter.lt('CLOUD_COVERAGE_ASSESSMENT', CLOUD_FILTER_MAX))
    .map(maskClouds)
    .map(addIndices);

  var temporalMean = s2_collection.select(['NDVI', 'NDWI']).mean();

  var zonalStatistics = temporalMean.reduceRegions({
    collection: studyArea,
    reducer: ee.Reducer.mean(),
    scale: SPATIAL_RESOLUTION,
    crs: temporalMean.projection().crs()
  });

  // Keep underscores in PipelineEcoID
  zonalStatistics = zonalStatistics.map(function(feature) {
    var pipelineEco = ee.String(feature.get(PIPELINE_ECO_PROPERTY)).trim();
    return feature
      .set(CLEAN_PIPELINE_ECO_PROPERTY, pipelineEco)
      .select([CLEAN_PIPELINE_ECO_PROPERTY, 'NDVI', 'NDWI']);
  });

  // Export to Drive
  Export.table.toDrive({
    collection: zonalStatistics,
    description: layer.name + '_NDVI_NDWI_Cleaned',
    folder: 'GEE_Exports',
    fileNamePrefix: 'hydrocarbons_' + layer.name + '_Indices_Cleaned',
    fileFormat: 'CSV',
    selectors: [CLEAN_PIPELINE_ECO_PROPERTY, 'NDVI', 'NDWI']
  });
}

// =========================
// MAIN EXECUTION
// =========================
LAYERS.forEach(function(layer) {
  if (layer.run) {
    processLayer(layer);
  } else {
    print('Skipping layer:', layer.name);
  }
});
