# Import system modules
import arcpy
import os
import sys

# Main function, all functions run in GravityModel
def Gravity(in_dest, attr_field, out_fc, num_neighbors, radius, out_weights):
    # Make sure ArcInfo license is available
    if arcpy.ProductInfo().lower() not in ['arcinfo']:
        arcpy.AddError("Tool requires an ArcInfo license.")
        sys.exit()

    # Set geoprocessing environments
    arcpy.env.overwriteOutput = True
    arcpy.env.qualifiedFieldNames = False

    # Make output feature class
    dest_desc = arcpy.Describe(in_dest)
    fieldmappings = MakeFieldMappings(in_dest, dest_desc.OIDFieldName)
    arcpy.FeatureClassToFeatureClass_conversion(in_dest, os.path.dirname(out_fc), os.path.basename(out_fc), "", fieldmappings)
        
    # Calculate distances between all origins and destinations
    if not out_weights:
        out_weights = f"{os.path.dirname(out_fc)}/gravity_near_table"
    nearmatrix = arcpy.analysis.GenerateNearTable(in_dest, in_dest, out_weights, radius, "", "", False, num_neighbors)#, "GEODESIC") #geodesic too slow for polys
    arcpy.Append_management(in_dest, nearmatrix, "NO_TEST", f'IN_FID "IN_FID" true true false 4 Long 0 0,First,#,{in_dest},{dest_desc.OIDFieldName},-1,-1;NEAR_FID "NEAR_FID" true true false 4 Long 0 0,First,#,{in_dest},{dest_desc.OIDFieldName},-1,-1')
    with arcpy.da.UpdateCursor(nearmatrix, ["NEAR_DIST"], "IN_FID = NEAR_FID") as ucur:
        for row in ucur:
            row[0] = 0
            ucur.updateRow(row)
    distance_attr_field = f"{attr_field}_X_INVDIST"
    arcpy.management.AddField(nearmatrix, distance_attr_field, "DOUBLE", "", "", "", f"{attr_field} Multiplied By Inverse Distance")
    arcpy.management.DeleteField(nearmatrix, "NEAR_RANK")
    arcpy.SetProgressor("step", "", 1,8,1)
    arcpy.SetProgressorPosition()
    arcpy.SetProgressorLabel("1/6 Generated distance matrix")  

    min_dist = 0 #next(arcpy.da.SearchCursor(nearmatrix, ["NEAR_DIST"], sql_clause=(None, 'ORDER BY NEAR_DIST')))[0]
    max_dist = next(arcpy.da.SearchCursor(nearmatrix, ["NEAR_DIST"], sql_clause=(None, 'ORDER BY NEAR_DIST DESC')))[0]
    
    # Calculate the spatial interaction scores per dest-origin pair
    arcpy.JoinField_management(nearmatrix, "IN_FID", in_dest, dest_desc.OIDFieldName, attr_field)
    arcpy.AlterField_management(nearmatrix, attr_field, f"{attr_field}_IN", clear_field_alias=True)
    arcpy.JoinField_management(nearmatrix, "NEAR_FID", in_dest, dest_desc.OIDFieldName, attr_field)
    arcpy.AlterField_management(nearmatrix, attr_field, f"{attr_field}_NEAR", clear_field_alias=True)
    arcpy.SetProgressorPosition()
    arcpy.SetProgressorLabel(f"2/6 Added {attr_field} to matrix") 
    
    with arcpy.da.UpdateCursor(nearmatrix, [distance_attr_field, "NEAR_DIST", f"{attr_field}_NEAR"]) as ucur:
        for row in ucur:
            row[0] = row[2] * (1/rescale(row[1], min_dist, max_dist, 1, 10))
            ucur.updateRow(row)
    arcpy.SetProgressorPosition()
    arcpy.SetProgressorLabel("3/6 Calculated weight x inv. distance")    
    
    # Calculate Probability
    sumnum = arcpy.analysis.Statistics(nearmatrix, "in_memory/sumnum", [[distance_attr_field, "SUM"]], "IN_FID")
    arcpy.JoinField_management(nearmatrix, "IN_FID", sumnum, "IN_FID", f"SUM_{distance_attr_field}")
    arcpy.CalculateField_management(nearmatrix, "PROBABILITY", f"(!{distance_attr_field}! / !SUM_{distance_attr_field}!) * 100", "PYTHON3", "", "DOUBLE")
    arcpy.AlterField_management(nearmatrix, "PROBABILITY", "", "Movement Probability %")
    arcpy.CalculateField_management(nearmatrix, f"{attr_field}_MOVEMENT", f"(!PROBABILITY!/100) * !{attr_field}_IN!", "PYTHON3", "", "DOUBLE")
    arcpy.AlterField_management(nearmatrix, f"{attr_field}_MOVEMENT", "", f"{attr_field} Projected Movement")
    arcpy.DeleteField_management(nearmatrix, [f"{attr_field}_X_INVDIST", f"SUM_{attr_field}_X_INVDIST"])
    arcpy.SetProgressorPosition()
    arcpy.SetProgressorLabel("4/6 Calculated and summarized probabilities")  
    
    # Join 
    score_stats = arcpy.Statistics_analysis(nearmatrix, "in_memory/score_stats", [["PROBABILITY", "SUM"], [f"{attr_field}_MOVEMENT","SUM"]], "NEAR_FID")
    arcpy.JoinField_management(out_fc, "IN_FID", score_stats, "NEAR_FID", ["SUM_PROBABILITY", f"SUM_{attr_field}_MOVEMENT"])
    arcpy.AlterField_management(out_fc, "SUM_PROBABILITY", "GRAVITY_INDEX", "Gravity Index (High values have higher weights and spatial interaction/influence)")
    arcpy.CalculateField_management(out_fc, f"{attr_field}_NET_MOVEMENT", f"((!SUM_{attr_field}_MOVEMENT! - !{attr_field}!) / !{attr_field}!)*100", "PYTHON3", "", "DOUBLE")
    arcpy.AlterField_management(out_fc, f"{attr_field}_NET_MOVEMENT", "", f"{attr_field} Net Projected Movement %")
    arcpy.DeleteField_management(out_fc, f"SUM_{attr_field}_MOVEMENT")
    arcpy.SetProgressorPosition()
    arcpy.SetProgressorLabel("5/6 Calculate gravity index and net movement")  
    
    # Calculate the highest attraction feature
    maxprob = arcpy.analysis.Statistics(nearmatrix, f"{os.path.dirname(out_fc)}/maxprob", "PROBABILITY MAX", "IN_FID")
    arcpy.SetProgressorPosition()
    arcpy.SetProgressorLabel("6/6 Calculating highest probabilities")
    arcpy.JoinField_management(maxprob, "MAX_PROBABILITY", nearmatrix, "PROBABILITY", "NEAR_FID")
    arcpy.JoinField_management(out_fc, "IN_FID", maxprob, "IN_FID", "NEAR_FID")
    arcpy.Delete_management(maxprob)
    arcpy.AlterField_management(out_fc, "NEAR_FID", "MAX_PROB_IN_FID", "IN_FID With Highest Movement Probability")
    
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
    radius = arcpy.GetParameterAsText(4)
    out_weights = arcpy.GetParameterAsText(5)

    # Run the main script
    Gravity(in_dest, attr_field, out_fc, num_neighbors, radius, out_weights)
    
    try:
        if arcpy.Describe(out_fc).shapeType ==  "Polygon":
            arcpy.SetParameterSymbology(2, os.path.join(os.path.dirname(sys.path[0]), "Templates", "gravity_full_poly.lyrx"))
        else:
            arcpy.SetParameterSymbology(2, os.path.join(os.path.dirname(sys.path[0]), "Templates", "gravity_full.lyrx"))
    except:
        pass