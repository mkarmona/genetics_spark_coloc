"""
Utilities to perform colocalisation analysis
"""

import pyspark.sql.functions as F
import pyspark.sql.column as Column


def logsum(logABF: Column):
    """
    This function calculates the log of the sum of the exponentiated
    logs taking out the max, i.e. insuring that the sum is not Inf
    Numpy equivalent:
    themax = np.max(logABF)
    result = themax + np.log(np.sum(np.exp(logABF - themax)))
    """
    themax = F.array_max(logABF)
    expVector = F.transform(logABF, lambda c: F.exp(c - themax))
    summedval = F.aggregate(expVector, F.lit(0.0), lambda acc, x: acc + x)
    result = themax + F.log(summedval)
    return result


def posteriors(allABF: Column):
    """
    Calculates the posterior probability of each hypothesis given the evidence.
    Numpy equivalent:
    diff = allAbfs - getLogsum(allAbfs)
    abfsPosteriors = np.exp(diff)
    """
    theLogsum = logsum(allABF)
    diff = F.transform(allABF, lambda c: F.exp(c - theLogsum))
    return diff


def colocalisation(overlappingSignals, priorc1, priorc2, priorc12):
    """
    Compute Bayesian colocalisation analysis for all pairs of credible sets

    Args:
        overlappingSignals: DataFrame with overlapping signals
    """

    coloc = (
        overlappingSignals.withColumn(
            "sum_logABF",
            F.expr(
                "transform(arrays_zip(left_logABF, right_logABF), x -> x.left_logABF + x.right_logABF)"
            ),
        )
        # TODO: add coloc_n_vars variable with size of the vector for backwards compatibility
        .withColumn("logsum1", logsum(F.col("left_logABF")))
        .withColumn("logsum2", logsum(F.col("right_logABF")))
        .withColumn("logsum12", logsum(F.col("sum_logABF")))
        .drop("left_logABF", "right_logABF", "sum_logABF")
        # Add priors
        # priorc1 Prior on variant being causal for trait 1
        .withColumn("priorc1", F.lit(priorc1))
        # priorc2 Prior on variant being causal for trait 2
        .withColumn("priorc2", F.lit(priorc2))
        # priorc12 Prior on variant being causal for traits 1 and 2
        .withColumn("priorc12", F.lit(priorc12))
        # h0-h2
        .withColumn("lH0abf", F.lit(0.0))
        .withColumn("lH1abf", F.log(F.col("priorc1")) + F.col("logsum1"))
        .withColumn("lH2abf", F.log(F.col("priorc2")) + F.col("logsum2"))
        # h3
        .withColumn("sumlogsum", F.col("logsum1") + F.col("logsum2"))
        # exclude null H3/H4s: due to sumlogsum == logsum12
        .filter(F.col("sumlogsum") != F.col("logsum12"))
        .withColumn("max", F.greatest("sumlogsum", "logsum12"))
        .withColumn(
            "logdiff",
            (
                F.col("max")
                + F.log(
                    F.exp(F.col("sumlogsum") - F.col("max"))
                    - F.exp(F.col("logsum12") - F.col("max"))
                )
            ),
        )
        .withColumn(
            "lH3abf",
            F.log(F.col("priorc1")) + F.log(F.col("priorc2")) + F.col("logdiff"),
        )
        .drop("right_logsum", "left_logsum", "sumlogsum", "max", "logdiff")
        # h4
        .withColumn("lH4abf", F.log(F.col("priorc12")) + F.col("logsum12"))
        # # cleaning
        .drop("priorc1", "priorc2", "priorc12", "logsum1", "logsum2", "logsum12")
        # posteriors
        .withColumn(
            "allABF",
            F.array(
                F.col("lH0abf"),
                F.col("lH1abf"),
                F.col("lH2abf"),
                F.col("lH3abf"),
                F.col("lH4abf"),
            ),
        )
        .withColumn("posteriors", posteriors(F.col("allABF")))
        .withColumn("coloc_h0", F.col("posteriors").getItem(0))
        .withColumn("coloc_h1", F.col("posteriors").getItem(1))
        .withColumn("coloc_h2", F.col("posteriors").getItem(2))
        .withColumn("coloc_h3", F.col("posteriors").getItem(3))
        .withColumn("coloc_h4", F.col("posteriors").getItem(4))
        .withColumn("coloc_h4_h3", F.col("coloc_h4") / F.col("coloc_h3"))
        .withColumn("coloc_log2_h4_h3", F.log2(F.col("coloc_h4_h3")))
        # clean up
        .drop("posteriors", "allABF", "lH0abf", "lH1abf", "lH2abf", "lH3abf", "lH4abf")
    )
    return coloc
