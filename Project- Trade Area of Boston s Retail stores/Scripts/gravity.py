'''----------------------------------------------------------------------------------
 Tool Name:   Gravity Model
 Source Name: gravity.py
 Version:     ArcGIS 10.0
 Author:      ESRI, Inc.
 Required Arguments:
              Input Destinations (Feature Layer)
              Destination Name Field (Field)
              Destination Attractiveness Field (Field)
              Input Origins (Features Layer)
              Output Feature Class (Feature Class)
 Optional Arguments:
              NA

 Description: Calculates the probabilistic attraction an origin will feel towards a destination based on the distance
               between that origin and destination and the attractiveness (or mass, or utility) of the destination.
----------------------------------------------------------------------------------'''

# Import system modules
import arcpy
import os
import sys

# Main function, all functions run in GravityModel
def GravityModel(in_dest, name_field, attr_field, in_orig, out_fc):
    # Make sure ArcInfo license is available
    if arcpy.ProductInfo().lower() not in ['arcinfo']:
        arcpy.AddError("Tool requires an ArcInfo license.")
        sys.exit()

    # Set geoprocessing environments
    arcpy.env.overwriteOutput = True
    arcpy.env.qualifiedFieldNames = False

    # Calculate distances between all origins and destinations
    nearmatrix = arcpy.analysis.GenerateNearTable(in_orig, in_dest, "in_memory/neartable", "", "", "", False)
    arcpy.management.AddField(nearmatrix, "num", "DOUBLE")
    arcpy.management.AddField(nearmatrix, "prob", "DOUBLE")

    # Transform NEAR_DIST values to scale of 0-10
    minmaxstats = arcpy.analysis.Statistics(nearmatrix, "in_memory/minmaxstats", [["NEAR_DIST", "MIN"],["NEAR_DIST", "MAX"]])
    # Read the min and max values
    scur = arcpy.SearchCursor(minmaxstats)
    try:
        for row in scur:
            min = row.getValue(arcpy.ValidateFieldName("MIN_NEAR_DIST"))
            max = row.getValue(arcpy.ValidateFieldName("MAX_NEAR_DIST"))
    except:
        raise
    finally:
        if scur:
            del scur
    # Perform calculation
    arcpy.management.CalculateField(nearmatrix, "NEAR_DIST", """((!NEAR_DIST! - %s) / (float(%s) - %s)) * 10""" % (min, max + 0.000001, min), "PYTHON")

    # Join store attributes to the near table
    arcpy.management.MakeTableView(nearmatrix, "nearmatrix")
    arcpy.management.AddJoin("nearmatrix", "NEAR_FID", in_dest, arcpy.Describe(in_dest).OIDFieldName)

    # Calculate the gravity model numerator (mass X inverse exp distanceX2)
    #arcpy.management.CalculateField("nearmatrix", "num", "(!%s! * (1 / ((!NEAR_DIST! * !NEAR_DIST!) + 0.0000000001))) * 10000000" % attr_field, "PYTHON")
    arcpy.management.CalculateField("nearmatrix", "num", "!%s! * (1.0 / math.exp(2.0*!NEAR_DIST!))" % attr_field, "PYTHON")
    arcpy.management.RemoveJoin("nearmatrix", os.path.splitext(arcpy.Describe(in_dest).name)[0])

    # Calculate the gravity model denominator (SUM of mass X inverse distance squared for each origin) and probability
    sumstats = arcpy.analysis.Statistics("nearmatrix", "in_memory/sumstats", "num SUM", "IN_FID")
    arcpy.management.AddJoin("nearmatrix", "IN_FID", sumstats, "IN_FID")
    arcpy.management.CalculateField("nearmatrix", "prob", "!num! / !SUM_num!", "PYTHON")
    arcpy.management.RemoveJoin("nearmatrix", os.path.splitext(os.path.basename(sumstats.getOutput(0)))[0])

    # Create the pivoted probability table (the destination names become attribute fields)
    arcpy.management.AddJoin("nearmatrix", "NEAR_FID", in_dest, arcpy.Describe(in_dest).OIDFieldName)
    pivot = arcpy.management.PivotTable("nearmatrix", "neartable.IN_FID", "%s.%s" % (os.path.splitext(arcpy.Describe(in_dest).name)[0], name_field), "neartable.prob", "in_memory/pivoted")

    # Find fields in the probability table
    keepfields = ["pivoted_%s" % field.name for field in arcpy.ListFields(pivot) if not field.required]

    # Join the probability table to the origins layers
    arcpy.management.MakeFeatureLayer(in_orig, "origins")
    arcpy.management.AddJoin("origins", arcpy.Describe(in_orig).OIDFieldName, pivot, "IN_FID")

    # Copy the origins with joined probabilities as the output feature class
    # First create field mappings, to contain only fields from the probability table, none from the origins layer
    fieldmappings = arcpy.FieldMappings()
    fieldmappings.addTable("origins")
    for field in fieldmappings.fields:
        if field.name not in keepfields:
            fieldmappings.removeFieldMap(fieldmappings.findFieldMapIndex(field.name))
        else:
            fieldmap = fieldmappings.getFieldMap(fieldmappings.findFieldMapIndex(field.name))
            fld = fieldmap.outputField
            fld.name = fld.aliasName = field.name.replace("pivoted_", "")
            fieldmap.outputField = fld
            fieldmappings.replaceFieldMap(fieldmappings.findFieldMapIndex(field.name), fieldmap)

    # Now perform the copy
    arcpy.conversion.FeatureClassToFeatureClass("origins", os.path.dirname(out_fc), os.path.basename(out_fc), "", fieldmappings)

    # Find the destination with the largest probability for each origin
    market_dict = {}
    scur = arcpy.SearchCursor("nearmatrix", "", "", ";".join(["neartable.IN_FID", "neartable.NEAR_FID", "%s.%s" % (os.path.splitext(arcpy.Describe(in_dest).name)[0], name_field), "neartable.prob"]))
    try:
        for row in scur:
            try:
                if row.getValue("neartable.prob") > market_dict[row.getValue("neartable.IN_FID")][1]:
                    market_dict[row.getValue("neartable.IN_FID")] = [row.getValue("%s.%s" % (os.path.splitext(arcpy.Describe(in_dest).name)[0], name_field)), row.getValue("neartable.prob")]
            except:
                market_dict[row.getValue("neartable.IN_FID")] = [row.getValue("%s.%s" % (os.path.splitext(arcpy.Describe(in_dest).name)[0], name_field)), row.getValue("neartable.prob")]
    except:
        raise
    finally:
        if scur:
            del scur

    # Write the destination with the highest probability to the output feature class
    #arcpy.management.AddField(out_fc, "HIGH_DEST", "TEXT", "", "", len(max([values[0] for values in market_dict.values()], key=len)))
    arcpy.management.AddField(out_fc, "HIGH_DEST", "TEXT")
    ucur = arcpy.UpdateCursor(out_fc, "", "", ";".join(["IN_FID", "HIGH_DEST"]))
    try:
        for row in ucur:
            row.setValue("HIGH_DEST", market_dict[row.getValue("IN_FID")][0])
            ucur.updateRow(row)
    except:
        raise
    finally:
        if ucur:
            del ucur

    for data in ["nearmatrix", "origins", nearmatrix, sumstats, minmaxstats, pivot]:
        arcpy.management.Delete(data)

# Run the script
if __name__ == '__main__':
    # Get Parameters
    in_dest = arcpy.GetParameterAsText(0)
    name_field = arcpy.GetParameterAsText(1)
    attr_field = arcpy.GetParameterAsText(2)
    in_orig = arcpy.GetParameterAsText(3)
    out_fc = arcpy.GetParameterAsText(4)

    # Run the main script
    GravityModel(in_dest, name_field, attr_field, in_orig, out_fc)