# Import system modules
import arcpy
import os
import sys

# Main function, all functions run in GravityModel
def WeightedCentralityScore(in_dest, attr_field, out_fc, num_neighbors):
    # Make sure ArcInfo license is available
    if arcpy.ProductInfo().lower() not in ['arcinfo']:
        arcpy.AddError("Tool requires an ArcInfo license.")
        sys.exit()

    # Set geoprocessing environments
    arcpy.env.overwriteOutput = True
    arcpy.env.qualifiedFieldNames = False

    dest_desc = arcpy.Describe(in_dest)
    fieldmappings = MakeFieldMappings(in_dest, dest_desc.OIDFieldName)
    arcpy.FeatureClassToFeatureClass_conversion(in_dest, os.path.dirname(out_fc), os.path.basename(out_fc), "", fieldmappings)
    arcpy.AddField_management(out_fc, "INTERACTION_INDEX", "DOUBLE", "", "", "", "Weighted Spatial Interaction Index")
        
    # Calculate sum of distances to all other features
    nearmatrix = arcpy.analysis.GenerateNearTable(in_dest, in_dest, r"memory/gravity_near_table", "", "", "", False, num_neighbors, "GEODESIC")
    sumdistances = arcpy.analysis.Statistics(nearmatrix, "in_memory/sumdistances", [["NEAR_DIST", "SUM"]], "IN_FID")
    arcpy.AlterField_management(sumdistances, "SUM_NEAR_DIST", "SUM_DIST", "Sum of Distances")
    arcpy.JoinField_management(out_fc, "IN_FID", sumdistances, "in_FID", "SUM_DIST")
    
    # Calculate distance to weighted mean center
    weighted_center = arcpy.MeanCenter_stats(in_dest, "in_memory/MeanCenterGravity", attr_field)
    arcpy.Near_analysis(out_fc, weighted_center, None, None, None, "GEODESIC")
    arcpy.AlterField_management(out_fc, "NEAR_DIST", "WEIGHTED_CENTER_DIST", "Distance to weighted mean center")
    
    # Calculate min and max of weights
    min_weight = next(arcpy.da.SearchCursor(out_fc, [attr_field], sql_clause=(None, f'ORDER BY {attr_field}')))[0]
    max_weight = next(arcpy.da.SearchCursor(out_fc, [attr_field], sql_clause=(None, f'ORDER BY {attr_field} DESC')))[0]
    
    # Standardize sum of distances
    mean_dist_stats = arcpy.analysis.Statistics(out_fc, "in_memory/sum_sum_distances", [["SUM_DIST", "MEAN"],
                                                                                     ["WEIGHTED_CENTER_DIST", "MEAN"],
                                                                                     ])
    sum_dist_row = next(arcpy.da.SearchCursor(mean_dist_stats, ["MEAN_SUM_DIST", 
                                                                "MEAN_WEIGHTED_CENTER_DIST",
                                                                ]))
    mean_dist = sum_dist_row[0]
    mean_weighted = sum_dist_row[1]
    arcpy.CalculateField_management(out_fc, "TS_SUM_DIST", f"1 / (1 + (!SUM_DIST! / {mean_dist}))", "PYTHON3", "", "DOUBLE")
    arcpy.CalculateField_management(out_fc, "TS_WEIGHTED_CENTER_DIST", f"1 / (1 + (!WEIGHTED_CENTER_DIST! / {mean_weighted}))", "PYTHON3", "", "DOUBLE")
    
    # Calculate min and max of Small-Transform distance fields
    min_ts_dist = next(arcpy.da.SearchCursor(out_fc, ["TS_SUM_DIST"], sql_clause=(None, 'ORDER BY TS_SUM_DIST')))[0]
    max_ts_dist = next(arcpy.da.SearchCursor(out_fc, ["TS_SUM_DIST"], sql_clause=(None, 'ORDER BY TS_SUM_DIST DESC')))[0]
    min_ts_weighted_center = next(arcpy.da.SearchCursor(out_fc, ["TS_WEIGHTED_CENTER_DIST"], sql_clause=(None, 'ORDER BY TS_WEIGHTED_CENTER_DIST')))[0]
    max_ts_weighted_center = next(arcpy.da.SearchCursor(out_fc, ["TS_WEIGHTED_CENTER_DIST"], sql_clause=(None, 'ORDER BY TS_WEIGHTED_CENTER_DIST DESC')))[0]
    
    # Calculate the final index
    with arcpy.da.UpdateCursor(out_fc, ["INTERACTION_INDEX", attr_field, "TS_SUM_DIST", "TS_WEIGHTED_CENTER_DIST"]) as ucur:
        for row in ucur:
            rescaled_attr = rescale(row[1], min_weight, max_weight, 0, 1)
            rescaled_dist = rescale(row[2], min_ts_dist, max_ts_dist, 0, 1)
            rescaled_weighted_center_dist = rescale(row[3], min_ts_weighted_center, max_ts_weighted_center, 0, 1)
            row[0] = rescaled_attr + ((rescaled_dist + rescaled_weighted_center_dist)/2) / 2
            ucur.updateRow(row)
    arcpy.DeleteField_management(out_fc, ["NEAR_FID", "TS_SUM_DIST", "TS_WEIGHTED_CENTER_DIST"])

