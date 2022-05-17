import pyspark.sql.functions as F
from pyspark.sql import SparkSession
from pyspark.sql.window import Window


def findOverlappingSignals(spark: SparkSession, credSetPath: str):
    """
    Find overlapping signals between all pairs of cred sets (exploded at the tag variant level)

    Args:
        spark: SparkSession
        credSetPath: Path to credible sets

    """

    # Columnns to be used as left and right
    idCols = [
        "studyKey",
        "lead_variant_id",
        "type",
    ]
    metadataCols = [
        "study_id",
        "phenotype_id",
        "bio_feature",
        "lead_chrom",
        "lead_pos",
        "lead_ref",
        "lead_alt",
    ]

    wind1 = Window.partitionBy(idCols)
    credSet = (
        spark.read.parquet(credSetPath)
        .withColumn(
            "studyKey",
            F.concat_ws("_", *["type", "study_id", "phenotype_id", "bio_feature"]),
        )
        # Exclude studies without logABFs available
        .filter(F.col("logABF").isNotNull())
        # Creating nested map with all tags in the study-lead variant
        .withColumn(
            "all_tags",
            F.map_from_entries(
                F.collect_list(F.struct("tag_variant_id", "logABF")).over(wind1)
            ),
        )
        .select(idCols + metadataCols + ["tag_variant_id", "all_tags"])
    )

    # Self join with complex condition. Left it's all gwas and right can be gwas or molecular trait
    colsToRename = idCols + metadataCols + ["all_tags"]
    overlappingPeaks = (
        credSet.alias("left")
        .filter(F.col("type") == "gwas")
        .join(
            credSet.alias("right"),
            on=[
                F.col("left.tag_variant_id") == F.col("right.tag_variant_id"),
                (F.col("right.type") != "gwas")
                | (F.col("left.studyKey") > F.col("right.studyKey")),
            ],
            how="inner",
        )
        .drop("left.tag_variant_id", "right.tag_variant_id")
        # Rename columns to make them unambiguous
        .selectExpr(
            *["left." + col + " as " + "left_" + col for col in colsToRename]
            + ["right." + col + " as " + "right_" + col for col in colsToRename]
        )
        # Keep only one record per overlapping peak
        .dropDuplicates(["left_" + i for i in idCols] + ["right_" + i for i in idCols])
    )

    #  For each comparison, logABF vectors are the same size mapped by tag_variant_id (incl 0.0 on empty)
    overlappingPeaksWithArrays = (
        overlappingPeaks.withColumn(
            "left_logABF",
            F.map_values(
                F.map_zip_with(
                    "left_all_tags",
                    "right_all_tags",
                    lambda k, v1, v2: F.coalesce(v1, F.lit(0.0)),
                )
            ),
        )
        .withColumn(
            "right_logABF",
            F.map_values(
                F.map_zip_with(
                    "left_all_tags",
                    "right_all_tags",
                    lambda k, v1, v2: F.coalesce(v2, F.lit(0.0)),
                )
            ),
        )
        .drop("right_all_tags", "left_all_tags")
    )

    return overlappingPeaksWithArrays