def MakeFieldMappings(fc, fid_field):
    fieldmappings = arcpy.FieldMappings()
    fieldmappings.addTable(fc)
    
    in_fid_fieldmap = arcpy.FieldMap()
    in_fid_fieldmap.addInputField(fc, fid_field)
    in_fid_field = in_fid_fieldmap.outputField
    in_fid_field.name = 'IN_FID'
    in_fid_field.aliasName = 'IN_FID'
    in_fid_fieldmap.outputField = in_fid_field
    fieldmappings.addFieldMap(in_fid_fieldmap)
    
    return fieldmappings

        
def rescale(val, in_min, in_max, out_min, out_max):
    return out_min + (val - in_min) * ((out_max - out_min) / (in_max - in_min))

# Run the script
if __name__ == '__main__':
    # Get Parameters
    in_dest = arcpy.GetParameterAsText(0)
    attr_field = arcpy.GetParameterAsText(1)
    out_fc = arcpy.GetParameterAsText(2)
    num_neighbors = arcpy.GetParameterAsText(3)

    # Run the main script
    WeightedCentralityScore(in_dest, attr_field, out_fc, num_neighbors)
    
    #renderer = """{"type":"CIMFeatureLayer","name":"gravity","uRI":"CIMPATH=map1/gravity.xml","charts":[{"type":"CIMChart","name":"Scatter Plot 1","series":[{"type":"CIMChartScatterSeries","name":"Series0","uniqueName":"Series0","fields":["HSE_UNITS","INTERACTION_INDEX"],"verticalAxis":1,"colorType":"ColorMatch","visible":true,"dataLabelText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Calibri","fontSize":9,"fontWeight":"Normal","textCase":"Normal"},"markerSymbolProperties":{"type":"CIMChartMarkerSymbolProperties","visible":true,"width":7,"height":7,"style":"Circle","color":{"type":"CIMRGBColor","values":[166,206,227,100]}},"showTrendLine":true,"trendLineSymbolProperties":{"type":"CIMChartLineSymbolProperties","visible":true,"width":2,"style":"Solid","color":{"type":"CIMRGBColor","values":[104,104,104,100]}},"trendLineFitType":"ChartTrendLineFitType_Linear","bubbleMinimumSize":5,"bubbleMaximumSize":30}],"generalProperties":{"type":"CIMChartGeneralProperties","title":"Relationship between Weight Field and Weighted Spatial Interaction Index","showTitle":false,"useAutomaticTitle":false,"showSubTitle":true,"showFooter":true,"titleText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":16,"fontWeight":"Normal","textCase":"Normal"},"subTitleText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Calibri","fontSize":12,"fontWeight":"Normal","textCase":"Normal"},"footerText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":10,"fontWeight":"Normal","textCase":"Normal"},"backgroundSymbolProperties":{"type":"CIMChartFillSymbolProperties","color":{"type":"CIMRGBColor","values":[255,255,255,100]},"opacity":1},"gridLineSymbolProperties":{"type":"CIMChartLineSymbolProperties","visible":true,"width":1,"style":"Solid","color":{"type":"CIMRGBColor","values":[225,225,225,100]}}},"legend":{"type":"CIMChartLegend","visible":true,"showTitle":true,"alignment":"Right","legendText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":10,"fontWeight":"Normal","textCase":"Normal"},"legendTitle":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":10.8,"fontWeight":"Normal","textCase":"Normal"}},"axes":[{"type":"CIMChartAxis","visible":true,"title":"HSE_UNITS","showTitle":true,"useAutomaticTitle":true,"valueFormat":"N2","calculateAutomaticMinimum":true,"calculateAutomaticMaximum":true,"minimum":null,"maximum":null,"titleText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":12,"fontWeight":"Normal","textCase":"Normal"},"labelText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":10,"fontWeight":"Normal","textCase":"Normal"},"axisLineSymbolProperties":{"type":"CIMChartLineSymbolProperties","visible":true,"width":1,"style":"Solid","color":{"type":"CIMRGBColor","values":[156,156,156,100]}},"labelCharacterLimit":11,"navigationScaleFactor":1},{"type":"CIMChartAxis","visible":true,"title":"Weighted Spatial Interaction Index","showTitle":true,"useAutomaticTitle":true,"valueFormat":"N2","dateTimeFormat":"M/d/yyyy","calculateAutomaticMinimum":true,"calculateAutomaticMaximum":true,"minimum":null,"maximum":null,"titleText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":12,"fontWeight":"Normal","textCase":"Normal"},"labelText":{"type":"CIMChartTextProperties","fontFillColor":{"type":"CIMRGBColor","values":[68,68,68,100]},"fontFamilyName":"Segoe UI","fontSize":10,"fontWeight":"Normal","textCase":"Normal"},"axisLineSymbolProperties":{"type":"CIMChartLineSymbolProperties","visible":true,"width":1,"style":"Solid","color":{"type":"CIMRGBColor","values":[156,156,156,100]}},"labelCharacterLimit":11,"navigationScaleFactor":1}],"mapSelectionHandling":"Highlight"}],"renderer":{"type":"CIMClassBreaksRenderer","barrierWeight":"High","breaks":[{"type":"CIMClassBreak","label":"≤0.191534","patch":"Default","symbol":{"type":"CIMSymbolReference","symbol":{"type":"CIMPointSymbol","symbolLayers":[{"type":"CIMVectorMarker","enable":true,"anchorPointUnits":"Relative","dominantSizeAxis3D":"Z","size":4,"billboardMode3D":"FaceNearPlane","frame":{"xmin":-2,"ymin":-2,"xmax":2,"ymax":2},"markerGraphics":[{"type":"CIMMarkerGraphic","geometry":{"curveRings":[[[1.2246467991473532e-16,2],{"a":[[1.2246467991473532e-16,2],[2.2962127484012875e-16,0],0,1]}]]},"symbol":{"type":"CIMPolygonSymbol","symbolLayers":[{"type":"CIMSolidStroke","enable":true,"capStyle":"Round","joinStyle":"Round","lineStyle3D":"Strip","miterLimit":10,"width":0.7,"color":{"type":"CIMRGBColor","values":[0,0,0,100]}},{"type":"CIMSolidFill","enable":true,"color":{"type":"CIMRGBColor","values":[230,238,207,100]}}]}}],"respectFrame":true}],"haloSize":1,"scaleX":1,"angleAlignment":"Display"}},"upperBound":0.19153403887632328},{"type":"CIMClassBreak","label":"≤0.248743","patch":"Default","symbol":{"type":"CIMSymbolReference","symbol":{"type":"CIMPointSymbol","symbolLayers":[{"type":"CIMVectorMarker","enable":true,"anchorPointUnits":"Relative","dominantSizeAxis3D":"Z","size":4,"billboardMode3D":"FaceNearPlane","frame":{"xmin":-2,"ymin":-2,"xmax":2,"ymax":2},"markerGraphics":[{"type":"CIMMarkerGraphic","geometry":{"curveRings":[[[1.2246467991473532e-16,2],{"a":[[1.2246467991473532e-16,2],[2.2962127484012875e-16,0],0,1]}]]},"symbol":{"type":"CIMPolygonSymbol","symbolLayers":[{"type":"CIMSolidStroke","enable":true,"capStyle":"Round","joinStyle":"Round","lineStyle3D":"Strip","miterLimit":10,"width":0.7,"color":{"type":"CIMRGBColor","values":[0,0,0,100]}},{"type":"CIMSolidFill","enable":true,"color":{"type":"CIMRGBColor","values":[155,196,193,100]}}]}}],"respectFrame":true}],"haloSize":1,"scaleX":1,"angleAlignment":"Display"}},"upperBound":0.24874315911026845},{"type":"CIMClassBreak","label":"≤0.325766","patch":"Default","symbol":{"type":"CIMSymbolReference","symbol":{"type":"CIMPointSymbol","symbolLayers":[{"type":"CIMVectorMarker","enable":true,"anchorPointUnits":"Relative","dominantSizeAxis3D":"Z","size":4,"billboardMode3D":"FaceNearPlane","frame":{"xmin":-2,"ymin":-2,"xmax":2,"ymax":2},"markerGraphics":[{"type":"CIMMarkerGraphic","geometry":{"curveRings":[[[1.2246467991473532e-16,2],{"a":[[1.2246467991473532e-16,2],[2.2962127484012875e-16,0],0,1]}]]},"symbol":{"type":"CIMPolygonSymbol","symbolLayers":[{"type":"CIMSolidStroke","enable":true,"capStyle":"Round","joinStyle":"Round","lineStyle3D":"Strip","miterLimit":10,"width":0.7,"color":{"type":"CIMRGBColor","values":[0,0,0,100]}},{"type":"CIMSolidFill","enable":true,"color":{"type":"CIMRGBColor","values":[105,168,183,100]}}]}}],"respectFrame":true}],"haloSize":1,"scaleX":1,"angleAlignment":"Display"}},"upperBound":0.3257658497960716},{"type":"CIMClassBreak","label":"≤0.544829","patch":"Default","symbol":{"type":"CIMSymbolReference","symbol":{"type":"CIMPointSymbol","symbolLayers":[{"type":"CIMVectorMarker","enable":true,"anchorPointUnits":"Relative","dominantSizeAxis3D":"Z","size":4,"billboardMode3D":"FaceNearPlane","frame":{"xmin":-2,"ymin":-2,"xmax":2,"ymax":2},"markerGraphics":[{"type":"CIMMarkerGraphic","geometry":{"curveRings":[[[1.2246467991473532e-16,2],{"a":[[1.2246467991473532e-16,2],[2.2962127484012875e-16,0],0,1]}]]},"symbol":{"type":"CIMPolygonSymbol","symbolLayers":[{"type":"CIMSolidStroke","enable":true,"capStyle":"Round","joinStyle":"Round","lineStyle3D":"Strip","miterLimit":10,"width":0.7,"color":{"type":"CIMRGBColor","values":[0,0,0,100]}},{"type":"CIMSolidFill","enable":true,"color":{"type":"CIMRGBColor","values":[75,126,152,100]}}]}}],"respectFrame":true}],"haloSize":1,"scaleX":1,"angleAlignment":"Display"}},"upperBound":0.5448290513745799},{"type":"CIMClassBreak","label":"≤1.146384","patch":"Default","symbol":{"type":"CIMSymbolReference","symbol":{"type":"CIMPointSymbol","symbolLayers":[{"type":"CIMVectorMarker","enable":true,"anchorPointUnits":"Relative","dominantSizeAxis3D":"Z","size":4,"billboardMode3D":"FaceNearPlane","frame":{"xmin":-2,"ymin":-2,"xmax":2,"ymax":2},"markerGraphics":[{"type":"CIMMarkerGraphic","geometry":{"curveRings":[[[1.2246467991473532e-16,2],{"a":[[1.2246467991473532e-16,2],[2.2962127484012875e-16,0],0,1]}]]},"symbol":{"type":"CIMPolygonSymbol","symbolLayers":[{"type":"CIMSolidStroke","enable":true,"capStyle":"Round","joinStyle":"Round","lineStyle3D":"Strip","miterLimit":10,"width":0.7,"color":{"type":"CIMRGBColor","values":[0,0,0,100]}},{"type":"CIMSolidFill","enable":true,"color":{"type":"CIMRGBColor","values":[46,85,122,100]}}]}}],"respectFrame":true}],"haloSize":1,"scaleX":1,"angleAlignment":"Display"}},"upperBound":1.1463836102866494}],"classBreakType":"GraduatedColor","classificationMethod":"NaturalBreaks","colorRamp":{"type":"CIMFixedColorRamp","colorSpace":{"type":"CIMICCColorSpace","url":"Default RGB"},"colors":[{"type":"CIMRGBColor","colorSpace":{"type":"CIMICCColorSpace","url":"Default RGB"},"values":[230,238,207,100]},{"type":"CIMRGBColor","colorSpace":{"type":"CIMICCColorSpace","url":"Default RGB"},"values":[155,196,193,100]},{"type":"CIMRGBColor","colorSpace":{"type":"CIMICCColorSpace","url":"Default RGB"},"values":[105,168,183,100]},{"type":"CIMRGBColor","colorSpace":{"type":"CIMICCColorSpace","url":"Default RGB"},"values":[75,126,152,100]},{"type":"CIMRGBColor","colorSpace":{"type":"CIMICCColorSpace","url":"Default RGB"},"values":[46,85,122,100]}],"arrangement":"Default"},"field":"INTERACTION_INDEX","minimumBreak":0.0537282476852565,"numberFormat":{"type":"CIMNumericFormat","alignmentOption":"esriAlignLeft","alignmentWidth":0,"roundingOption":"esriRoundNumberOfDecimals","roundingValue":6,"zeroPad":true},"showInAscendingOrder":true,"heading":"Weighted Spatial Interaction Index","sampleSize":10000,"defaultSymbolPatch":"Default","defaultSymbol":{"type":"CIMSymbolReference","symbol":{"type":"CIMPointSymbol","symbolLayers":[{"type":"CIMVectorMarker","enable":true,"anchorPointUnits":"Relative","dominantSizeAxis3D":"Z","size":4,"billboardMode3D":"FaceNearPlane","frame":{"xmin":-2,"ymin":-2,"xmax":2,"ymax":2},"markerGraphics":[{"type":"CIMMarkerGraphic","geometry":{"curveRings":[[[1.2246467991473532e-16,2],{"a":[[1.2246467991473532e-16,2],[2.2962127484012875e-16,0],0,1]}]]},"symbol":{"type":"CIMPolygonSymbol","symbolLayers":[{"type":"CIMSolidStroke","enable":true,"capStyle":"Round","joinStyle":"Round","lineStyle3D":"Strip","miterLimit":10,"width":0.7,"color":{"type":"CIMRGBColor","values":[0,0,0,100]}},{"type":"CIMSolidFill","enable":true,"color":{"type":"CIMRGBColor","values":[130,130,130,100]}}]}}],"respectFrame":true}],"haloSize":1,"scaleX":1,"angleAlignment":"Display"}},"defaultLabel":"<out of range>","polygonSymbolColorTarget":"Fill","normalizationType":"Nothing","exclusionLabel":"<excluded>","exclusionSymbol":{"type":"CIMSymbolReference","symbol":{"type":"CIMPointSymbol","symbolLayers":[{"type":"CIMVectorMarker","enable":true,"anchorPointUnits":"Relative","dominantSizeAxis3D":"Z","size":4,"billboardMode3D":"FaceNearPlane","frame":{"xmin":-2,"ymin":-2,"xmax":2,"ymax":2},"markerGraphics":[{"type":"CIMMarkerGraphic","geometry":{"curveRings":[[[1.2246467991473532e-16,2],{"a":[[1.2246467991473532e-16,2],[2.2962127484012875e-16,0],0,1]}]]},"symbol":{"type":"CIMPolygonSymbol","symbolLayers":[{"type":"CIMSolidStroke","enable":true,"capStyle":"Round","joinStyle":"Round","lineStyle3D":"Strip","miterLimit":10,"width":0.7,"color":{"type":"CIMRGBColor","values":[0,0,0,100]}},{"type":"CIMSolidFill","enable":true,"color":{"type":"CIMRGBColor","values":[255,0,0,100]}}]}}],"respectFrame":true}],"haloSize":1,"scaleX":1,"angleAlignment":"Display"}},"useExclusionSymbol":false,"exclusionSymbolPatch":"Default","visualVariables":[{"type":"CIMSizeVisualVariable","authoringInfo":{"type":"CIMVisualVariableAuthoringInfo","minSliderValue":1,"maxSliderValue":1602,"heading":"HSE_UNITS"},"randomMax":1,"minSize":4,"maxSize":30,"minValue":1,"maxValue":1602,"valueRepresentation":"Radius","variableType":"Graduated","valueShape":"Unknown","axis":"HeightAxis","normalizationType":"Nothing","valueExpressionInfo":{"type":"CIMExpressionInfo","title":"Custom","expression":"$feature.HSE_UNITS","returnType":"Default"}}]},"scaleSymbols":true,"snappable":true,"symbolLayerDrawing":{"type":"CIMSymbolLayerDrawing"}}"""
    #renderer = renderer.replace("HSE_UNITS", attr_field)
    #arcpy.SetParameterSymbology(2, f"JSONCIMDEF={renderer}")